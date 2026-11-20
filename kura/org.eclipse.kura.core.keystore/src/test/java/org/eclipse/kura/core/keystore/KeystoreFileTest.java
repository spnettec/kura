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

class KeystoreFileTest {
    @TempDir
    Path directory;

    private final char[] password = "fixture-entry".toCharArray();

    private KeyStore populated() throws Exception {
        KeyStore store = KeyStore.getInstance("PKCS12");
        store.load(null, this.password);
        store.setEntry("original", new KeyStore.SecretKeyEntry(KeyGenerator.getInstance("AES").generateKey()),
                new KeyStore.PasswordProtection(this.password));
        return store;
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
