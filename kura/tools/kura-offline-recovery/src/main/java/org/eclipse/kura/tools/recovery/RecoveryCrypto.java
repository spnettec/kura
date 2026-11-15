/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import java.io.InputStream;
import java.nio.channels.Channels;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermission;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.Map;

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
        byte[] active = readPrivate(activePath, 32);
        byte[] ring = null;
        try {
            require(HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(active)).equals(keySha256));
            if (ringSha256.equals("none")) {
                require(Files.notExists(ringPath, LinkOption.NOFOLLOW_LINKS));
                return CryptoServiceImpl.forSnapshotRecovery(active, false);
            }
            ring = readPrivate(ringPath, 512);
            require(HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(ring)).equals(ringSha256));
            return CryptoServiceImpl.forKeyRingRecovery(ring, active);
        } finally {
            Arrays.fill(active, (byte) 0);
            if (ring != null) { Arrays.fill(ring, (byte) 0); }
        }
    }

    private static byte[] readPrivate(Path path, int limit) throws Exception {
        require(path.isAbsolute() && Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS));
        require(Files.isDirectory(path.getParent(), LinkOption.NOFOLLOW_LINKS));
        var parent = Files.getPosixFilePermissions(path.getParent(), LinkOption.NOFOLLOW_LINKS);
        require(!parent.contains(PosixFilePermission.GROUP_WRITE) && !parent.contains(PosixFilePermission.OTHERS_WRITE));
        var permissions = Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS);
        require(permissions.stream().noneMatch(p -> p.name().startsWith("GROUP") || p.name().startsWith("OTHERS")));
        Map<String, Object> before = Files.readAttributes(path,
                "unix:dev,ino,size,uid,gid,mode,nlink,lastModifiedTime,ctime", LinkOption.NOFOLLOW_LINKS);
        require(Integer.valueOf(1).equals(before.get("nlink")));
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
            }
            accepted = true;
            return value;
        } finally {
            if (!accepted && value != null) {
                Arrays.fill(value, (byte) 0);
            }
        }
    }

    private static void require(boolean valid) {
        if (!valid) {
            throw new IllegalArgumentException("Invalid private recovery key selection");
        }
    }
}
