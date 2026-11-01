/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ConfigurationRevisionService.Reason;
import org.eclipse.kura.configuration.ConfigurationRevisionService.Rejected;
import org.eclipse.kura.configuration.Password;
import org.junit.jupiter.api.Test;
import org.osgi.service.cm.Configuration;
import org.osgi.service.cm.ConfigurationAdmin;

class ConfigurationRevisionAdmissionTest {
    private static final String PID = "fixture.revision";

    private static final class Fixture extends ConfigurationServiceImpl {
        Map<String, Object> current = new HashMap<>(Map.of("name", "initial", "password", new Password("original")));
        Map<String, Object> delayed;
        boolean delay;
        boolean failAfterWrite;
        boolean tracked = true;
        Map<String, Object> submitted;
        int writes;
        final AtomicLong changeCount = new AtomicLong();

        Fixture() throws Exception {
            var config = mock(Configuration.class); when(config.getChangeCount()).thenAnswer(i -> this.changeCount.get());
            var admin = mock(ConfigurationAdmin.class); when(admin.getConfiguration(PID, "?")).thenReturn(config);
            setConfigurationAdmin(admin);
            var field = ConfigurationServiceImpl.class.getDeclaredField("servicePidByPid"); field.setAccessible(true);
            @SuppressWarnings("unchecked") var pids = (Map<String, String>) field.get(this); pids.put(PID, PID);
        }

        @Override public synchronized ComponentConfiguration getComponentConfiguration(String pid) {
            return PID.equals(pid) ? ConfigurationRevisionTest.component(this.current) : null;
        }

        @Override public synchronized void updateConfiguration(String pid, Map<String, Object> patch, boolean snapshot)
                throws KuraException {
            assertEquals(PID, pid); assertTrue(snapshot); this.writes++; this.changeCount.incrementAndGet();
            this.submitted = new HashMap<>(patch);
            if (this.delay) { this.delayed = new HashMap<>(patch); }
            else { this.current.putAll(patch); }
            if (this.failAfterWrite) { throw new KuraException(org.eclipse.kura.KuraErrorCode.CONFIGURATION_UPDATE); }
        }

        @Override protected boolean revisionTargetTracked(String pid) { return this.tracked && PID.equals(pid); }
    }

    @Test void concurrentReadersCannotBothCommitAndOmittedPasswordsSurvive() throws Exception {
        var service = new Fixture(); String revision = service.readRevision(PID).revision();
        var start = new CountDownLatch(1);
        try (var workers = Executors.newFixedThreadPool(2)) {
            var first = workers.submit(() -> attempt(service, revision, "first", start));
            var second = workers.submit(() -> attempt(service, revision, "second", start));
            start.countDown();
            assertNotEquals(first.get(5, TimeUnit.SECONDS), second.get(5, TimeUnit.SECONDS));
        }
        assertEquals(1, service.writes);
        assertArrayEquals("original".toCharArray(), ((Password) service.current.get("password")).getPassword());
        assertNotEquals(revision, service.readRevision(PID).revision());
    }

    private static boolean attempt(Fixture service, String revision, String value, CountDownLatch start) throws Exception {
        assertTrue(start.await(5, TimeUnit.SECONDS));
        try { service.updateRevision(PID, revision, Map.of("name", value)); return true; }
        catch (Rejected e) { assertEquals(Reason.CONFLICT, e.getReason()); return false; }
    }

    @Test void sameValueLegacyAbaAndCrossInstanceTokensAreRejectedBeforeWriting() throws Exception {
        var service = new Fixture(); String revision = service.readRevision(PID).revision();
        service.updateConfiguration(PID, Map.of("name", "temporary"), true);
        service.updateConfiguration(PID, Map.of("name", "initial"), true);
        assertEquals(Reason.CONFLICT, assertThrows(Rejected.class,
                () -> service.updateRevision(PID, revision, Map.of("name", "stale"))).getReason());
        assertEquals(2, service.writes);
        String fresh = service.readRevision(PID).revision();
        var restarted = new Fixture(); restarted.changeCount.set(2);
        assertEquals(Reason.CONFLICT, assertThrows(Rejected.class,
                () -> restarted.updateRevision(PID, fresh, Map.of("name", "stale"))).getReason());
        assertEquals(0, restarted.writes);
    }

    @Test void delayedSelfConfigurationCannotProduceAWritableOldView() throws Exception {
        var service = new Fixture(); service.delay = true;
        String revision = service.readRevision(PID).revision();
        service.updateRevision(PID, revision, Map.of("name", "submitted"));
        assertEquals(Reason.CONFLICT, assertThrows(Rejected.class, () -> service.readRevision(PID)).getReason());
        assertEquals(Reason.CONFLICT, assertThrows(Rejected.class,
                () -> service.updateRevision(PID, revision, Map.of("name", "overwrite"))).getReason());
        assertEquals(1, service.writes);
        service.current.putAll(service.delayed);
        assertNotEquals(revision, service.readRevision(PID).revision());
    }

    @Test void aFailureAfterMutationWithholdsFreshTokensEvenWhenValuesMatch() throws Exception {
        var service = new Fixture(); String revision = service.readRevision(PID).revision();
        service.failAfterWrite = true;
        assertThrows(KuraException.class, () -> service.updateRevision(PID, revision, Map.of("name", "written")));
        assertEquals("written", service.current.get("name"));
        assertEquals(Reason.CONFLICT, assertThrows(Rejected.class, () -> service.readRevision(PID)).getReason());
        assertEquals(Reason.CONFLICT, assertThrows(Rejected.class,
                () -> service.updateRevision(PID, revision, Map.of("name", "again"))).getReason());
        assertEquals(1, service.writes);
    }

    @Test void rejectsMissingTargetsSystemFieldsAndIncorrectTypesWithoutCallingWriter() throws Exception {
        var service = new Fixture(); String revision = service.readRevision(PID).revision();
        assertEquals(Reason.NOT_FOUND, assertThrows(Rejected.class, () -> service.readRevision("missing")).getReason());
        for (Map<String, Object> patch : java.util.List.of(Map.<String, Object>of("service.pid", "changed"),
                Map.<String, Object>of("count", "9223372036854775807"), Map.<String, Object>of("password", "ambiguous"))) {
            assertEquals(Reason.INVALID_ARGUMENT, assertThrows(Rejected.class,
                    () -> service.updateRevision(PID, revision, patch)).getReason());
        }
        assertEquals(Reason.INVALID_ARGUMENT, assertThrows(Rejected.class,
                () -> service.updateRevision(PID, "invalid", Map.of("name", "bad"))).getReason());
        assertEquals(0, service.writes);
    }

    @Test void untrackedComponentDoesNotBurnAdmission() throws Exception {
        var service = new Fixture(); service.tracked = false;
        String revision = service.readRevision(PID).revision();
        var rejected = assertThrows(Rejected.class, () -> service.updateRevision(PID, revision, Map.of("name", "no-write")));
        assertEquals(Reason.UNSUPPORTED, rejected.getReason());
        assertEquals(0, service.writes);
        service.tracked = true;
        service.updateRevision(PID, revision, Map.of("name", "kept"));
        assertEquals("kept", service.current.get("name"));
    }

    @Test void selfConfiguringUpdatePreservesOmittedObservedValues() throws Exception {
        var service = new Fixture();
        var field = ConfigurationServiceImpl.class.getDeclaredField("activatedSelfConfigComponents");
        field.setAccessible(true);
        @SuppressWarnings("unchecked") var self = (java.util.Set<String>) field.get(service);
        self.add(PID);
        String revision = service.readRevision(PID).revision();
        service.updateRevision(PID, revision, Map.of("name", "from-view"));
        assertEquals("from-view", service.submitted.get("name"));
        assertArrayEquals("original".toCharArray(), ((Password) service.submitted.get("password")).getPassword());
        assertEquals("from-view", service.current.get("name"));
    }
}
