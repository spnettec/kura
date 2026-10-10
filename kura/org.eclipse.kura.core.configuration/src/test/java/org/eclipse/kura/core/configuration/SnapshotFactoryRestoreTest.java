package org.eclipse.kura.core.configuration;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Hashtable;
import java.util.List;
import java.util.Map;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.system.SystemService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.osgi.service.cm.Configuration;
import org.osgi.service.cm.ConfigurationAdmin;

class SnapshotFactoryRestoreTest {

    @TempDir Path snapshots;

    @Test
    void existingFactoryConfigurationIsReusedDuringSnapshotRestore() throws Exception {
        Files.writeString(this.snapshots.resolve("snapshot_0.xml"), "fixture");
        var saved = mock(Configuration.class);
        var properties = new Hashtable<String, Object>();
        properties.put(ConfigurationService.KURA_SERVICE_PID, "fixture.instance");
        when(saved.getFactoryPid()).thenReturn("fixture.factory");
        when(saved.getPid()).thenReturn("cm.factory.1");
        when(saved.getProperties()).thenReturn(properties);

        var admin = mock(ConfigurationAdmin.class);
        when(admin.listConfigurations(anyString())).thenReturn(new Configuration[] { saved });
        var system = mock(SystemService.class);
        when(system.getKuraSnapshotsDirectory()).thenReturn(this.snapshots.toString());

        var service = new ConfigurationServiceImpl() {
            @Override
            XmlComponentConfigurations loadEncryptedSnapshotFileContent(long id) {
                var configurations = new XmlComponentConfigurations();
                configurations.setConfigurations(List.of(new ComponentConfigurationImpl("fixture.instance", null,
                        Map.of(ConfigurationAdmin.SERVICE_FACTORYPID, "fixture.factory", "enabled", true))));
                return configurations;
            }
        };
        service.setConfigurationAdmin(admin);
        service.setSystemService(system);

        Method restore = ConfigurationServiceImpl.class.getDeclaredMethod("loadLatestSnapshotInConfigAdmin");
        restore.setAccessible(true);
        restore.invoke(service);

        verify(admin, never()).createFactoryConfiguration("fixture.factory", null);
        verify(saved).updateIfDifferent(org.mockito.ArgumentMatchers.any());
    }
}
