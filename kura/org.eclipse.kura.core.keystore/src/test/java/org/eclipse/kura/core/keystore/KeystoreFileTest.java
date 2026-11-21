/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.keystore;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.KeyStore;
import java.util.List;

import javax.crypto.KeyGenerator;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.api.parallel.ResourceLock;
import org.junit.jupiter.api.parallel.Resources;

class KeystoreFileTest {
    @TempDir
    Path directory;

    @Test
    void pendingPasswordKeepsTheOriginalRecordIfSecondNameCannotBePublished() throws Exception {
        String previous = "1".repeat(64);
        String replacement = "2".repeat(64);
        var record = new PendingStorePassword(previous, replacement, PendingStorePassword.scope("fixture"), "ciphertext");
        Path first = this.directory.resolve("password-change-" + previous);
        Path second = this.directory.resolve("password-change-" + replacement);
        Files.createDirectory(second);
        assertThrows(IOException.class, () -> record.publish(this.directory));
        assertEquals(record, PendingStorePassword.read(this.directory, previous));
        assertFalse(Files.exists(this.directory.resolve("password-change.tmp")));
        Files.delete(second);
        record.publish(this.directory);
        assertEquals(record, PendingStorePassword.read(this.directory, replacement));
        assertEquals(1, Files.getAttribute(first, "unix:nlink"));
        assertEquals(1, Files.getAttribute(second, "unix:nlink"));
        assertArrayEquals(Files.readAllBytes(first), Files.readAllBytes(second));
        assertEquals(PosixFilePermissions.fromString("rw-------"), Files.getPosixFilePermissions(second));
        record.retire(this.directory);
        assertFalse(Files.exists(first));
        assertFalse(Files.exists(second));
    }

    private final char[] password = "fixture-entry".toCharArray();

    private KeyStore populated() throws Exception {
        KeyStore store = KeyStore.getInstance("PKCS12");
        store.load(null, this.password);
        store.setEntry("original", new KeyStore.SecretKeyEntry(KeyGenerator.getInstance("AES").generateKey()),
                new KeyStore.PasswordProtection(this.password));
        return store;
    }

    @Test
    void randomPasswordRecoveryRequiresTheSamePidAndPublishedFile() throws Exception {
        Path file = this.directory.resolve("application.p12");
        KeyStore store = populated();
        KeystoreFile.create(file, store, this.password);
        var original = KeystoreFile.existing(file);
        original.write(store, this.password, "encrypted-fixture", "first");
        var published = KeystoreFile.existing(file);
        var pending = published.pendingPassword("first");
        assertEquals("encrypted-fixture", pending.encrypted());
        assertNull(published.pendingPassword("second"));
        assertThrows(IOException.class, () -> published.write(store, this.password, "other-ciphertext", "second"));
        assertEquals(pending, published.pendingPassword("first"));
        assertEquals(pending, published.pendingPassword("first"));

        Path retained = Files.move(file, this.directory.resolve("retained.p12"));
        Files.copy(retained, file);
        assertNull(KeystoreFile.existing(file).pendingPassword("first"));
        Files.move(retained, file, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        assertEquals(pending, KeystoreFile.existing(file).pendingPassword("first"));
        published.retirePassword(pending);
        assertNull(KeystoreFile.existing(file).pendingPassword("first"));
    }

    private KeyStore interrupted() throws Exception {
        KeyStore store = mock(KeyStore.class);
        doAnswer(call -> {
            OutputStream stream = call.getArgument(0);
            stream.write(new byte[128]);
            throw new IOException("interrupted while streaming");
        }).when(store).store(any(OutputStream.class), any(char[].class));
        return store;
    }

    @Test
    @ResourceLock(Resources.SYSTEM_PROPERTIES)
    void writerOwnershipUsesTheOperatingSystemIdentity() throws Exception {
        String previous = System.setProperty("user.name", "kura-nonexistent-keystore-test-account");
        try {
            Path file = this.directory.resolve("application.p12");
            KeystoreFile.create(file, populated(), this.password);
            assertTrue(KeystoreFile.existing(file).load(this.password).isKeyEntry("original"));
        } finally {
            if (previous == null) {
                System.clearProperty("user.name");
            } else {
                System.setProperty("user.name", previous);
            }
        }
    }

    @Test
    void failedSerializationLeavesTheOriginalEntryAndFileIntact() throws Exception {
        Path file = this.directory.resolve("private.p12");
        KeyStore source = populated();
        KeystoreFile.create(file, source, this.password);
        byte[] before = Files.readAllBytes(file);
        var attributes = Files.readAttributes(file, "unix:dev,ino,mode,uid,gid,size,ctime");
        KeystoreFile loaded = KeystoreFile.existing(file);

        assertThrows(IOException.class, () -> loaded.write(interrupted(), this.password));
        assertArrayEquals(before, Files.readAllBytes(file));
        assertEquals(attributes, Files.readAttributes(file, "unix:dev,ino,mode,uid,gid,size,ctime"));
        assertEquals(source.getKey("original", this.password), KeyStore.getInstance(file.toFile(), this.password)
                .getKey("original", this.password));
        try (var files = Files.walk(this.directory)) {
            assertEquals(List.of("lock", "private.p12"), files.filter(Files::isRegularFile)
                    .map(path -> path.getFileName().toString()).sorted().toList());
        }
    }

    @Test
    void initialPublicationRequiresACompleteStoreAndAnAbsentDestination() throws Exception {
        Path file = this.directory.resolve("new.p12");
        assertThrows(IOException.class, () -> KeystoreFile.create(file, interrupted(), this.password));
        assertFalse(Files.exists(file));

        KeystoreFile.create(file, populated(), this.password);
        byte[] original = Files.readAllBytes(file);
        assertThrows(FileAlreadyExistsException.class, () -> KeystoreFile.create(file, populated(), this.password));
        assertArrayEquals(original, Files.readAllBytes(file));
    }

    @Test
    void aWriteThroughAnAliasRetainsPermissionsAndRejectsAnOlderWriter() throws Exception {
        Path file = this.directory.resolve("store");
        KeystoreFile.create(file, populated(), this.password);
        Files.setPosixFilePermissions(file, PosixFilePermissions.fromString("rw-r-----"));
        Path alias = Files.createSymbolicLink(this.directory.resolve("alias"), file.getFileName());
        var access = Files.readAttributes(file, "unix:mode,uid,gid");
        KeystoreFile stale = KeystoreFile.existing(file);

        KeystoreFile.existing(alias).write(populated(), this.password);
        byte[] committed = Files.readAllBytes(file);
        assertTrue(Files.isSymbolicLink(alias));
        assertEquals(access, Files.readAttributes(file, "unix:mode,uid,gid"));
        assertThrows(IOException.class, () -> stale.write(populated(), this.password));
        assertArrayEquals(committed, Files.readAllBytes(file));
    }

    @Test
    void resumesAfterPublicationOfTheInitialLinkOrAnInterruptedReplacement() throws Exception {
        Path file = this.directory.resolve("business");
        KeyStore original = populated();
        KeystoreFile.create(file, original, this.password);
        Path staging;
        try (var paths = Files.list(this.directory)) {
            staging = paths.filter(Files::isDirectory).findFirst().orElseThrow().resolve("store");
        }
        Files.createLink(staging, file);
        KeystoreFile.existing(file).write(original, this.password);
        assertFalse(Files.exists(staging));
        assertEquals(1, Files.getAttribute(file, "unix:nlink"));
        Files.write(staging, new byte[32]);
        KeystoreFile.existing(file).write(original, this.password);
        assertFalse(Files.exists(staging));
        assertEquals(original.getKey("original", this.password),
                KeyStore.getInstance(file.toFile(), this.password).getKey("original", this.password));
    }

    @Test
    void aRetargetedAliasOrSecondHardLinkCannotSplitTheOriginalStore() throws Exception {
        Path first = this.directory.resolve("first");
        Path second = this.directory.resolve("second");
        KeystoreFile.create(first, populated(), this.password);
        KeystoreFile.create(second, populated(), this.password);
        byte[] a = Files.readAllBytes(first);
        byte[] b = Files.readAllBytes(second);
        Path alias = Files.createSymbolicLink(this.directory.resolve("alias"), first.getFileName());
        KeystoreFile previous = KeystoreFile.existing(alias);
        Files.delete(alias);
        Files.createSymbolicLink(alias, second.getFileName());
        assertThrows(IOException.class, () -> previous.write(populated(), this.password));

        Path hardLink = Files.createLink(this.directory.resolve("hard-link"), first);
        assertThrows(IOException.class, () -> KeystoreFile.existing(first).write(populated(), this.password));
        assertTrue(Files.isSameFile(hardLink, first));
        assertArrayEquals(a, Files.readAllBytes(first));
        assertArrayEquals(b, Files.readAllBytes(second));
    }
}
