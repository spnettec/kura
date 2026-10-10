/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.rest.keystore.provider;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.nio.file.Path;
import java.util.Hashtable;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import org.eclipse.kura.internal.rest.keystore.util.KeystoreRemoteService;
import org.eclipse.kura.security.keystore.KeystoreService;
import org.eclipse.osgi.launch.EquinoxFactory;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.osgi.framework.*;
import org.osgi.framework.launch.Framework;
import org.osgi.service.component.ComponentContext;

@Timeout(15)
class KeystoreTrackerLifecycleTest {
    @TempDir Path storage;

    @ParameterizedTest
    @ValueSource(ints = { 0, 2 })
    void shouldReleaseTrackedKeystoreAfterPropertyUpdates(int modifications) throws Exception {
        Framework framework = new EquinoxFactory().newFramework(Map.of(Constants.FRAMEWORK_STORAGE, this.storage.toString()));
        framework.start();
        BundleContext registry = framework.getBundleContext();
        KeystoreRemoteService endpoint = new KeystoreRemoteService();
        ComponentContext context = mock(ComponentContext.class);
        when(context.getBundleContext()).thenReturn(registry);
        KeystoreService service = mock(KeystoreService.class);
        AtomicInteger releases = new AtomicInteger();
        ServiceRegistration<KeystoreService> registration = registry.registerService(KeystoreService.class,
                new ServiceFactory<KeystoreService>() {
                    @Override
                    public KeystoreService getService(Bundle bundle, ServiceRegistration<KeystoreService> reference) {
                        return service;
                    }
                    @Override
                    public void ungetService(Bundle bundle, ServiceRegistration<KeystoreService> reference,
                            KeystoreService instance) {
                        assertSame(service, instance);
                        releases.incrementAndGet();
                    }
                }, new Hashtable<>(Map.of("kura.service.pid", "tracked.store")));
        try {
            endpoint.activate(context);
            assertNotNull(registration.getReference().getUsingBundles());
            for (int i = 0; i < modifications; i++) {
                registration.setProperties(new Hashtable<>(Map.of("kura.service.pid", "tracked.store", "revision", i)));
            }
            endpoint.deactivate(context);
            assertEquals(1, releases.get(), "Tracker close must release its acquired OSGi service use");
            assertNull(registration.getReference().getUsingBundles());
        } finally {
            endpoint.deactivate(context);
            registration.unregister();
            framework.stop();
            assertEquals(FrameworkEvent.STOPPED, framework.waitForStop(5000).getType());
        }
    }
}
