/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.io.IOException;
import java.io.OutputStream;
import java.lang.reflect.InvocationTargetException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Hashtable;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.concurrent.atomic.AtomicReference;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.configuration.ExternalConfigurationHandler;
import org.eclipse.kura.configuration.ExternalConfigurationHandler.ChangeSource;
import org.eclipse.kura.system.SystemService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.api.parallel.ResourceLock;
import org.junit.jupiter.api.parallel.Resources;
import org.osgi.service.cm.Configuration;
import org.osgi.service.cm.ConfigurationAdmin;

@ResourceLock(Resources.SYSTEM_PROPERTIES)
class ExternalConfigurationRoutingTest {
    private static final String PID = "org.eclipse.kura.net.admin.NetworkConfigurationService";
    private static final String OTHER = "fixture.other";
    @TempDir Path snapshots;
    private String previousProperty;
    private ConfigurationAdmin admin;
    private ExternalConfigurationHandler owner;
    private Fixture service;

    @BeforeEach
    void setup() throws Exception {
        this.previousProperty = System.getProperty(ExternalConfigurations.RESERVED_PIDS_PROPERTY);
        System.setProperty(ExternalConfigurations.RESERVED_PIDS_PROPERTY, PID);
        this.admin = mock(ConfigurationAdmin.class);
        this.owner = mock(ExternalConfigurationHandler.class);
        when(this.owner.getPid()).thenReturn(PID);
        when(this.owner.getConfirmedConfiguration()).thenReturn(config(PID, "confirmed"));
        this.service = new Fixture();
        this.service.setConfigurationAdmin(this.admin);
        var system = mock(SystemService.class);
        when(system.getKuraSnapshotsDirectory()).thenReturn(this.snapshots.toString());
        when(system.getKuraSnapshotsCount()).thenReturn(10);
        var properties = new Properties();
        properties.setProperty("kura.snapshots.encrypt", "false");
        when(system.getProperties()).thenReturn(properties);
        this.service.setSystemService(system);
        this.service.addExternalConfigurationHandler(this.owner);
    }

    @AfterEach
    void restoreProperty() {
        if (this.previousProperty == null) {
            System.clearProperty(ExternalConfigurations.RESERVED_PIDS_PROPERTY);
        } else {
            System.setProperty(ExternalConfigurations.RESERVED_PIDS_PROPERTY, this.previousProperty);
        }
    }

    @Test
    void revisionedWritesCannotBypassTheNetworkOwner() throws Exception {
        var error = assertThrows(org.eclipse.kura.configuration.ConfigurationRevisionService.Rejected.class,
                () -> this.service.readRevision(PID));
        assertEquals(org.eclipse.kura.configuration.ConfigurationRevisionService.Reason.UNSUPPORTED, error.getReason());
        verifyNoInteractions(this.admin);
        verify(this.owner, never()).applyConfiguration(anyMap(), any());
    }

    @Test
    void genericUpdateIsRoutedWithoutWritingConfigAdminAndSnapshotContainsOnlyConfirmedState() throws Exception {
        this.service.updateConfiguration(PID, new HashMap<>(Map.of("value", "candidate", "revision", 4L)), true);

        verify(this.owner).validateConfiguration(Map.of("value", "candidate", "revision", 4L),
                ChangeSource.CONFIGURATION_UPDATE);
        verify(this.owner).applyConfiguration(Map.of("value", "candidate", "revision", 4L),
                ChangeSource.CONFIGURATION_UPDATE);
        verifyNoInteractions(this.admin);
        assertEquals("confirmed", this.service.serialized.get().getConfigurations().get(0)
                .getConfigurationProperties().get("value"));
        assertEquals(1, this.service.getSnapshots().size());
        assertFalse(Files.readString(this.snapshots.resolve("snapshot_" + this.service.getSnapshots().iterator().next() + ".xml"))
                .contains("candidate"));
    }

    @Test
    void partialUpdatesMergeWithAuthoritativeStateAndPublicReadCannotMutateIt() throws Exception {
        this.service.updateConfiguration(PID, new HashMap<>(Map.of("revision", 4L)), false);
        verify(this.owner).applyConfiguration(Map.of("value", "confirmed", "revision", 4L),
                ChangeSource.CONFIGURATION_UPDATE);
        this.service.getComponentConfiguration(PID).getConfigurationProperties().put("value", "tampered");
        assertEquals("confirmed", this.service.getComponentConfiguration(PID).getConfigurationProperties().get("value"));
    }

    @Test
    void preflightFailureRejectsTheWholeRequestBeforeAnyConfigurationOrSnapshotIsChanged() throws Exception {
        doThrow(new KuraException(KuraErrorCode.CONFIGURATION_UPDATE, "CONFLICT"))
                .when(this.owner).validateConfiguration(anyMap(), any());
        assertThrows(KuraException.class, () -> this.service.updateConfigurations(
                List.of(config(OTHER, "other-candidate"), config(PID, "candidate")), true));
        verify(this.owner, never()).applyConfiguration(anyMap(), any());
        verifyNoInteractions(this.admin);
        assertTrue(this.service.getSnapshots().isEmpty());
    }

    @Test
    void ownerDisconnectRejectsUpdatesAndSnapshotsInsteadOfPersistingAnOldMirror() throws Exception {
        this.service.removeExternalConfigurationHandler(this.owner);
        assertThrows(KuraException.class, () -> this.service.updateConfiguration(PID, Map.of("value", "candidate")));
        assertThrows(KuraException.class, () -> this.service.getComponentConfiguration(PID));
        assertThrows(KuraException.class, () -> this.service.snapshot());
        verifyNoInteractions(this.admin);
        assertTrue(this.service.getSnapshots().isEmpty());
    }

    @Test
    void duplicateOwnersAndDuplicateRequestsFailClosed() throws Exception {
        var duplicate = mock(ExternalConfigurationHandler.class);
        when(duplicate.getPid()).thenReturn(PID);
        this.service.addExternalConfigurationHandler(duplicate);
        assertThrows(KuraException.class, () -> this.service.updateConfiguration(PID, Map.of("value", "candidate")));
        this.service.removeExternalConfigurationHandler(duplicate);
        assertThrows(KuraException.class, () -> this.service.updateConfigurations(
                List.of(config(PID, "first"), config(PID, "second")), true));
        verify(this.owner, never()).applyConfiguration(anyMap(), any());
        verifyNoInteractions(this.admin);
    }

    @Test
    void bootReservationProtectsThePidBeforeAnyOwnerConnects() throws Exception {
        var fresh = new Fixture();
        fresh.setConfigurationAdmin(this.admin);
        assertThrows(KuraException.class, () -> fresh.updateConfiguration(PID, Map.of("value", "candidate")));
        verifyNoInteractions(this.admin);
    }

    @Test
    void aServiceCannotAcquireAnUnreservedPidAtRuntime() {
        var unreserved = mock(ExternalConfigurationHandler.class);
        when(unreserved.getPid()).thenReturn(OTHER);
        assertThrows(IllegalStateException.class, () -> this.service.addExternalConfigurationHandler(unreserved));
    }

    @Test
    void startupDoesNotReplayTheNetworkSnapshotOrApplyATransaction() throws Exception {
        seed(List.of(config(PID, "old-snapshot")));
        this.service.removeExternalConfigurationHandler(this.owner);
        invoke("loadLatestSnapshotInConfigAdmin");
        verify(this.admin, never()).getConfiguration(eq(PID), anyString());
        verify(this.owner, never()).validateConfiguration(anyMap(), any());
        verify(this.owner, never()).applyConfiguration(anyMap(), any());
        verify(this.owner, never()).getConfirmedConfiguration();
    }

    @Test
    void earlyRegisteredOwnerDoesNotMakeCoreBootstrapDependOnItsTransport() throws Exception {
        seed(List.of(config(PID, "old-snapshot")));
        this.service.registerSelfConfiguringComponent(PID, PID);
        when(this.owner.getConfirmedConfiguration()).thenThrow(new KuraException(KuraErrorCode.CONFIGURATION_ERROR));
        invoke("loadLatestSnapshotInConfigAdmin");
        verify(this.owner, never()).getConfirmedConfiguration();
        verify(this.admin, never()).getConfiguration(eq(PID), anyString());
        // The bootstrap exclusion must not weaken normal reads or new snapshots.
        assertThrows(KuraException.class, () -> this.service.getComponentConfigurations());
        assertThrows(KuraException.class, () -> this.service.snapshot());
        assertEquals(1, this.service.getSnapshots().size());
    }

    @Test
    void rejectedOrIndeterminateApplicationDoesNotFallBackToConfigAdmin() throws Exception {
        seed(List.of(config(PID, "old-snapshot")));
        doThrow(new KuraException(KuraErrorCode.CONFIGURATION_UPDATE, "UNKNOWN"))
                .when(this.owner).applyConfiguration(anyMap(), any());
        assertThrows(KuraException.class, () -> this.service.updateConfiguration(PID,
                new HashMap<>(Map.of("value", "candidate")), true));
        verifyNoInteractions(this.admin);
        assertEquals(1, this.service.getSnapshots().size());
        assertEquals("old-snapshot-file", Files.readString(this.snapshots.resolve("snapshot_1.xml")));
    }

    @Test
    void explicitRollbackUsesTheCoordinatorAndDoesNotWriteTheNetworkConfigAdmin() throws Exception {
        seed(List.of(config(PID, "historical-target")));
        var current = current(PID);
        when(this.admin.listConfigurations(anyString())).thenReturn(new Configuration[] {current});
        this.service.rollback(1);
        verify(this.owner).validateConfiguration(Map.of("value", "historical-target"), ChangeSource.SNAPSHOT_ROLLBACK);
        verify(this.owner).applyConfiguration(Map.of("value", "historical-target"), ChangeSource.SNAPSHOT_ROLLBACK);
        verify(current, never()).update(any());
        verify(this.admin, never()).getConfiguration(eq(PID), anyString());
        assertEquals("old-snapshot-file", Files.readString(this.snapshots.resolve("snapshot_1.xml")));
    }

    @Test
    void rollbackRejectsOmittedNetworkPidBeforeResettingOtherConfigurations() throws Exception {
        seed(List.of(config(OTHER, "historical")));
        var network = current(PID);
        var other = current(OTHER);
        when(this.admin.listConfigurations(anyString())).thenReturn(new Configuration[] {network, other});
        assertThrows(KuraException.class, () -> this.service.rollback(1));
        verify(network, never()).update(any());
        verify(other, never()).update(any());
        verify(this.owner, never()).applyConfiguration(anyMap(), any());
        verify(this.admin, never()).getConfiguration(anyString(), anyString());
    }

    @Test
    void olderRollbackSnapshotIsSavedWithConfirmedNetworkState() throws Exception {
        seed(List.of(config(PID, "historical-target")));
        Files.writeString(this.snapshots.resolve("snapshot_2.xml"), "newer");
        this.service.rollback(1);
        assertEquals("confirmed", this.service.serialized.get().getConfigurations().get(0)
                .getConfigurationProperties().get("value"));
        assertEquals("old-snapshot-file", Files.readString(this.snapshots.resolve("snapshot_1.xml")));
    }

    @Test
    void factoryOperationsCannotBypassTheOwner() throws Exception {
        assertThrows(KuraException.class, () -> this.service.createFactoryConfiguration("factory", PID, Map.of(), false));
        assertThrows(KuraException.class, () -> this.service.deleteFactoryConfiguration(PID, false));
        assertThrows(KuraException.class, () -> this.service.updateConfiguration(PID,
                Map.of(ConfigurationAdmin.SERVICE_FACTORYPID, "factory"), false));
        verifyNoInteractions(this.admin);
        verify(this.owner, never()).applyConfiguration(anyMap(), any());
    }

    @Test
    void malformedOrUnavailableConfirmedStateIsNeverSaved() throws Exception {
        when(this.owner.getConfirmedConfiguration()).thenReturn(config(OTHER, "wrong-pid"));
        assertThrows(KuraException.class, () -> this.service.snapshot());
        when(this.owner.getConfirmedConfiguration()).thenReturn(null);
        assertThrows(KuraException.class, () -> this.service.snapshot());
        assertTrue(this.service.getSnapshots().isEmpty());
    }

    private void seed(List<ComponentConfiguration> configurations) throws IOException {
        this.service.historical = configurations;
        Files.writeString(this.snapshots.resolve("snapshot_1.xml"), "old-snapshot-file");
    }

    private void invoke(String methodName) throws Exception {
        var method = ConfigurationServiceImpl.class.getDeclaredMethod(methodName);
        method.setAccessible(true);
        try {
            method.invoke(this.service);
        } catch (InvocationTargetException e) {
            throw (Exception) e.getCause();
        }
    }

    private static ComponentConfiguration config(String pid, String value) {
        return new ComponentConfigurationImpl(pid, null, new HashMap<>(Map.of("value", value)));
    }

    private static Configuration current(String pid) {
        var current = mock(Configuration.class);
        var properties = new Hashtable<String, Object>();
        properties.put(ConfigurationService.KURA_SERVICE_PID, pid);
        properties.put("value", "old-cm-mirror");
        when(current.getProperties()).thenReturn(properties);
        return current;
    }

    private static final class Fixture extends ConfigurationServiceImpl {
        private List<ComponentConfiguration> historical = List.of();
        private final AtomicReference<XmlComponentConfigurations> serialized = new AtomicReference<>();

        @Override
        XmlComponentConfigurations loadEncryptedSnapshotFileContent(long id) {
            var result = new XmlComponentConfigurations();
            result.setConfigurations(this.historical);
            return result;
        }

        @Override
        protected void marshal(OutputStream out, Object value) throws KuraException {
            var configurations = (XmlComponentConfigurations) value;
            this.serialized.set(configurations);
            try {
                out.write(configurations.getConfigurations().toString().getBytes(StandardCharsets.UTF_8));
            } catch (IOException e) {
                throw KuraException.internalError(e);
            }
        }
    }
}
