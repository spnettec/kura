/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.keystore;

import static java.nio.file.LinkOption.NOFOLLOW_LINKS;
import static java.nio.file.StandardCopyOption.ATOMIC_MOVE;
import static java.nio.file.StandardCopyOption.REPLACE_EXISTING;
import static java.nio.file.StandardOpenOption.READ;
import static java.nio.file.StandardOpenOption.WRITE;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/** Encrypted recovery material for the two file images of a random password change. */
record PendingStorePassword(String previous, String replacement, String scope, String encrypted) {
    private static final String NAME = "password-change";

    static String fingerprint(Path file, Path configured, Path target) throws IOException, NoSuchAlgorithmException {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        var key = Files.readAttributes(file, BasicFileAttributes.class, NOFOLLOW_LINKS).fileKey();
        if (key == null) {
            throw new IOException("Unable to identify keystore file");
        }
        for (String value : new String[] { configured.toAbsolutePath().toString(), target.toString(), key.toString() }) {
            byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
            digest.update(ByteBuffer.allocate(Integer.BYTES).putInt(bytes.length).array());
            digest.update(bytes);
        }
        try (var input = new DigestInputStream(Files.newInputStream(file, NOFOLLOW_LINKS), digest)) {
            input.transferTo(OutputStream.nullOutputStream());
        }
        return HexFormat.of().formatHex(digest.digest());
    }

    static String scope(String pid) throws NoSuchAlgorithmException {
        byte[] value = (pid == null ? "0" : "1" + pid).getBytes(StandardCharsets.UTF_8);
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value));
    }

    static PendingStorePassword read(Path dir, String fingerprint) throws IOException {
        Path record = dir.resolve(NAME + "-" + fingerprint);
        if (Files.exists(record, NOFOLLOW_LINKS) && !Files.isRegularFile(record, NOFOLLOW_LINKS)) {
            throw new IOException("Invalid keystore password change record");
        }
        try (var input = Files.newInputStream(record, NOFOLLOW_LINKS)) {
            byte[] bytes = input.readNBytes(4097);
            String[] fields = new String(bytes, StandardCharsets.UTF_8).split("\n", 4);
            if (bytes.length > 4096 || fields.length != 4 || !fields[0].matches("[0-9a-f]{64}")
                    || !fields[1].matches("[0-9a-f]{64}") || !fields[2].matches("[0-9a-f]{64}") || fields[3].isEmpty()
                    || !(fingerprint.equals(fields[0]) || fingerprint.equals(fields[1]))) {
                throw new IOException("Invalid keystore password change record");
            }
            return new PendingStorePassword(fields[0], fields[1], fields[2], fields[3]);
        } catch (NoSuchFileException absent) {
            return null;
        }
    }

    void publish(Path dir) throws IOException {
        byte[] bytes = (this.previous + "\n" + this.replacement + "\n" + this.scope + "\n" + this.encrypted).getBytes(StandardCharsets.UTF_8);
        if (bytes.length > 4096 || this.encrypted.isEmpty()) {
            throw new IOException("Invalid encrypted password change");
        }
        Path tmp = dir.resolve(NAME + ".tmp");
        Files.deleteIfExists(tmp);
        try (var directory = FileChannel.open(dir, READ)) {
            // Both names must survive before replacing the store. Use independent inodes so the
            // container can validate private state before restarting the provider after an interruption.
            for (String fingerprint : new String[] { this.previous, this.replacement }) {
                publishName(tmp, dir.resolve(NAME + "-" + fingerprint), bytes);
            }
            directory.force(true);
        } finally {
            Files.deleteIfExists(tmp);
        }
    }

    private static void publishName(Path tmp, Path name, byte[] bytes) throws IOException {
        Files.createFile(tmp, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        try (var output = FileChannel.open(tmp, WRITE, NOFOLLOW_LINKS)) {
            var buffer = ByteBuffer.wrap(bytes);
            while (buffer.hasRemaining()) {
                output.write(buffer);
            }
            output.force(true);
        }
        Files.move(tmp, name, ATOMIC_MOVE, REPLACE_EXISTING);
    }

    void separateLinks(Path dir, String expectedDigest) throws IOException, NoSuchAlgorithmException {
        Path previousName = dir.resolve(NAME + "-" + this.previous);
        Path replacementName = dir.resolve(NAME + "-" + this.replacement);
        var owner = Files.getOwner(dir, NOFOLLOW_LINKS);
        var permissions = PosixFilePermissions.fromString("rw-------");
        boolean linked = Files.isSameFile(previousName, replacementName);
        for (Path path : new Path[] { previousName, replacementName }) {
            if (!Files.isRegularFile(path, NOFOLLOW_LINKS) || !Files.getOwner(path, NOFOLLOW_LINKS).equals(owner)
                    || !Files.getPosixFilePermissions(path, NOFOLLOW_LINKS).equals(permissions)
                    || !Integer.valueOf(linked ? 2 : 1).equals(Files.getAttribute(path, "unix:nlink", NOFOLLOW_LINKS))) {
                throw new IOException("Unexpected password change record identity");
            }
        }
        byte[] bytes;
        try (var input = Files.newInputStream(previousName, NOFOLLOW_LINKS)) {
            bytes = input.readNBytes(4097);
        }
        if (bytes.length > 4096 || !HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes))
                .equals(expectedDigest) || Files.mismatch(previousName, replacementName) != -1) {
            throw new IOException("Password change records differ from maintenance input");
        }
        try (var directory = FileChannel.open(dir, READ)) {
            if (linked) {
                // Only reclaim a partial copy of these same bytes from an interrupted repair.
                Path tmp = dir.resolve(".separate-record.tmp");
                if (Files.exists(tmp, NOFOLLOW_LINKS)) {
                    if (!Files.isRegularFile(tmp, NOFOLLOW_LINKS) || !Files.getOwner(tmp, NOFOLLOW_LINKS).equals(owner)
                            || !Files.getPosixFilePermissions(tmp, NOFOLLOW_LINKS).equals(permissions)
                            || !Integer.valueOf(1).equals(Files.getAttribute(tmp, "unix:nlink", NOFOLLOW_LINKS))) {
                        throw new IOException("Unexpected maintenance staging file");
                    }
                    try (var input = Files.newInputStream(tmp, NOFOLLOW_LINKS)) {
                        byte[] partial = input.readNBytes(bytes.length + 1);
                        if (partial.length > bytes.length || !java.util.Arrays.equals(bytes, 0, partial.length,
                                partial, 0, partial.length)) {
                            throw new IOException("Unpaired maintenance staging data");
                        }
                    }
                    Files.delete(tmp);
                }
                try {
                    publishName(tmp, replacementName, bytes);
                } finally {
                    Files.deleteIfExists(tmp);
                }
            }
            directory.force(true);
        }
    }

    void removeName(Path dir, String fingerprint) throws IOException {
        if (equals(read(dir, fingerprint))) {
            Files.delete(dir.resolve(NAME + "-" + fingerprint));
        }
    }

    void retire(Path dir) throws IOException {
        removeName(dir, this.previous);
        removeName(dir, this.replacement);
        try (var directory = FileChannel.open(dir, READ)) {
            directory.force(true);
        }
    }
}
