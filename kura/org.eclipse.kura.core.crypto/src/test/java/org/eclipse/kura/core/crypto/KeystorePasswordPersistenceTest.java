/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.crypto;

import static org.junit.jupiter.api.Assertions.*;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;
import java.util.Properties;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.eclipse.kura.KuraException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class KeystorePasswordPersistenceTest {
    @TempDir Path directory;
    private static final byte[] OLD = "rv;ipse329183!@#".getBytes(StandardCharsets.US_ASCII);
    private static final byte[] ACTIVE = new byte[32];
    static { Arrays.fill(ACTIVE, (byte) 0x57); }

    private Path file() { return directory.resolve("store.save"); }

    private CryptoServiceImpl service(boolean ring) throws Exception {
        CryptoServiceImpl service;
        if (ring) {
            ByteArrayOutputStream material = new ByteArrayOutputStream();
            material.writeBytes("YOFC-KURA-KEYRING-v1\n".getBytes(StandardCharsets.US_ASCII));
            material.write(2); material.write(1); material.write(0);
            for (byte[] key : new byte[][] {OLD, ACTIVE}) {
                material.write(key.length); material.writeBytes(key);
            }
            service = CryptoServiceImpl.forKeyRingRecovery(material.toByteArray());
        } else {
            service = CryptoServiceImpl.forSnapshotRecovery(OLD, false);
        }
        var field = CryptoServiceImpl.class.getDeclaredField("keystorePasswordPath");
        field.setAccessible(true); field.set(service, file().toString());
        return service;
    }

    private Properties values() throws IOException {
        Properties result = new Properties();
        try (var input = Files.newInputStream(file())) { result.load(input); }
        return result;
    }

    private void noStagedFiles() throws IOException {
        try (var paths = Files.list(directory)) {
            assertTrue(paths.noneMatch(p -> p.getFileName().toString().startsWith(".store-save-")));
        }
    }

    @Test void actualApiKeepsUntouchedLegacyCiphertextAndReadsAllEntriesAfterReopen() throws Exception {
        CryptoServiceImpl old = service(false);
        old.setKeyStorePassword("/original/cert store.p12", "原有口令".toCharArray());
        old.setKeyStorePassword("sqlite:/original/db", "db-key-and-salt".toCharArray());
        String original = values().getProperty("/original/cert store.p12");
        service(true).setKeyStorePassword("sqlite:/original/db", new char[0]);
        Properties persisted = values();
        assertEquals(2, persisted.size());
        assertEquals(original, persisted.getProperty("/original/cert store.p12"));
        assertTrue(persisted.getProperty("sqlite:/original/db").startsWith("KURA2." + EncryptionKeyRing.id(ACTIVE) + "."));
        CryptoServiceImpl reopened = service(true);
        assertArrayEquals("原有口令".toCharArray(), reopened.getKeyStorePassword("/original/cert store.p12"));
        assertArrayEquals(new char[0], reopened.getKeyStorePassword("sqlite:/original/db"));
        assertEquals(PosixFilePermissions.fromString("rw-------"), Files.getPosixFilePermissions(file()));
        noStagedFiles();
    }

    @Test void concurrentActualApiUpdatesFromTwoInstancesKeepEveryOriginalAndNewEntry() throws Exception {
        CryptoServiceImpl first = service(true), second = service(true);
        first.setKeyStorePassword("original", "retain".toCharArray());
        String original = values().getProperty("original");
        CountDownLatch start = new CountDownLatch(1);
        try (var workers = Executors.newFixedThreadPool(8)) {
            var pending = new java.util.ArrayList<java.util.concurrent.Future<?>>();
            for (int i = 0; i < 32; i++) {
                final int id = i;
                pending.add(workers.submit(() -> {
                    assertTrue(start.await(5, TimeUnit.SECONDS));
                    (id % 2 == 0 ? first : second).setKeyStorePassword("entry-" + id, ("value-" + id).toCharArray());
                    return null;
                }));
            }
            start.countDown();
            for (var task : pending) { task.get(15, TimeUnit.SECONDS); }
        }
        assertEquals(33, values().size());
        assertEquals(original, values().getProperty("original"));
        for (int i = 0; i < 32; i++) {
            assertArrayEquals(("value-" + i).toCharArray(), second.getKeyStorePassword("entry-" + i));
        }
        noStagedFiles();
    }

    @Test void failedAtomicPublicationRetainsOriginalBytesAndCannotFallBackToTruncation() throws Exception {
        for (boolean unsupported : new boolean[] {false, true}) {
            service(false).setKeyStorePassword("original", "retain".toCharArray());
            byte[] before = Files.readAllBytes(file());
            Object identity = Files.getAttribute(file(), "basic:fileKey");
            KeystorePasswordStore failing = new KeystorePasswordStore() {
                @Override void publish(Path staged, Path target) throws IOException {
                    assertEquals(PosixFilePermissions.fromString("rw-------"), Files.getPosixFilePermissions(staged));
                    // A failed write affects only the staged ciphertext file.
                    Files.writeString(staged, "partial staged ciphertext");
                    if (unsupported) { throw new AtomicMoveNotSupportedException(staged.toString(), target.toString(), "fixture"); }
                    throw new IOException("Fixture publication fault");
                }
            };
            assertThrows(IOException.class, () -> failing.put(file(), "new", "encrypted-new-value"));
            assertArrayEquals(before, Files.readAllBytes(file()));
            assertEquals(identity, Files.getAttribute(file(), "basic:fileKey"));
            assertArrayEquals("retain".toCharArray(), service(false).getKeyStorePassword("original"));
            noStagedFiles();
        }
    }

    @Test void malformedOrNonRegularOriginalNeverBecomesAnEmptyReplacement() throws Exception {
        byte[] malformed = "original=\\uNOT0\n".getBytes(StandardCharsets.US_ASCII);
        Files.write(file(), malformed);
        assertThrows(KuraException.class, () -> service(false).setKeyStorePassword("new", "value".toCharArray()));
        assertArrayEquals(malformed, Files.readAllBytes(file()));
        Files.delete(file()); Files.createDirectory(file());
        assertThrows(KuraException.class, () -> service(false).setKeyStorePassword("new", "value".toCharArray()));
        assertTrue(Files.isDirectory(file()));
        noStagedFiles();
    }

    @Test void readDeniedButWritableOriginalCannotBeTruncatedToOnlyTheNewEntry() throws Exception {
        service(false).setKeyStorePassword("original", "retain".toCharArray());
        byte[] before = Files.readAllBytes(file());
        Files.setPosixFilePermissions(file(), PosixFilePermissions.fromString("-w-------"));
        try {
            org.junit.jupiter.api.Assumptions.assumeFalse(Files.isReadable(file()), "Requires an unprivileged test UID");
            assertThrows(KuraException.class, () -> service(false).setKeyStorePassword("new", "value".toCharArray()));
        } finally {
            Files.setPosixFilePermissions(file(), PosixFilePermissions.fromString("rw-------"));
        }
        assertArrayEquals(before, Files.readAllBytes(file()));
        assertArrayEquals("retain".toCharArray(), service(false).getKeyStorePassword("original"));
        noStagedFiles();
    }

    @Test void symlinkAndHardLinkCannotRedirectAnOrdinaryPasswordUpdate() throws Exception {
        Path retained = directory.resolve("retained.save");
        byte[] original = "retained=original-ciphertext\n".getBytes(StandardCharsets.US_ASCII);
        Files.write(retained, original);
        for (boolean symbolic : new boolean[] {true, false}) {
            if (symbolic) { Files.createSymbolicLink(file(), retained); }
            else { Files.createLink(file(), retained); }
            assertThrows(KuraException.class, () -> service(false).setKeyStorePassword("new", "value".toCharArray()));
            assertArrayEquals(original, Files.readAllBytes(retained));
            Files.delete(file());
        }
        noStagedFiles();
    }
}
