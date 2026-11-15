/* Copyright (c) 2026 YOFC. SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ConfigurationRevisionService;
import org.eclipse.kura.configuration.ExternalConfigurationHandler;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.parallel.ResourceLock;
import org.junit.jupiter.api.parallel.Resources;
import org.osgi.service.cm.ConfigurationAdmin;

@ResourceLock(Resources.SYSTEM_PROPERTIES)
class ExternalConfirmedCohortTest {
    private static final String NETWORK = "org.eclipse.kura.net.admin.NetworkConfigurationService";
    private static final String V4 = "org.eclipse.kura.net.admin.FirewallConfigurationService";
    private static final String V6 = "org.eclipse.kura.net.admin.ipv6.FirewallConfigurationServiceIPv6";
    private static final Set<String> PIDS = Set.of(NETWORK, V4, V6);
    private String previous;
    private ConfigurationServiceImpl service;
    private ConfigurationAdmin admin;
    private final Map<String, ExternalConfigurationHandler> owners = new HashMap<>();
    private final Map<String, ComponentConfiguration> configurations = new HashMap<>();
    private final Map<String, Map<String, Object>> properties = new HashMap<>();

    @BeforeEach void setup() throws Exception {
        previous = System.getProperty(ExternalConfigurations.RESERVED_PIDS_PROPERTY);
        System.setProperty(ExternalConfigurations.RESERVED_PIDS_PROPERTY, String.join(",", PIDS));
        service = new ConfigurationServiceImpl();
        admin = mock(ConfigurationAdmin.class);
        service.setConfigurationAdmin(admin);
        for (String pid : PIDS) {
            var values = new HashMap<String, Object>();
            values.put("value", new String[] { "original" });
            var configuration = mock(ComponentConfiguration.class);
            when(configuration.getPid()).thenReturn(pid);
            when(configuration.getConfigurationProperties()).thenReturn(values);
            var owner = mock(ExternalConfigurationHandler.class);
            when(owner.getPid()).thenReturn(pid);
            when(owner.getConfirmedConfiguration()).thenReturn(configuration);
            owners.put(pid, owner); configurations.put(pid, configuration); properties.put(pid, values);
            service.addExternalConfigurationHandler(owner);
        }
    }

    @AfterEach void restore() {
        if (previous == null) System.clearProperty(ExternalConfigurations.RESERVED_PIDS_PROPERTY);
        else System.setProperty(ExternalConfigurations.RESERVED_PIDS_PROPERTY, previous);
    }

    @Test void allThreeAreReadOnlyDetachedAndCannotUseConfigAdmin() throws Exception {
        var result = service.readExternalConfirmedConfigurations(PIDS);
        assertEquals(PIDS, result.keySet());
        assertThrows(UnsupportedOperationException.class, result::clear);
        for (String pid : PIDS) {
            assertEquals(pid, result.get(pid).getPid());
            var original = (String[]) properties.get(pid).get("value");
            var detached = (String[]) result.get(pid).getConfigurationProperties().get("value");
            assertNotSame(original, detached);
            detached[0] = "caller edit";
            assertEquals("original", original[0]);
            verify(owners.get(pid)).getConfirmedConfiguration();
            verify(owners.get(pid), never()).applyConfiguration(anyMap(), any());
        }
        verifyNoInteractions(admin);
    }

    @Test void missingHandlerRefusesBeforeReadingAnyRemainingProvider() throws Exception {
        service.removeExternalConfigurationHandler(owners.get(V6));
        assertThrows(KuraException.class, () -> service.readExternalConfirmedConfigurations(PIDS));
        for (var owner : owners.values()) verify(owner, never()).getConfirmedConfiguration();
        verifyNoInteractions(admin);
    }

    @Test void duplicateHandlerCannotBeChosenArbitrarily() throws Exception {
        var duplicate = mock(ExternalConfigurationHandler.class);
        when(duplicate.getPid()).thenReturn(V6);
        service.addExternalConfigurationHandler(duplicate);
        assertThrows(KuraException.class, () -> service.readExternalConfirmedConfigurations(PIDS));
        for (var owner : owners.values()) verify(owner, never()).getConfirmedConfiguration();
        verifyNoInteractions(admin);
    }

    @Test void removalAndRebindingTheSameObjectDuringReadCannotHideAnAbaChange() throws Exception {
        String first = new TreeSet<>(PIDS).first();
        String last = new TreeSet<>(PIDS).last();
        when(owners.get(first).getConfirmedConfiguration()).thenAnswer(call -> {
            service.removeExternalConfigurationHandler(owners.get(last));
            service.addExternalConfigurationHandler(owners.get(last));
            return configurations.get(first);
        });
        assertThrows(KuraException.class, () -> service.readExternalConfirmedConfigurations(PIDS));
        verify(owners.get(last), never()).getConfirmedConfiguration();
        verifyNoInteractions(admin);
    }

    @Test void malformedProviderIdentityRefusesTheWholeResult() throws Exception {
        when(configurations.get(V6).getPid()).thenReturn("another.pid");
        assertThrows(KuraException.class, () -> service.readExternalConfirmedConfigurations(PIDS));
        verifyNoInteractions(admin);
    }

    @Test void lateStartupPropertyAndGenericCmCannotCreateAnUnreservedOwner() throws Exception {
        System.setProperty(ExternalConfigurations.RESERVED_PIDS_PROPERTY, String.join(",", PIDS) + ",late.pid");
        var rejected = assertThrows(ConfigurationRevisionService.Rejected.class,
                () -> service.readExternalConfirmedConfigurations(Set.of(NETWORK, "late.pid")));
        assertEquals(ConfigurationRevisionService.Reason.UNSUPPORTED, rejected.getReason());
        for (var owner : owners.values()) verify(owner, never()).getConfirmedConfiguration();
        verifyNoInteractions(admin);
    }

    @Test void emptyOrInvalidRequestsNeverReadAProvider() throws Exception {
        for (Set<String> requested : java.util.List.of(Set.<String>of(), Set.of("bad\nPID"))) {
            var rejected = assertThrows(ConfigurationRevisionService.Rejected.class,
                    () -> service.readExternalConfirmedConfigurations(requested));
            assertEquals(ConfigurationRevisionService.Reason.INVALID_ARGUMENT, rejected.getReason());
        }
        for (var owner : owners.values()) verify(owner, never()).getConfirmedConfiguration();
        verifyNoInteractions(admin);
    }

    @Test void olderProviderRejectsWithoutFallingBackToSinglePidOrGenericReads() throws Exception {
        var older = mock(ConfigurationRevisionService.class, org.mockito.Answers.CALLS_REAL_METHODS);
        var rejected = assertThrows(ConfigurationRevisionService.Rejected.class,
                () -> older.readExternalConfirmedConfigurations(PIDS));
        assertEquals(ConfigurationRevisionService.Reason.UNSUPPORTED, rejected.getReason());
        verify(older, never()).readExternalConfirmedConfiguration(anyString());
        verify(older, never()).readRevision(anyString());
    }
}
