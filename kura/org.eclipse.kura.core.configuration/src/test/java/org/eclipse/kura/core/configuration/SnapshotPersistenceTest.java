package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.reflect.InvocationTargetException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.system.SystemService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class SnapshotPersistenceTest {
    @TempDir Path directory;
    private static final String XML = "<?xml version=\"1.0\"?><configurations/>";

    private ConfigurationServiceImpl service(Properties properties, CryptoService crypto) {
        var service = new ConfigurationServiceImpl() {
            @Override protected void marshal(OutputStream output, Object value) throws KuraException {
                try { output.write(XML.getBytes(StandardCharsets.UTF_8)); }
                catch (IOException e) { throw KuraException.internalError(e); }
            }
        };
        configure(service, properties, crypto);
        return service;
    }

    private void configure(ConfigurationServiceImpl service, Properties properties, CryptoService crypto) {
        SystemService system = mock(SystemService.class);
        when(system.getProperties()).thenReturn(properties);
        when(system.getKuraSnapshotsDirectory()).thenReturn(directory.toString());
        service.setSystemService(system);
        service.setCryptoService(crypto);
    }

    private static Object invoke(ConfigurationServiceImpl service, String name, Class<?>[] types, Object... arguments)
            throws Exception {
        var method = ConfigurationServiceImpl.class.getDeclaredMethod(name, types);
        method.setAccessible(true);
        try { return method.invoke(service, arguments); }
        catch (InvocationTargetException e) {
            if (e.getCause() instanceof Error error) throw error;
            throw (Exception) e.getCause();
        }
    }

    @ParameterizedTest
    @ValueSource(strings = {"default", "true", "false"})
    void encryptionIsEnabledByDefaultAndCanBeDisabled(String setting) throws Exception {
        var properties = new Properties();
        if (!setting.equals("default")) properties.setProperty("kura.snapshots.encrypt", setting);
        var crypto = mock(CryptoService.class);
        doAnswer(call -> {
            OutputStream output = call.getArgument(1);
            output.write("ENCRYPTED:".getBytes(StandardCharsets.UTF_8));
            ((InputStream) call.getArgument(0)).transferTo(output);
            return null;
        }).when(crypto).encryptAes(any(InputStream.class), any(OutputStream.class));
        var configs = new XmlComponentConfigurations();
        configs.setConfigurations(List.of(new ComponentConfigurationImpl("pid", null, Map.of("value", "x"))));
        invoke(service(properties, crypto), "writeSnapshot", new Class<?>[] {long.class, XmlComponentConfigurations.class},
                7L, configs);
        Path snapshot = directory.resolve("snapshot_7.xml");
        var privatePermissions = java.nio.file.attribute.PosixFilePermissions.fromString("rw-------");
        assertEquals(privatePermissions, Files.getPosixFilePermissions(snapshot));
        Files.setPosixFilePermissions(snapshot,
                java.nio.file.attribute.PosixFilePermissions.fromString("rw-r--r--"));
        invoke(service(properties, crypto), "writeSnapshot", new Class<?>[] {long.class, XmlComponentConfigurations.class},
                7L, configs);
        assertEquals(privatePermissions, Files.getPosixFilePermissions(snapshot));
        assertEquals(setting.equals("false") ? XML : "ENCRYPTED:" + XML,
                Files.readString(directory.resolve("snapshot_7.xml")));
        if (setting.equals("false")) verifyNoInteractions(crypto);
        else verify(crypto, times(2)).encryptAes(any(InputStream.class), any(OutputStream.class));
    }

    @Test
    void corruptedNewestSnapshotIsRetainedAndPreviousSnapshotIsLoaded() throws Exception {
        Files.writeString(directory.resolve("snapshot_1.xml"), "valid snapshot");
        Files.writeString(directory.resolve("snapshot_2.xml"), "broken snapshot");
        var expected = new XmlComponentConfigurations();
        expected.setConfigurations(List.of(new ComponentConfigurationImpl("previous.pid", null, Map.of())));
        var service = new ConfigurationServiceImpl() {
            @Override XmlComponentConfigurations loadEncryptedSnapshotFileContent(long id) throws KuraException {
                if (id == 2L) throw new KuraException(KuraErrorCode.DECODER_ERROR);
                return expected;
            }
        };
        var properties = new Properties();
        properties.setProperty("kura.snapshots.encrypt", "false");
        configure(service, properties, mock(CryptoService.class));
        assertEquals(expected.getConfigurations(), invoke(service, "loadLatestSnapshotConfigurations", new Class<?>[0]));
        assertFalse(Files.exists(directory.resolve("snapshot_2.xml")));
        assertEquals("broken snapshot", Files.readString(directory.resolve("snapshot_2.xml.bad")));
        assertEquals("valid snapshot", Files.readString(directory.resolve("snapshot_1.xml")));
    }
}
