/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.testing;

import static org.junit.jupiter.api.Assertions.*;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Properties;

import org.eclipse.kura.testing.osgi.EquinoxExtension;
import org.eclipse.kura.testing.osgi.EquinoxRuntime;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.api.parallel.ResourceLock;
import org.junit.jupiter.api.parallel.Resources;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.osgi.framework.Bundle;

/** Real SCR services with temporary property files and a command boundary that cannot execute host commands. */
@ExtendWith(EquinoxExtension.class)
@ResourceLock(Resources.SYSTEM_PROPERTIES)
@Timeout(30)
class SystemServicesRuntimeIT {
    private static final String PROVIDER = "org.eclipse.kura.core.system";
    private static final String API = "org.eclipse.kura.api";
    private static final String SYSTEM = "org.eclipse.kura.system.SystemService";
    @TempDir
    Path directory;

    @ParameterizedTest(name = "{0}.testServiceExists")
    @ValueSource(strings = {"SystemService", "SystemAdminService"})
    void testServiceExists(String serviceName, EquinoxRuntime runtime) throws Exception {
        String contract = "org.eclipse.kura.system." + serviceName;
        assertThrows(ClassNotFoundException.class, () -> Class.forName(contract));
        List<Bundle> bundles = new ArrayList<>();
        for (String source : List.of("target/it-bundles", "target/system-it-bundles")) {
            try (var paths = Files.list(Path.of(source))) {
                for (Path jar : paths.filter(path -> path.toString().endsWith(".jar")).sorted().toList()) {
                    bundles.add(runtime.install(jar));
                }
            }
        }
        runtime.resolve(bundles);
        Class<?> api = runtime.bundle(API).loadClass(SYSTEM);
        Properties original = System.getProperties();
        Properties isolated = new Properties();
        isolated.putAll(original);
        isolated.keySet().removeIf(key -> key.toString().startsWith("kura.")
                || key.equals("dpa.configuration") || key.equals("log4j.configuration"));
        System.setProperties(isolated);
        try {
            prepareProperties(api);
            runtime.start(bundles);
            assertFalse(runtime.hasService(contract, null), "The mandatory executor reference must be required");
            try (var executor = runtime.register(API, "org.eclipse.kura.executor.PrivilegedExecutorService",
                    (proxy, method, args) -> switch (method.getName()) {
                        case "toString" -> "Non-executing privileged executor fixture";
                        case "hashCode" -> System.identityHashCode(proxy);
                        case "equals" -> proxy == args[0];
                        default -> throw new UnsupportedOperationException("Host commands are disabled in this fixture");
                    }, Map.of());
                    var service = runtime.service(contract, "(service.pid=" + contract + ")", Duration.ofSeconds(5))) {
                assertEquals(PROVIDER, service.provider().getSymbolicName());
                assertEquals(Bundle.ACTIVE, service.provider().getState());
                assertSame(runtime.bundle(API).loadClass(contract), service.contract());
                assertEquals(API, runtime.packageProvider(PROVIDER, "org.eclipse.kura.system"));
                assertEquals(API, runtime.packageProvider(PROVIDER, "org.eclipse.kura.executor"));
                if (serviceName.equals("SystemService")) {
                    assertEquals(this.directory.toString(), service.call("getKuraHome"));
                    assertEquals("runtime-fixture", service.call("getKuraVersion"));
                    for (String name : List.of("framework", "user", "snapshots", "tmp")) {
                        assertTrue(Files.isDirectory(this.directory.resolve(name)), name);
                    }
                }
            }
        } finally {
            try {
                runtime.bundle(PROVIDER).stop();
                assertFalse(runtime.hasService(contract, null), "Stopping the provider must remove its services");
            } finally {
                System.setProperties(original);
            }
        }
    }

    private void prepareProperties(Class<?> api) throws Exception {
        Properties defaults = new Properties();
        defaults.setProperty(key(api, "KEY_KURA_HOME_DIR"), this.directory.toString());
        defaults.setProperty(key(api, "KEY_KURA_VERSION"), "runtime-fixture");
        for (var entry : Map.of("KEY_KURA_FRAMEWORK_CONFIG_DIR", "framework", "KEY_KURA_USER_CONFIG_DIR", "user",
                "KEY_KURA_SNAPSHOTS_DIR", "snapshots", "KEY_KURA_TMP_DIR", "tmp").entrySet()) {
            defaults.setProperty(key(api, entry.getKey()), this.directory.resolve(entry.getValue()).toString());
        }
        Path file = this.directory.resolve("defaults.properties");
        try (var writer = Files.newBufferedWriter(file)) { defaults.store(writer, "Isolated system runtime fixture"); }
        Path custom = Files.writeString(this.directory.resolve("custom.properties"), "");
        System.setProperty(key(api, "KURA_CONFIG"), file.toUri().toString());
        System.setProperty(key(api, "KURA_CUSTOM_CONFIG"), custom.toUri().toString());
        System.setProperty("org.eclipse.kura.core.dontExitOnFailure", "true");
    }

    private static String key(Class<?> api, String name) throws Exception {
        return (String) api.getField(name).get(null);
    }
}
