/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.keystore;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

import org.eclipse.kura.core.testutil.TestUtil;
import org.eclipse.kura.crypto.CryptoService;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.osgi.service.component.ComponentContext;

@Timeout(10)
class FilesystemKeystoreLifecycleTest {
    @TempDir
    Path directory;

    @ParameterizedTest
    @ValueSource(booleans = { false, true })
    void shouldStopPasswordUpdaterOnDeactivation(boolean randomizePassword) throws Exception {
        FilesystemKeystoreServiceImpl service = new FilesystemKeystoreServiceImpl();
        CryptoService crypto = mock(CryptoService.class);
        when(crypto.encryptAes(any(char[].class))).thenAnswer(call -> call.getArgument(0));
        when(crypto.decryptAes(any(char[].class))).thenAnswer(call -> call.getArgument(0));
        service.setCryptoService(crypto);
        ScheduledExecutorService executor = null;
        try {
            service.activate(mock(ComponentContext.class), Map.of("kura.service.pid", "lifecycle.test",
                    "keystore.path", this.directory.resolve("store.p12").toString(), "keystore.password", "changeit",
                    "randomize.password", randomizePassword, "crl.management.enabled", false));
            executor = (ScheduledExecutorService) TestUtil.getFieldValue(service, "selfUpdaterExecutor");
            ScheduledFuture<?> task = (ScheduledFuture<?>) TestUtil.getFieldValue(service, "selfUpdaterFuture");
            if (randomizePassword) {
                assertNotNull(task, "Activation must schedule the pending password configuration update");
                assertFalse(task.isDone());
            }
            service.deactivate();
            if (task != null) {
                assertTrue(task.isCancelled());
            }
            assertTrue(executor.isShutdown(), "Deactivation must release its owned password updater");
            assertTrue(executor.awaitTermination(2, TimeUnit.SECONDS));
        } finally {
            // Preserve bounded cleanup even when demonstrating the pre-fix leak.
            if (executor != null) {
                executor.shutdownNow();
                assertTrue(executor.awaitTermination(2, TimeUnit.SECONDS));
            }
        }
    }
}
