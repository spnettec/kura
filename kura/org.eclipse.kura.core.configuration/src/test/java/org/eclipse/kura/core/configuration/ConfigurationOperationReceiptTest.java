/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import static org.eclipse.kura.core.configuration.ConfigurationPlanAdmissionTest.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import org.eclipse.kura.configuration.ConfigurationOperationReceiptService.State;
import org.eclipse.kura.configuration.ConfigurationRevisionService.*;
import org.eclipse.kura.system.SystemService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.*;
import java.util.concurrent.*;

class ConfigurationOperationReceiptTest {
    @TempDir Path data;

    @org.junit.jupiter.api.BeforeEach
    void retainedEvidenceDirectory(org.junit.jupiter.api.TestInfo test) throws Exception {
        String output = System.getProperty("kura.receipt.evidence");
        if (output != null) {
            Path parent = Path.of(output);
            if (!parent.isAbsolute()) throw new IllegalArgumentException("absolute evidence path required");
            Files.createDirectories(parent);
            // The JUnit-managed temporary directory is separate; this explicitly selected scene is retained.
            data = Files.createTempDirectory(parent, test.getTestMethod().orElseThrow().getName() + "-");
        }
    }

    Path root() {
        return data.resolve("configuration-dispatch-journal-v1");
    }

    String id() {
        return "op-" + UUID.randomUUID();
    }

    Path file(String id, String extension) {
        return root().resolve(id.substring(3) + extension);
    }

    Path clientFile(String id, String extension) {
        return root().resolve("client-operations").resolve(id.substring(3) + extension);
    }

    RecordedConfigurationPlan plan() throws Exception {
        return new RecordedConfigurationPlan(
                List.of(), List.of(creation(NEW)), Set.of(), Map.of(), null);
    }

    ConfigurationOperationReceiptServiceImpl reader() {
        var system = mock(SystemService.class);
        when(system.getKuraDataDirectory()).thenReturn(data.toString());
        var result = new ConfigurationOperationReceiptServiceImpl();
        result.setSystemService(system);
        return result;
    }

    @Test
    void committedPlanHasValueFreeDurableReceiptAndCannotReplayAfterRestart() throws Exception {
        String id = id();
        var reader = reader();
        var service = new Fixture();
        service.initializeIntentJournal(data);
        try {
            service.applyConfigurationPlanIfUnchanged(
                    id,
                    List.of(update(SECOND, "never-store-secret-xy")),
                    List.of(
                            new Creation(
                                    FACTORY, NEW, Map.of("password", "never-store-secret-ab"))),
                    Set.of(FIRST),
                    service.baseline());
            var receipt = reader.getOperationReceipt(id);
            assertEquals(State.CORE_COMMITTED, receipt.state());
            assertEquals(Map.of(NEW, FACTORY), receipt.createdFactories());
            assertEquals(Set.of(SECOND), receipt.updatedPids());
            assertEquals(Set.of(FIRST), receipt.deletedPids());
            assertFalse(receipt.businessHealthVerified());
            try (var paths = Files.walk(root())) {
                for (Path path : paths.filter(Files::isRegularFile).toList()) {
                    String bytes =
                            new String(
                                    Files.readAllBytes(path),
                                    java.nio.charset.StandardCharsets.ISO_8859_1);
                    assertFalse(bytes.contains("never-store-secret"));
                }
            }
            assertEquals(
                    Reason.CONFLICT,
                    assertThrows(
                                    Rejected.class,
                                    () ->
                                            service.applyConfigurationPlanIfUnchanged(
                                                    id,
                                                    List.of(),
                                                    List.of(creation("other.pid")),
                                                    Set.of(),
                                                    Map.of()))
                            .getReason());
            assertEquals(3, service.dispatched.size());
            assertEquals(1, service.snapshots);
        } finally {
            service.deactivate();
        }
        try (var journal = ConfigurationIntentJournal.open(root())) {
            journal.requireStartup();
        }
        var restarted = new Fixture();
        restarted.initializeIntentJournal(data);
        try {
            assertEquals(State.CORE_COMMITTED, reader.getOperationReceipt(id).state());
            assertThrows(
                    Rejected.class,
                    () ->
                            restarted.applyConfigurationPlanIfUnchanged(
                                    id, List.of(), List.of(creation(NEW)), Set.of(), Map.of()));
            assertTrue(restarted.dispatched.isEmpty());
        } finally {
            restarted.deactivate();
        }
    }

    @Test
    void stalePreflightIsRejectedWithoutIntentAndCannotReuseId() throws Exception {
        String id = id();
        var service = new Fixture();
        service.initializeIntentJournal(data);
        try {
            var guard = service.baseline();
            service.values.get(FIRST).put("name", "concurrent");
            assertThrows(
                    Rejected.class,
                    () ->
                            service.applyConfigurationPlanIfUnchanged(
                                    id, List.of(), List.of(), Set.of(FIRST), guard));
            var receipt = reader().getOperationReceipt(id);
            assertEquals(State.REJECTED, receipt.state());
            assertEquals("CONFLICT", receipt.rejection());
            assertFalse(Files.exists(file(id, ".intent")));
            assertTrue(service.dispatched.isEmpty());
            assertThrows(
                    Rejected.class,
                    () ->
                            service.applyConfigurationPlanIfUnchanged(
                                    id, List.of(), List.of(), Set.of(FIRST), service.baseline()));
            assertTrue(service.dispatched.isEmpty());
        } finally {
            service.deactivate();
        }
    }

    @Test
    void failedSnapshotIsUnknownAndIndependentReaderSurvivesBlockedStartup() throws Exception {
        String id = id();
        var service = new Fixture();
        service.initializeIntentJournal(data);
        service.failSnapshot = true;
        try {
            assertThrows(
                    Exception.class,
                    () ->
                            service.applyConfigurationPlanIfUnchanged(
                                    id, List.of(), List.of(creation(NEW)), Set.of(), Map.of()));
            assertEquals(State.UNKNOWN, reader().getOperationReceipt(id).state());
            assertThrows(Exception.class, service::baseline);
        } finally {
            service.deactivate();
        }
        try (var journal = ConfigurationIntentJournal.open(root())) {
            assertThrows(Exception.class, journal::requireStartup);
        }
        assertEquals(State.UNKNOWN, reader().getOperationReceipt(id).state());
        assertThrows(Rejected.class, () -> reader().cancelUnreservedOperation(id));
        assertThrows(Rejected.class, () -> reader().cancelUnreservedOperation(id));
        assertFalse(Files.exists(file(id, ".complete")));
    }

    @Test
    void unreservedCancellationPreventsLateWriteAndReservationRaceHasOneWinner() throws Exception {
        String id = id();
        var reader = reader();
        assertEquals(State.NOT_FOUND, reader.getOperationReceipt(id).state());
        assertEquals(State.CANCELLED, reader.cancelUnreservedOperation(id).state());
        var service = new Fixture();
        service.initializeIntentJournal(data);
        try {
            assertThrows(
                    Rejected.class,
                    () ->
                            service.applyConfigurationPlanIfUnchanged(
                                    id, List.of(), List.of(creation(NEW)), Set.of(), Map.of()));
            assertTrue(service.dispatched.isEmpty());
        } finally {
            service.deactivate();
        }
        String race = id();
        var plan = plan();
        var start = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(2);
        try {
            var futures = new ArrayList<Future<Boolean>>();
            for (boolean cancel : List.of(false, true))
                futures.add(
                        pool.submit(
                                () -> {
                                    start.await();
                                    try {
                                        ConfigurationOperationStore.reserve(
                                                root(), race, cancel ? null : plan);
                                        return true;
                                    } catch (Rejected duplicate) {
                                        assertEquals(Reason.CONFLICT, duplicate.getReason());
                                        return false;
                                    }
                                }));
            start.countDown();
            assertEquals(
                    1,
                    (futures.get(0).get(5, TimeUnit.SECONDS) ? 1 : 0)
                            + (futures.get(1).get(5, TimeUnit.SECONDS) ? 1 : 0));
            assertTrue(
                    Set.of(State.RESERVED, State.CANCELLED)
                            .contains(reader.getOperationReceipt(race).state()));
        } finally {
            pool.shutdownNow();
        }
    }

    @Test
    void queryDoesNotWaitForWriterOrRequireConfigurationService() throws Exception {
        String id = id();
        var reader = reader();
        try (var journal = ConfigurationIntentJournal.open(root())) {
            try (var operation = journal.clientOperation(id, plan())) {
                assertEquals(State.RESERVED, reader.getOperationReceipt(id).state());
                journal.requireOrdinaryWrite();
                try (var ticket = journal.begin("plan", Set.of(NEW))) {
                    var pool = Executors.newSingleThreadExecutor();
                    try {
                        assertEquals(
                                State.UNKNOWN,
                                pool.submit(() -> reader.getOperationReceipt(id).state())
                                        .get(2, TimeUnit.SECONDS));
                    } finally {
                        pool.shutdownNow();
                    }
                    ticket.complete();
                    assertEquals(State.CORE_COMMITTED, reader.getOperationReceipt(id).state());
                }
            }
        }
    }

    @Test
    void partialOrUntrustedRecordsAreUnknownAndNeverNotFound() throws Exception {
        String id = id();
        ConfigurationOperationStore.reserve(root(), id, plan());
        Files.write(clientFile(id, ".request"), new byte[] {1, 2, 3});
        assertEquals(State.UNKNOWN, reader().getOperationReceipt(id).state());
        String other = id();
        ConfigurationOperationStore.reserve(root(), other, plan());
        Files.setPosixFilePermissions(
                clientFile(other, ".request"), PosixFilePermissions.fromString("rw-r--r--"));
        assertEquals(State.UNKNOWN, reader().getOperationReceipt(other).state());
        String linked = id();
        Files.createSymbolicLink(clientFile(linked, ".request"), clientFile(other, ".request"));
        assertEquals(State.UNKNOWN, reader().getOperationReceipt(linked).state());
        assertThrows(Rejected.class, () -> reader().getOperationReceipt("op-../../secrets"));
    }

    @Test
    void cancelledOrReservedRequestCannotHideAnOrphanDecisionOrRelease() throws Exception {
        String cancelled=id();reader().cancelUnreservedOperation(cancelled);
        Files.write(file(cancelled,".complete"),new byte[0],StandardOpenOption.CREATE_NEW);
        assertEquals(State.UNKNOWN,reader().getOperationReceipt(cancelled).state());
        String reserved=id();ConfigurationOperationStore.reserve(root(),reserved,plan());
        Files.write(file(reserved,"."+UUID.randomUUID()+".release"),new byte[0],StandardOpenOption.CREATE_NEW);
        assertEquals(State.UNKNOWN,reader().getOperationReceipt(reserved).state());
    }

    @Test
    void validRecoveryCannotMaskADamagedOriginalCompletion() throws Exception {
        String id=id();Path publication=data.resolve("release-with-damaged-completion");byte[] bytes={1,2,3};
        String digest=HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(bytes));
        try(var journal=ConfigurationIntentJournal.open(root())) {
            try(var operation=journal.clientOperation(id,plan())) {
                journal.requireOrdinaryWrite();try(var ticket=journal.begin("plan",Set.of(NEW))) { }
            }
            var evidence=new ControlledRecovery.CompletionEvidence("owned-recovery","b".repeat(64),"complete-"+UUID.randomUUID(),"c".repeat(64));
            journal.prepareRelease(evidence,publication,digest);Files.write(publication,bytes,StandardOpenOption.CREATE_NEW);
            assertEquals(State.RECOVERED,reader().getOperationReceipt(id).state());
            Files.write(file(id,".complete"),new byte[]{0},StandardOpenOption.CREATE_NEW);
            assertEquals(State.UNKNOWN,reader().getOperationReceipt(id).state());
        }
        assertThrows(Exception.class,()->ConfigurationIntentJournal.open(root()));
    }

    @Test
    void legacyProviderDoesNotSilentlyDowngradeIdentifiedPlan() throws Exception {
        var provider = mock(org.eclipse.kura.configuration.ConfigurationRevisionService.class, CALLS_REAL_METHODS);
        assertEquals(Reason.UNSUPPORTED, assertThrows(Rejected.class, () -> provider.applyConfigurationPlanIfUnchanged(
                id(), List.of(), List.of(creation(NEW)), Set.of(), Map.of())).getReason());
        assertEquals(Reason.UNSUPPORTED, assertThrows(Rejected.class, () -> provider.applyConfigurationPlanIfUnchanged(
                id(), List.of(), List.of(creation(NEW)), Set.of(), Map.of(), new DeletionGuard(Map.of(), Set.of()))).getReason());
        verify(provider, never()).applyConfigurationPlanIfUnchanged(anyList(), anyList(), anySet(), anyMap());
        verify(provider, never()).applyConfigurationPlanIfUnchanged(anyList(), anyList(), anySet(), anyMap(), any(DeletionGuard.class));
    }

    @Test
    void java11CallerCanCompileReceiptReadAndIdentifiedInvocation() throws Exception {
        Path source = data.resolve("ReceiptJava11.java");
        Files.writeString(source, """
                import java.util.*;
                import org.eclipse.kura.KuraException;
                import org.eclipse.kura.configuration.*;
                class ReceiptJava11 {
                  ConfigurationOperationReceiptService.State read(ConfigurationOperationReceiptService service,
                      String id) throws KuraException { return service.getOperationReceipt(id).state(); }
                  void write(ConfigurationRevisionService service, String id) throws KuraException {
                    service.applyConfigurationPlanIfUnchanged(id, Collections.emptyList(), Collections.emptyList(),
                        Collections.emptySet(), Collections.emptyMap());
                  }
                }
                """);
        var diagnostics = new java.io.ByteArrayOutputStream();
        int result = javax.tools.ToolProvider.getSystemJavaCompiler().run(null, diagnostics, diagnostics,
                "--release", "11", "-cp", System.getProperty("surefire.test.class.path", System.getProperty("java.class.path")),
                "-d", data.toString(), source.toString());
        assertEquals(0, result, diagnostics.toString(java.nio.charset.StandardCharsets.UTF_8));
    }

    @Test
    void danglingDecisionWithoutRequestIsUnknown() throws Exception {
        String id = id();
        Files.createDirectory(root(), PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        Files.write(file(id, ".complete"), new byte[0]);
        assertEquals(State.UNKNOWN, reader().getOperationReceipt(id).state());
        assertThrows(Rejected.class, () -> reader().cancelUnreservedOperation(id));
    }

    @Test
    void legacyWriterReenteredDuringPreflightCannotConsumeTheClientIntent() throws Exception {
        String id = id();
        var service =
                new Fixture() {
                    boolean entered;
                    int denied;

                    @Override
                    public synchronized org.eclipse.kura.configuration.ComponentConfiguration
                            getComponentConfiguration(String pid) {
                        if (!entered) {
                            entered = true;
                            try {
                                super.applyConfigurationPlanIfUnchanged(
                                        List.of(),
                                        List.of(creation("unrelated.legacy")),
                                        Set.of(),
                                        Map.of());
                                fail("reentrant writer admitted during identified preflight");
                            } catch (Rejected rejected) {
                                assertEquals(Reason.CONFLICT, rejected.getReason());
                                denied++;
                            } catch (org.eclipse.kura.KuraException unexpected) {
                                throw new AssertionError(unexpected);
                            }
                        }
                        return super.getComponentConfiguration(pid);
                    }
                };
        // Obtain guards before opening the identified preflight.
        service.entered = true;
        var baseline = service.baseline();
        service.entered = false;
        service.initializeIntentJournal(data);
        try {
            service.applyConfigurationPlanIfUnchanged(
                    id, List.of(update(SECOND, "edited")), List.of(), Set.of(), baseline);
            assertEquals(1, service.denied);
            assertEquals(List.of("update:" + SECOND), service.dispatched);
            assertEquals(State.CORE_COMMITTED, reader().getOperationReceipt(id).state());
        } finally {
            service.deactivate();
        }
    }

    @Test
    void completionAndUnresolvedIntentCanBeReadInFreshJvmWithoutReplayingWriter() throws Exception {
        String committed = id(), unknown = id();
        var service = new Fixture();
        service.initializeIntentJournal(data);
        try {
            service.applyConfigurationPlanIfUnchanged(
                    committed, List.of(), List.of(creation(NEW)), Set.of(), Map.of());
            service.failSnapshot = true;
            assertThrows(
                    Exception.class,
                    () ->
                            service.applyConfigurationPlanIfUnchanged(
                                    unknown,
                                    List.of(),
                                    List.of(creation("second.new")),
                                    Set.of(),
                                    Map.of()));
        } finally {
            service.deactivate();
        }
        var process =
                new ProcessBuilder(
                                Path.of(System.getProperty("java.home"), "bin", "java").toString(),
                                "-cp",
                                System.getProperty(
                                        "surefire.test.class.path",
                                        System.getProperty("java.class.path")),
                                FreshReceiptReader.class.getName(),
                                root().toString(),
                                committed,
                                unknown)
                        .redirectErrorStream(true)
                        .start();
        assertTrue(process.waitFor(10, TimeUnit.SECONDS));
        assertEquals(
                0,
                process.exitValue(),
                new String(
                        process.getInputStream().readAllBytes(),
                        java.nio.charset.StandardCharsets.UTF_8));
        assertEquals(State.CORE_COMMITTED, reader().getOperationReceipt(committed).state());
        assertEquals(State.UNKNOWN, reader().getOperationReceipt(unknown).state());
    }

    public static class FreshReceiptReader {
        public static void main(String[] args) throws Exception {
            Path root = Path.of(args[0]);
            if (ConfigurationOperationStore.read(root, args[1]).state() != State.CORE_COMMITTED
                    || ConfigurationOperationStore.read(root, args[2]).state() != State.UNKNOWN)
                throw new AssertionError();
            try (var journal = ConfigurationIntentJournal.open(root)) {
                try {
                    journal.requireStartup();
                    throw new AssertionError("pending intent admitted startup");
                } catch (org.eclipse.kura.KuraException expected) {
                }
            }
        }
    }

    @Test
    void recoveryPublicationChangesReceiptToRecoveredAndNeverOriginalSuccess() throws Exception {
        String id = id();
        Path publication = data.resolve("exact-release");
        byte[] bytes =
                "explicit recovery receipt".getBytes(java.nio.charset.StandardCharsets.UTF_8);
        String digest =
                HexFormat.of()
                        .formatHex(
                                java.security.MessageDigest.getInstance("SHA-256").digest(bytes));
        try (var journal = ConfigurationIntentJournal.open(root())) {
            try (var operation = journal.clientOperation(id, plan())) {
                journal.requireOrdinaryWrite();
                try (var ticket = journal.begin("plan", Set.of(NEW))) {}
            }
            var evidence =
                    new ControlledRecovery.CompletionEvidence(
                            "owned-recovery",
                            "b".repeat(64),
                            "complete-" + UUID.randomUUID(),
                            "c".repeat(64));
            journal.prepareRelease(evidence, publication, digest);
            assertEquals(State.UNKNOWN, reader().getOperationReceipt(id).state());
            Files.write(publication, bytes, StandardOpenOption.CREATE_NEW);
            assertEquals(State.RECOVERED, reader().getOperationReceipt(id).state());
            journal.commitRelease(evidence);
        }
        try (var journal = ConfigurationIntentJournal.open(root())) {
            journal.requireStartup();
        }
        Files.writeString(publication, "changed");
        assertEquals(State.UNKNOWN, reader().getOperationReceipt(id).state());
        assertThrows(Exception.class, () -> ConfigurationIntentJournal.open(root()));
    }

    @Test
    void damagedDispatchLinkTrailingDecisionAndOversizeRequestRemainUnknown() throws Exception {
        String id = id();
        try (var journal = ConfigurationIntentJournal.open(root())) {
            try (var operation = journal.clientOperation(id, plan())) {
                journal.requireOrdinaryWrite();
                try (var ticket = journal.begin("plan", Set.of(NEW))) {
                    ticket.complete();
                }
            }
        }
        assertEquals(State.CORE_COMMITTED, reader().getOperationReceipt(id).state());
        byte[] original = Files.readAllBytes(clientFile(id, ".dispatch"));
        Files.write(clientFile(id, ".dispatch"), new byte[] {0});
        assertEquals(State.UNKNOWN, reader().getOperationReceipt(id).state());
        Files.write(clientFile(id, ".dispatch"), original);
        Files.write(file(id, ".complete"), new byte[] {0}, StandardOpenOption.APPEND);
        assertEquals(State.UNKNOWN, reader().getOperationReceipt(id).state());
        Files.write(clientFile(id, ".request"), new byte[(2 << 20) + 1]);
        assertEquals(State.UNKNOWN, reader().getOperationReceipt(id).state());
    }
}
