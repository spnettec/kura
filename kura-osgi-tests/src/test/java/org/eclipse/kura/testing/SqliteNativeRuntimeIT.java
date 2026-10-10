/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.testing;

import static org.junit.jupiter.api.Assertions.*;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Properties;

import org.eclipse.kura.testing.osgi.EquinoxExtension;
import org.eclipse.kura.testing.osgi.EquinoxRuntime;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.api.parallel.ResourceLock;
import org.junit.jupiter.api.parallel.Resources;
import org.osgi.framework.Bundle;

/** Native placement is a bundle-activator contract, so it runs in real Equinox. */
@ExtendWith(EquinoxExtension.class)
@ResourceLock(Resources.SYSTEM_PROPERTIES)
@Timeout(30)
class SqliteNativeRuntimeIT {
    private static final String PROVIDER = "org.eclipse.kura.db.sqlite.provider";
    private static final String CONTRACT = "org.eclipse.kura.db.BaseDbService";
    private static final String PID = "org.eclipse.kura.db.SQLiteDbService";
    @TempDir
    Path directory;

    @Test
    void shouldNotExtractNativeLibrariesInJavaTempdir(EquinoxRuntime runtime) throws Exception {
        assertThrows(ClassNotFoundException.class, () -> Class.forName(CONTRACT));
        assertThrows(ClassNotFoundException.class, () -> Class.forName("org.sqlite.JDBC"));
        List<Bundle> bundles = new ArrayList<>();
        for (String source : List.of("target/it-bundles", "target/sqlite-it-bundles")) {
            try (var paths = Files.list(Path.of(source))) {
                for (Path jar : paths.filter(path -> path.toString().endsWith(".jar")).sorted().toList()) {
                    bundles.add(runtime.install(jar));
                }
            }
        }
        runtime.resolve(bundles);
        Properties original = System.getProperties();
        Properties isolated = new Properties();
        isolated.putAll(original);
        for (String key : List.of("org.sqlite.tmpdir", "org.sqlite.lib.path", "org.sqlite.lib.name")) {
            isolated.remove(key);
        }
        Path javaTemp = Files.createDirectory(this.directory.resolve("java-temp"));
        isolated.setProperty("java.io.tmpdir", javaTemp.toString());
        System.setProperties(isolated);
        try {
            runtime.start(bundles.stream().filter(bundle -> !bundle.getSymbolicName().equals("org.eclipse.kura.emulator")).toList());
            Bundle provider = runtime.bundle(PROVIDER);
            Path nativeDirectory = provider.getBundleContext().getDataFile("").toPath();
            assertEquals(nativeDirectory.toAbsolutePath().toString(), System.getProperty("org.sqlite.tmpdir"));
            assertFalse(runtime.hasService(CONTRACT, null), "The database requires configuration");
            try (var crypto = runtime.register("org.eclipse.kura.api", "org.eclipse.kura.crypto.CryptoService",
                    (proxy, method, args) -> switch (method.getName()) {
                        case "toString" -> "Unused crypto boundary for an in-memory database";
                        case "hashCode" -> System.identityHashCode(proxy);
                        case "equals" -> proxy == args[0];
                        default -> throw new AssertionError("Unexpected crypto call: " + method);
                    }, Map.of())) {
                runtime.configure(PID, Map.of("kura.service.pid", "native-placement-fixture", "db.mode", "IN_MEMORY"));
                try (var service = runtime.service(CONTRACT, "(service.pid=" + PID + ")", Duration.ofSeconds(5));
                        Connection connection = (Connection) service.call("getConnection");
                        var statement = connection.createStatement();
                        var result = statement.executeQuery("SELECT 42")) {
                    assertEquals(PROVIDER, service.provider().getSymbolicName());
                    assertTrue(result.next());
                    assertEquals(42, result.getInt(1));
                    assertEquals(Boolean.TRUE, runtime.bundle("org.xerial.sqlite-jdbc").loadClass("org.sqlite.SQLiteJDBCLoader")
                            .getMethod("isNativeMode").invoke(null));
                    assertEquals("org.xerial.sqlite-jdbc", runtime.packageProvider(PROVIDER, "org.sqlite"));
                    assertEquals("com.zaxxer.HikariCP", runtime.packageProvider(PROVIDER, "com.zaxxer.hikari"));
                    try (var extracted = Files.list(nativeDirectory)) {
                        assertTrue(extracted.anyMatch(path -> path.getFileName().toString().startsWith("sqlite-")
                                && !path.getFileName().toString().endsWith(".lck") && Files.isRegularFile(path)),
                                "A native library must actually be extracted into the bundle storage area");
                    }
                    try (var files = Files.list(javaTemp)) {
                        assertTrue(files.noneMatch(path -> path.getFileName().toString().startsWith("sqlite-")),
                                "The Java temporary directory must contain no SQLite native libraries");
                    }
                }
            }
        } finally {
            try {
                runtime.bundle(PROVIDER).stop();
                assertNull(System.getProperty("org.sqlite.tmpdir"), "The activator must clear its override on stop");
                assertFalse(runtime.hasService(CONTRACT, null));
            } finally {
                System.setProperties(original);
            }
        }
    }
}
