/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.keystore;

import static java.nio.file.LinkOption.NOFOLLOW_LINKS;
import static java.nio.file.StandardCopyOption.ATOMIC_MOVE;
import static java.nio.file.StandardCopyOption.COPY_ATTRIBUTES;
import static java.nio.file.StandardCopyOption.REPLACE_EXISTING;
import static java.nio.file.StandardOpenOption.CREATE;
import static java.nio.file.StandardOpenOption.READ;
import static java.nio.file.StandardOpenOption.TRUNCATE_EXISTING;
import static java.nio.file.StandardOpenOption.WRITE;

import java.io.IOException;
import java.nio.channels.Channels;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.KeyStore;
import java.security.KeyStoreException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.cert.CertificateException;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.Map;
import java.util.Set;

/** Captures the identity of a loaded store so a stale writer cannot replace a newer publication. */
final class KeystoreFile {
    private final Path path;
    private final Path target;
    private final Map<String, Object> original;

    private KeystoreFile(Path path, Path target, Map<String, Object> original) {
        this.path = path;
        this.target = target;
        this.original = original;
    }

    static KeystoreFile existing(Path path) throws IOException {
        Path target = path.toRealPath();
        return new KeystoreFile(path, target, attributes(target));
    }

    static void create(Path path, KeyStore store, char[] password)
            throws IOException, KeyStoreException, NoSuchAlgorithmException, CertificateException {
        Path destination = path.toAbsolutePath();
        Files.createDirectories(destination.getParent());
        Path target = destination.getParent().toRealPath().resolve(destination.getFileName());
        new KeystoreFile(path, target, null).write(store, password);
    }

    private static Map<String, Object> attributes(Path target) throws IOException {
        if (target.getFileSystem().supportedFileAttributeViews().contains("unix")) {
            return Files.readAttributes(target, "unix:dev,ino,mode,nlink,size,ctime,lastModifiedTime,uid,gid", NOFOLLOW_LINKS);
        }
        return Files.readAttributes(target, "basic:fileKey,size,lastModifiedTime,creationTime", NOFOLLOW_LINKS);
    }

    KeyStore load(char[] password) throws IOException, KeyStoreException, NoSuchAlgorithmException, CertificateException {
        KeyStore store = KeyStore.getInstance(this.target.toFile(), password);
        checkOriginal();
        return store;
    }

    private void checkOriginal() throws IOException {
        if (!this.target.equals(this.path.toRealPath()) || !this.original.equals(attributes(this.target))) {
            throw new IOException("Keystore changed since it was loaded");
        }
    }

    private static String currentUser() throws IOException {
        var user = ProcessHandle.current().info().user();
        if (user.isPresent()) {
            return user.get();
        }
        // Linux containers may run with no passwd entry. Column four is the filesystem UID.
        for (String line : Files.readAllLines(Path.of("/proc/thread-self/status"), StandardCharsets.US_ASCII)) {
            if (line.startsWith("Uid:")) {
                String[] ids = line.substring(4).trim().split("\\s+");
                if (ids.length == 4 && ids[3].matches("[0-9]+")) {
                    return ids[3];
                }
            }
        }
        throw new IOException("Unable to determine keystore writer identity");
    }

    private Path workspace(boolean create) throws IOException, NoSuchAlgorithmException {
        String user = currentUser();
        byte[] name = (user + "\0" + this.target.getFileName()).getBytes(StandardCharsets.UTF_8);
        String id = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(name));
        Path dir = this.target.resolveSibling(".kura-keystore-" + id);
        var permissions = PosixFilePermissions.fromString("rwx------");
        if (!create && Files.notExists(dir, NOFOLLOW_LINKS)) {
            return null;
        }
        if (create) {
            try {
                Files.createDirectory(dir, PosixFilePermissions.asFileAttribute(permissions));
            } catch (FileAlreadyExistsException alreadyPresent) {
                // A completed or interrupted write may already have created the private workspace.
            }
        }
        var owner = dir.getFileSystem().getUserPrincipalLookupService().lookupPrincipalByName(user);
        if (!Files.isDirectory(dir, NOFOLLOW_LINKS) || !Files.getOwner(dir, NOFOLLOW_LINKS).equals(owner)
                || !Files.getPosixFilePermissions(dir, NOFOLLOW_LINKS).equals(permissions)) {
            throw new IOException("Invalid keystore staging directory");
        }
        return dir;
    }

    private KeystoreFile prepare(Path staged) throws IOException {
        if (this.original != null) {
            checkOriginal();
        }
        if (Files.exists(staged, NOFOLLOW_LINKS)) {
            if (!Files.isRegularFile(staged, NOFOLLOW_LINKS)) {
                throw new IOException("Invalid staged keystore");
            }
            // Creation publishes a hard link without overwriting a competing destination. A stop immediately
            // after publication can leave that one temporary link. Only detach our own confirmed staging name.
            if (this.original != null && Files.isSameFile(staged, this.target)) {
                if (!Integer.valueOf(2).equals(this.original.get("nlink"))) {
                    throw new IOException("Unexpected keystore links");
                }
                Files.delete(staged);
                KeystoreFile recovered = existing(this.path);
                Map<String, Object> expected = new HashMap<>(this.original);
                expected.remove("ctime");
                expected.put("nlink", 1);
                if (!this.target.equals(recovered.target) || !recovered.original.entrySet().containsAll(expected.entrySet())) {
                    throw new IOException("Keystore changed during staging recovery");
                }
                return recovered;
            }
            Files.delete(staged);
        }
        return this;
    }

    private void replace(Path staged) throws IOException {
        // Check write access to the original and respect an existing file lock.
        try (FileChannel current = FileChannel.open(this.target, WRITE, NOFOLLOW_LINKS);
                FileLock lock = current.tryLock()) {
            if (lock == null) {
                throw new IOException("Keystore is busy");
            }
            checkOriginal();
            Files.move(staged, this.target, ATOMIC_MOVE, REPLACE_EXISTING);
        }
    }

    private void writeStaged(Path staged, KeyStore store, char[] password, String encrypted, String pid)
            throws IOException, KeyStoreException, NoSuchAlgorithmException, CertificateException {
        if (this.original == null) {
            Files.createFile(staged, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        } else {
            if (!Files.isRegularFile(this.target, NOFOLLOW_LINKS) || !Integer.valueOf(1).equals(this.original.get("nlink"))) {
                throw new IOException("Atomic keystore replacement requires a single-link regular file");
            }
            Files.copy(this.target, staged, COPY_ATTRIBUTES, NOFOLLOW_LINKS);
            Map<String, Object> copied = Files.readAttributes(staged, "unix:mode,uid,gid", NOFOLLOW_LINKS);
            if (!this.original.entrySet().containsAll(copied.entrySet())) {
                throw new IOException("Cannot preserve keystore ownership or permissions");
            }
        }
        try (FileChannel output = FileChannel.open(staged, WRITE, TRUNCATE_EXISTING, NOFOLLOW_LINKS)) {
            store.store(Channels.newOutputStream(output), password);
            output.force(true);
        }
        if (this.original == null) {
            Files.createLink(this.target, staged);
        } else {
            if (encrypted != null) {
                String previous = PendingStorePassword.fingerprint(this.target, this.path, this.target);
                var existing = PendingStorePassword.read(staged.getParent(), previous);
                String scope = PendingStorePassword.scope(pid);
                if (existing != null) {
                    if (!existing.previous().equals(previous) || !existing.scope().equals(scope)
                            || !existing.encrypted().equals(encrypted)) {
                        throw new IOException("Unresolved keystore password change");
                    }
                    existing.removeName(staged.getParent(), existing.replacement());
                }
                new PendingStorePassword(previous, PendingStorePassword.fingerprint(staged, this.path, this.target),
                        scope, encrypted).publish(staged.getParent());
            }
            replace(staged);
        }
    }

    void write(KeyStore store, char[] password)
            throws IOException, KeyStoreException, NoSuchAlgorithmException, CertificateException {
        write(store, password, null, null);
    }

    PendingStorePassword pendingPassword(String pid) throws IOException, NoSuchAlgorithmException {
        Path dir = workspace(false);
        if (dir != null) {
            try (var records = Files.newDirectoryStream(dir, "password-change-*")) {
                if (!records.iterator().hasNext()) {
                    return null;
                }
            }
            String current = PendingStorePassword.fingerprint(this.target, this.path, this.target);
            var pending = PendingStorePassword.read(dir, current);
            checkOriginal();
            if (pending != null && pending.scope().equals(PendingStorePassword.scope(pid))) {
                return pending;
            }
        }
        return null;
    }

    void retirePassword(PendingStorePassword pending) throws IOException, NoSuchAlgorithmException {
        Path dir = workspace(false);
        if (dir != null) {
            try (var guard = FileChannel.open(dir.resolve("lock"), WRITE, NOFOLLOW_LINKS);
                    var lock = guard.tryLock()) {
                if (lock == null) {
                    throw new IOException("Keystore is busy");
                }
                pending.retire(dir);
            } catch (OverlappingFileLockException e) {
                throw new IOException("Keystore is busy", e);
            }
        }
    }

    void write(KeyStore store, char[] password, String encrypted, String pid)
            throws IOException, KeyStoreException, NoSuchAlgorithmException, CertificateException {
        Path dir = workspace(true);
        Path staged = dir.resolve("store");
        try (FileChannel directory = FileChannel.open(this.target.getParent(), READ);
                FileChannel guard = FileChannel.open(dir.resolve("lock"), Set.of(CREATE, WRITE, NOFOLLOW_LINKS),
                        PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
                FileLock lock = guard.tryLock()) {
            if (lock == null) {
                throw new IOException("Keystore is busy");
            }
            directory.force(true);
            KeystoreFile current = prepare(staged);
            try {
                current.writeStaged(staged, store, password, encrypted, pid);
                directory.force(true);
            } finally {
                Files.deleteIfExists(staged);
            }
        } catch (OverlappingFileLockException e) {
            throw new IOException("Keystore is busy", e);
        }
    }
}
