/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.*;
import java.util.*;
import org.eclipse.kura.KuraException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class ConfigurationIntentJournalTest {
    @TempDir Path root;
    Path directory() { return root.resolve("journal"); }
    @Test void unfinishedPreDispatchIntentSurvivesReopenAndBlocksSnapshotStartupAndWrites() throws Exception {
        try (var journal = ConfigurationIntentJournal.open(directory())) {
            try (var ticket = journal.begin("plan", Set.of("fixture.new", "fixture.guard"))) { }
            assertThrows(KuraException.class, journal::requireOrdinaryWrite);
        }
        try (var reopened = ConfigurationIntentJournal.open(directory())) {
            assertThrows(KuraException.class, reopened::requireStartup);
            assertThrows(KuraException.class, reopened::requireOrdinaryWrite);
            assertThrows(KuraException.class, () -> reopened.begin("single", Set.of("fixture.other")));
        }
        assertEquals(1, Files.list(directory()).filter(p -> p.toString().endsWith(".intent")).count());
    }
    @Test void durableCompletionIsLinkedToItsIntentAndRetainsBothRecords() throws Exception {
        try (var journal = ConfigurationIntentJournal.open(directory())) {
            try (var ticket = journal.begin("single", Set.of("fixture.target"))) {
                journal.requireOrdinaryWrite(); ticket.complete();
            }
        }
        try (var reopened = ConfigurationIntentJournal.open(directory())) {
            reopened.requireStartup(); reopened.requireOrdinaryWrite();
        }
        assertEquals(3, Files.list(directory()).count());
    }
    @Test void corruptedCompletionCannotHideItsIntent() throws Exception {
        Path completion;
        try (var journal = ConfigurationIntentJournal.open(directory())) {
            try (var ticket = journal.begin("single", Set.of("fixture.target"))) { ticket.complete(); }
        }
        completion = Files.list(directory()).filter(p -> p.toString().endsWith(".complete")).findFirst().orElseThrow();
        byte[] bytes = Files.readAllBytes(completion); bytes[bytes.length - 1] ^= 1; Files.write(completion, bytes);
        assertThrows(KuraException.class, () -> ConfigurationIntentJournal.open(directory()));
    }
    @Test void aPartialRecordFailsClosedAndIsPreserved() throws Exception {
        try (var journal = ConfigurationIntentJournal.open(directory())) { }
        Path partial = directory().resolve(UUID.randomUUID() + ".intent"); Files.write(partial, new byte[] { 0, 1 });
        assertThrows(KuraException.class, () -> ConfigurationIntentJournal.open(directory()));
        assertArrayEquals(new byte[] { 0, 1 }, Files.readAllBytes(partial));
    }
    @Test void journalOwnershipAndNoFollowAreRealFilesystemConstraints() throws Exception {
        try (var journal = ConfigurationIntentJournal.open(directory())) {
            assertThrows(KuraException.class, () -> ConfigurationIntentJournal.open(directory()));
        }
        Path link = root.resolve("linked"); Files.createSymbolicLink(link, directory());
        assertThrows(KuraException.class, () -> ConfigurationIntentJournal.open(link));
    }
    @Test void emptyRollbackStillHasADurableIntent() throws Exception {
        try (var journal = ConfigurationIntentJournal.open(directory())) {
            try (var ticket = journal.begin("rollback", Set.of())) { }
        }
        try (var reopened = ConfigurationIntentJournal.open(directory())) { assertThrows(KuraException.class, reopened::requireStartup); }
    }
    @Test void writerFailureRecordsSurviveARealCoreObjectReplacement() throws Exception {
        var first = new ConditionalWriteOutcomeTest.Single(new IllegalStateException("owned post-dispatch fault"));
        first.initializeIntentJournal(root);
        assertThrows(KuraException.class, first::write); first.assertUncertain(); first.deactivate();
        var next = new ConditionalWriteOutcomeTest.Single(null); next.initializeIntentJournal(root);
        assertThrows(KuraException.class, next::write); assertEquals(0, next.writes); next.deactivate();
    }
    @Test void successfulCoreDispatchCanBeReopenedWithoutAnUncertainGate() throws Exception {
        var first = new ConditionalWriteOutcomeTest.Single(null); first.initializeIntentJournal(root);
        first.write(); assertEquals(1, first.writes); first.deactivate();
        var next = new ConditionalWriteOutcomeTest.Single(null); next.initializeIntentJournal(root);
        next.write(); assertEquals(1, next.writes); next.deactivate();
    }
    @Test void activationRejectsUnresolvedDispatchBeforeAnyCmSeeding() throws Exception {
        Path store = root.resolve("configuration-dispatch-journal-v1");
        try (var journal = ConfigurationIntentJournal.open(store)) {
            try (var ticket = journal.begin("plan", Set.of("fixture.created", "fixture.deleted"))) { }
        }
        var core = new ConfigurationServiceImpl();
        var system = org.mockito.Mockito.mock(org.eclipse.kura.system.SystemService.class);
        org.mockito.Mockito.when(system.getKuraDataDirectory()).thenReturn(root.toString()); core.setSystemService(system);
        var admin = org.mockito.Mockito.mock(org.osgi.service.cm.ConfigurationAdmin.class); core.setConfigurationAdmin(admin);
        var context = org.mockito.Mockito.mock(org.osgi.service.component.ComponentContext.class);
        assertThrows(org.osgi.service.component.ComponentException.class, () -> core.activate(context));
        org.mockito.Mockito.verifyNoInteractions(admin);
        org.mockito.Mockito.verify(system, org.mockito.Mockito.never()).getKuraSnapshotsDirectory();
        // Failed activation released only its lock, never its retained intent.
        try (var journal = ConfigurationIntentJournal.open(store)) { assertThrows(KuraException.class, journal::requireStartup); }
    }
    @Test void completionPersistenceFailureIsUnknownAfterOneWriterAndNeverResent() throws Exception {
        class FailCompletion extends ConditionalWriteOutcomeTest.Single {
            FailCompletion() { super(null); }
            @Override public synchronized void updateConfiguration(String pid, Map<String,Object> patch, boolean snapshot) throws KuraException {
                super.updateConfiguration(pid, patch, snapshot);
                try (var entries = Files.list(root.resolve("configuration-dispatch-journal-v1"))) {
                    Path intent = entries.filter(p -> p.toString().endsWith(".intent")).findFirst().orElseThrow();
                    Files.createDirectory(intent.resolveSibling(intent.getFileName().toString().replace(".intent", ".complete")));
                } catch (java.io.IOException e) { throw new AssertionError(e); }
            }
        }
        var first = new FailCompletion(); first.initializeIntentJournal(root);
        assertThrows(KuraException.class, first::write); first.assertUncertain();
        assertThrows(KuraException.class, first::write); assertEquals(1, first.writes); first.deactivate();
        assertThrows(KuraException.class, () -> ConfigurationIntentJournal.open(root.resolve("configuration-dispatch-journal-v1")));
    }
    @Test void intentExistsBeforeTheFirstPlanMutationAndFailureRetainsEveryScopeMember() throws Exception {
        class Plan extends ConfigurationPlanAdmissionTest.Fixture {
            Plan() throws Exception { }
            @Override public synchronized void deleteFactoryConfiguration(String pid, boolean snapshot) {
                try (var files = Files.list(root.resolve("configuration-dispatch-journal-v1"))) {
                    assertEquals(1, files.filter(p -> p.toString().endsWith(".intent")).count());
                } catch (java.io.IOException e) { throw new AssertionError(e); }
                super.deleteFactoryConfiguration(pid, snapshot);
            }
        }
        var core = new Plan(); core.initializeIntentJournal(root); core.failAfterCreation = true;
        var before = core.baseline();
        assertThrows(KuraException.class, () -> core.applyConfigurationPlanIfUnchanged(List.of(),
                List.of(ConfigurationPlanAdmissionTest.creation(ConfigurationPlanAdmissionTest.NEW)),
                Set.of(ConfigurationPlanAdmissionTest.FIRST), before));
        assertEquals(List.of("delete:"+ConfigurationPlanAdmissionTest.FIRST,"create:"+ConfigurationPlanAdmissionTest.NEW), core.dispatched);
        core.deactivate();
        try (var files = Files.list(root.resolve("configuration-dispatch-journal-v1"))) {
            String bytes = new String(Files.readAllBytes(files.filter(p -> p.toString().endsWith(".intent")).findFirst().orElseThrow()), java.nio.charset.StandardCharsets.ISO_8859_1);
            for (String pid : List.of(ConfigurationPlanAdmissionTest.FIRST, ConfigurationPlanAdmissionTest.SECOND, ConfigurationPlanAdmissionTest.NEW)) assertTrue(bytes.contains(pid));
            assertFalse(bytes.contains("created"));
        }
    }

    @Test void onlyANewerExplicitRecoveryDecisionCanResolvePendingIntents() throws Exception {
        String oldProperty = System.getProperty(ControlledRecovery.REQUEST_PROPERTY);
        java.lang.reflect.Field admission = ControlledRecovery.class.getDeclaredField("admission"), completion = ControlledRecovery.class.getDeclaredField("completion");
        admission.setAccessible(true); completion.setAccessible(true); Object oldAdmission = admission.get(null), oldCompletion = completion.get(null);
        ConfigurationIntentJournal registered = null;
        try {
            admission.set(null, null); completion.set(null, null);
            Path snapshot = root.resolve("snapshot_42.xml"); Files.writeString(snapshot, "owned recovery artifact");
            String sha = HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(snapshot)));
            System.setProperty(ControlledRecovery.REQUEST_PROPERTY, "owned-recovery-request");
            ControlledRecovery.admitNormalLoad("owned-recovery-request", "owned-recovery", snapshot, sha);
            try (var journal = ConfigurationIntentJournal.open(directory())) {
                registered = journal; ControlledRecovery.registerIntentJournal(journal);
                // A prior ordinary operation left no terminal decision.
                try (var ticket = journal.begin("plan", Set.of("fixture.unknown"))) { }
                journal.requireStartup(); // admitted controlled startup only, still no ordinary release
                assertThrows(KuraException.class, journal::requireOrdinaryWrite);
                String id = "complete-" + UUID.randomUUID(); Path decision = root.resolve("completion.decision");
                String receiptSha = HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest("owned explicit decision".getBytes(java.nio.charset.StandardCharsets.UTF_8)));
                ControlledRecovery.commitOrdinaryWriteRelease(ControlledRecovery.evidence().orElseThrow(), id, sha, decision, receiptSha,
                        () -> Files.writeString(decision, "owned explicit decision", StandardOpenOption.CREATE_NEW));
                journal.requireOrdinaryWrite();
                // This new failure occurred AFTER the release; that old release must not erase it.
                try (var ticket = journal.begin("single", Set.of("fixture.newer-unknown"))) { }
                assertThrows(KuraException.class, journal::requireOrdinaryWrite);
            }
            try (var reopened = ConfigurationIntentJournal.open(directory())) {
                assertThrows(KuraException.class, reopened::requireStartup);
                assertThrows(KuraException.class, reopened::requireOrdinaryWrite);
            }
        } finally {
            if (registered != null) ControlledRecovery.unregisterIntentJournal(registered);
            admission.set(null, oldAdmission); completion.set(null, oldCompletion);
            if (oldProperty == null) System.clearProperty(ControlledRecovery.REQUEST_PROPERTY); else System.setProperty(ControlledRecovery.REQUEST_PROPERTY, oldProperty);
        }
    }

    @Test void unresolvedDispatchDoesNotIssueEditableTokensForOtherTargets() throws Exception {
        var core = new ConditionalWriteOutcomeTest.Single(new IllegalStateException("owned post-dispatch fault"));
        core.initializeIntentJournal(root); assertThrows(KuraException.class, core::write);
        var failure = assertThrows(org.eclipse.kura.configuration.ConfigurationRevisionService.Rejected.class,
                () -> core.readRevision("fixture.unrelated"));
        assertEquals(org.eclipse.kura.configuration.ConfigurationRevisionService.Reason.CONFLICT, failure.getReason());
        assertEquals(1, core.writes); core.deactivate();
    }

}
