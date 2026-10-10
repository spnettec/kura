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
import org.eclipse.kura.testing.osgi.EquinoxExtension;
import org.eclipse.kura.testing.osgi.EquinoxRuntime;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.extension.ExtendWith;
import org.osgi.framework.Bundle;

/** Retains the sole active legacy CommTest scenario without enabling serial hardware tests. */
@ExtendWith(EquinoxExtension.class)
@Timeout(30)
class CommServiceRuntimeIT {
    @Test
    void testServiceExists(EquinoxRuntime runtime) throws Exception {
        String contract = "org.eclipse.kura.comm.CommConnectionFactory";
        String provider = "org.eclipse.kura.core.comm";
        assertThrows(ClassNotFoundException.class, () -> Class.forName(contract));
        List<Bundle> bundles = new ArrayList<>();
        for (String directory : List.of("target/it-bundles", "target/comm-it-bundles")) {
            try (var paths = Files.list(Path.of(directory))) {
                for (Path jar : paths.filter(path -> path.toString().endsWith(".jar")).sorted().toList()) {
                    bundles.add(runtime.install(jar));
                }
            }
        }
        runtime.resolve(bundles);
        runtime.start(bundles);
        try (var service = runtime.service(contract,
                "(service.pid=org.eclipse.kura.core.comm.CommConnectionFactory)", Duration.ofSeconds(5))) {
            assertEquals(provider, service.provider().getSymbolicName());
            assertEquals(Bundle.ACTIVE, service.provider().getState());
            assertSame(runtime.bundle("org.eclipse.kura.api").loadClass(contract), service.contract());
            assertEquals("org.eclipse.kura.api", runtime.packageProvider(provider, "org.eclipse.kura.comm"));
            assertEquals("com.fazecast.jSerialComm", runtime.packageProvider(provider, "com.fazecast.jSerialComm"));
        }
    }
}
