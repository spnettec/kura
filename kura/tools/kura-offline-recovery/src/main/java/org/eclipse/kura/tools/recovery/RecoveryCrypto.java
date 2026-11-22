/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import java.io.InputStream;
import java.nio.channels.Channels;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.FileTime;
import java.nio.file.attribute.PosixFilePermission;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import org.eclipse.kura.core.crypto.CryptoServiceImpl;

/** Explicit private key selection shared by diagnostic and controlled recovery readers. */
final class RecoveryCrypto {
    private RecoveryCrypto() { }

    static CryptoServiceImpl load(Path keyFile, Path ringFile, String ringSha256, boolean useDefault)
            throws Exception {
        require((keyFile != null ? 1 : 0) + (ringFile != null ? 1 : 0) + (useDefault ? 1 : 0) == 1);
        require((ringFile != null) == (ringSha256 != null));
        require(ringSha256 == null || ringSha256.matches("[0-9a-f]{64}"));
        if (useDefault) {
            return CryptoServiceImpl.forSnapshotRecovery(null, true);
        }
        byte[] raw = readPrivate(ringFile != null ? ringFile : keyFile, ringFile != null ? 512 : 32);
        try {
            if (ringFile != null) {
                String actual = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(raw));
                require(actual.equals(ringSha256));
                return CryptoServiceImpl.forKeyRingRecovery(raw);
            }
            return CryptoServiceImpl.forSnapshotRecovery(raw, false);
        } finally {
            Arrays.fill(raw, (byte) 0);
        }
    }

    /** Only PID1's credential directory is selected by production callers, never a manifest path. */
    static CryptoServiceImpl loadManaged(Path directory, String keySha256, String ringSha256) throws Exception {
        require(directory != null && directory.isAbsolute() && directory.normalize().equals(directory)
                && Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS));
        require(keySha256 != null && keySha256.matches("[0-9a-f]{64}"));
        require(ringSha256 != null && (ringSha256.equals("none") || ringSha256.matches("[0-9a-f]{64}")));
        Path activePath = directory.resolve("kura_encryption_key");
        Path ringPath = directory.resolve("kura_encryption_keyring");
        byte[] active = readPrivate(activePath, 32, true);
        byte[] ring = null;
        try {
            require(HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(active)).equals(keySha256));
            if (ringSha256.equals("none")) {
                require(Files.notExists(ringPath, LinkOption.NOFOLLOW_LINKS));
                return CryptoServiceImpl.forSnapshotRecovery(active, false);
            }
            ring = readPrivate(ringPath, 512, true);
            require(HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(ring)).equals(ringSha256));
            return CryptoServiceImpl.forKeyRingRecovery(ring, active);
        } finally {
            Arrays.fill(active, (byte) 0);
            if (ring != null) { Arrays.fill(ring, (byte) 0); }
        }
    }

    private static byte[] readPrivate(Path path, int limit) throws Exception {
        return readPrivate(path,limit,false);
    }

    private static byte[] readPrivate(Path path, int limit, boolean loaded) throws Exception {
        require(path.isAbsolute() && Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS));
        require(Files.isDirectory(path.getParent(), LinkOption.NOFOLLOW_LINKS));
        var parent = Files.getPosixFilePermissions(path.getParent(), LinkOption.NOFOLLOW_LINKS);
        require(!parent.contains(PosixFilePermission.GROUP_WRITE) && !parent.contains(PosixFilePermission.OTHERS_WRITE));
        var permissions = Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS);
        Map<String, Object> before = Files.readAttributes(path,
                "unix:dev,ino,size,uid,gid,mode,nlink,lastModifiedTime,ctime", LinkOption.NOFOLLOW_LINKS);
        require(Integer.valueOf(1).equals(before.get("nlink")));
        String aclDigest=null;
        if(permissions.stream().anyMatch(p -> p.name().startsWith("GROUP") || p.name().startsWith("OTHERS"))) {
            // PID1 may use a root-owned 0440 file with an exact service-UID ACL.
            // Reuse native ACL parsing; plain group-readable legacy files remain refused.
            require(loaded && (Integer.valueOf(0100440).equals(before.get("mode")))
                    && Integer.valueOf(0).equals(before.get("uid")) && Files.getFileStore(path).isReadOnly());
            aclDigest=loadedProof(path,before);
        }
        byte[] value = null;
        boolean accepted = false;
        try {
            try (var channel = Files.newByteChannel(path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS);
                    InputStream input = Channels.newInputStream(channel)) {
                value = input.readNBytes(limit + 1);
                require(value.length > 0 && value.length <= limit);
                Map<String, Object> after = Files.readAttributes(path,
                        "unix:dev,ino,size,uid,gid,mode,nlink,lastModifiedTime,ctime", LinkOption.NOFOLLOW_LINKS);
                require(before.equals(after) && Long.valueOf(value.length).equals(before.get("size")));
                require(aclDigest==null || aclDigest.equals(HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value))));
            }
            accepted = true;
            return value;
        } finally {
            if (!accepted && value != null) {
                Arrays.fill(value, (byte) 0);
            }
        }
    }

    private static String loadedProof(Path path,Map<String,Object> metadata) throws Exception {
        String directory=System.getenv("CREDENTIALS_DIRECTORY");
        String name=path.getFileName().toString();
        require(directory!=null && Path.of(directory).equals(path.getParent())
                && (name.equals("kura_encryption_key") || name.equals("kura_encryption_keyring")));
        ProcessBuilder builder=new ProcessBuilder("/usr/bin/python3","-I","-B",
                "/opt/eclipse/kura/bin/kura_key_store.py","loaded-credential-proof",name);
        builder.environment().clear();builder.environment().put("PATH","/usr/bin:/bin");
        builder.environment().put("LANG","C");builder.environment().put("CREDENTIALS_DIRECTORY",directory);
        Process child=builder.start();
        try {
            require(child.waitFor(5,TimeUnit.SECONDS));
            byte[] output=child.getInputStream().readNBytes(1537);
            require(child.exitValue()==0 && child.getErrorStream().readNBytes(1).length==0 && output.length<=1536);
            String raw=new String(output,java.nio.charset.StandardCharsets.US_ASCII);
            require(raw.endsWith("\n") && raw.indexOf('\n')==raw.length()-1);
            String[] fields=raw.substring(0,raw.length()-1).split(":",-1);
            require(fields.length==12 && fields[0].equals("v1") && fields[1].equals(name) && fields[11].matches("[0-9a-f]{64}"));
            String[] names={"dev","ino","uid","gid","mode","nlink","size","lastModifiedTime","ctime"};
            for(int n=0;n<names.length;n++) {
                Object value=metadata.get(names[n]);
                String expected=value instanceof FileTime time ? Long.toString(time.to(TimeUnit.NANOSECONDS)) : value.toString();
                require(fields[n+2].equals(expected));
            }
            return fields[11];
        } finally {
            if(child.isAlive()){child.destroyForcibly();child.waitFor(5,TimeUnit.SECONDS);}
            child.getInputStream().close();child.getErrorStream().close();child.getOutputStream().close();
        }
    }

    private static void require(boolean valid) {
        if (!valid) {
            throw new IllegalArgumentException("Invalid private recovery key selection");
        }
    }
}
