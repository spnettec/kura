/* Copyright (c) 2025, 2026 Eurotech and contributors. SPDX-License-Identifier: EPL-2.0 */
package ${package}.test;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.eclipse.kura.testing.osgi.EquinoxExtension;
import org.eclipse.kura.testing.osgi.EquinoxRuntime;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.osgi.framework.Bundle;

/** Actual bundle loading, ConfigAdmin and SCR; no static DS latch or shared business classloader. */
@ExtendWith(EquinoxExtension.class)
class ExampleComponentIT {
    @Test
    void activatesOnlyAfterConfigurationAndRegistersConfiguredProperties(EquinoxRuntime runtime) throws Exception {
        List<Bundle> bundles = new ArrayList<>();
        try (var files = Files.list(Path.of("target/it-bundles"))) {
            for (Path path : files.filter(p -> p.toString().endsWith(".jar")).sorted().toList()) {
                bundles.add(runtime.install(path));
            }
        }
        runtime.resolve(bundles);
        // Core implementation bundles supply imported classes; only these services are activated.
        runtime.start(List.of(runtime.bundle("org.eclipse.equinox.cm"), runtime.bundle("org.apache.felix.scr"),
                runtime.bundle("${artifactId}.bundle")));
        String serviceName = "org.eclipse.kura.configuration.ConfigurableComponent";
        String pid = "${package}.ExampleComponent";
        String filter = "(kura.service.pid=" + pid + ")";
        assertFalse(runtime.hasService(serviceName, filter));
        runtime.configure(pid, Map.of("example.property", "from-real-configadmin"));
        try (var service = runtime.service(serviceName, filter, Duration.ofSeconds(5))) {
            assertEquals("from-real-configadmin", service.property("example.property"));
            assertEquals("org.eclipse.kura.api", runtime.packageProvider("${artifactId}.bundle", "org.eclipse.kura.configuration"));
        }
    }
}
