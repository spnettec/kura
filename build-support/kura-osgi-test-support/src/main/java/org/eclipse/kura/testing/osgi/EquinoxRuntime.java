/*
 * Copyright (c) 2026 Contributors to the Eclipse Foundation.
 * SPDX-License-Identifier: EPL-2.0
 */
package org.eclipse.kura.testing.osgi;

import java.io.IOException;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Proxy;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Hashtable;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.ServiceLoader;
import java.util.concurrent.TimeoutException;

import org.osgi.framework.Bundle;
import org.osgi.framework.BundleException;
import org.osgi.framework.Constants;
import org.osgi.framework.FrameworkEvent;
import org.osgi.framework.ServiceReference;
import org.osgi.framework.launch.Framework;
import org.osgi.framework.launch.FrameworkFactory;
import org.osgi.framework.namespace.PackageNamespace;
import org.osgi.framework.wiring.BundleRevision;
import org.osgi.framework.wiring.BundleWiring;
import org.osgi.framework.wiring.FrameworkWiring;

/** Real OSGi class loading. The controller never imports or exports business interfaces. */
public final class EquinoxRuntime implements AutoCloseable {
    private final Framework framework;
    private final Path directory;
    private final List<Service> services = new ArrayList<>();

    public EquinoxRuntime(Path directory) throws Exception {
        this.directory = directory;
        Files.createDirectories(directory);
        var properties = new LinkedHashMap<String, String>();
        properties.put(Constants.FRAMEWORK_STORAGE, directory.resolve("storage").toString());
        properties.put(Constants.FRAMEWORK_STORAGE_CLEAN, Constants.FRAMEWORK_STORAGE_CLEAN_ONFIRSTINIT);
        properties.put(Constants.FRAMEWORK_BUNDLE_PARENT, Constants.FRAMEWORK_BUNDLE_PARENT_FRAMEWORK);
        properties.put("osgi.console.enable.builtin", "false");
        this.framework = ServiceLoader.load(FrameworkFactory.class).findFirst().orElseThrow().newFramework(properties);
        this.framework.init();
        this.framework.start();
    }

    public Bundle install(Path jar) throws BundleException {
        if (!Files.isRegularFile(jar)) {
            throw new IllegalArgumentException("Missing bundle: " + jar);
        }
        return this.framework.getBundleContext().installBundle(jar.toUri().toString());
    }

    public void resolve(Collection<Bundle> bundles) throws Exception {
        if (!this.framework.adapt(FrameworkWiring.class).resolveBundles(bundles)) {
            diagnose("unresolved");
            throw new IllegalStateException("Unresolved bundles; see " + this.directory);
        }
    }

    public void start(Collection<Bundle> bundles) throws BundleException {
        for (Bundle bundle : bundles) {
            if ((bundle.adapt(BundleRevision.class).getTypes() & BundleRevision.TYPE_FRAGMENT) == 0) {
                bundle.start();
            }
        }
    }

    public Bundle bundle(String symbolicName) {
        for (Bundle bundle : this.framework.getBundleContext().getBundles()) {
            if (symbolicName.equals(bundle.getSymbolicName())) {
                return bundle;
            }
        }
        throw new IllegalArgumentException("Missing bundle " + symbolicName);
    }

    public Service service(String interfaceName, String filter, Duration timeout) throws Exception {
        long deadline = System.nanoTime() + timeout.toNanos();
        do {
            ServiceReference<?>[] references = this.framework.getBundleContext().getAllServiceReferences(interfaceName, filter);
            if (references != null) {
                for (ServiceReference<?> reference : references) {
                    Object instance = this.framework.getBundleContext().getService(reference);
                    if (instance != null) {
                        Service result = new Service(reference, instance, reference.getBundle().loadClass(interfaceName));
                        this.services.add(result);
                        return result;
                    }
                }
            }
            Thread.sleep(25);
        } while (System.nanoTime() < deadline);
        if (!timeout.isZero()) {
            diagnose("service-timeout");
        }
        throw new TimeoutException("Service not available: " + interfaceName + " " + filter);
    }

    public boolean hasService(String interfaceName, String filter) throws Exception {
        ServiceReference<?>[] refs = this.framework.getBundleContext().getAllServiceReferences(interfaceName, filter);
        return refs != null && refs.length > 0;
    }

    public void configure(String pid, Map<String, ?> properties) throws Exception {
        try (Service admin = service("org.osgi.service.cm.ConfigurationAdmin", null, Duration.ofSeconds(5))) {
            Object configuration = admin.call("getConfiguration", pid, null);
            Class<?> contract = admin.provider().loadClass("org.osgi.service.cm.Configuration");
            invoke(contract, configuration, "update", new Hashtable<>(properties));
        }
    }

    public AutoCloseable register(String apiBundle, String interfaceName, InvocationHandler handler, Map<String, ?> properties) throws Exception {
        Class<?> contract = bundle(apiBundle).loadClass(interfaceName);
        Object service = Proxy.newProxyInstance(contract.getClassLoader(), new Class<?>[] {contract}, handler);
        var registration = this.framework.getBundleContext().registerService(interfaceName, service, new Hashtable<>(properties));
        return registration::unregister;
    }

    public String packageProvider(String consumer, String packageName) {
        BundleWiring wiring = bundle(consumer).adapt(BundleWiring.class);
        if (wiring == null) {
            throw new IllegalStateException("Bundle is unresolved: " + consumer);
        }
        return wiring.getRequiredWires(PackageNamespace.PACKAGE_NAMESPACE).stream()
                .filter(wire -> packageName.equals(wire.getCapability().getAttributes().get(PackageNamespace.PACKAGE_NAMESPACE)))
                .map(wire -> wire.getProviderWiring().getBundle().getSymbolicName()).findFirst().orElseThrow();
    }

    /** Invoke using the interface loaded by its actual provider, never a controller-side business class. */
    public static Object invoke(Class<?> contract, Object receiver, String name, Object... arguments) throws Exception {
        List<Method> matches = new ArrayList<>();
        for (Method method : contract.getMethods()) {
            if (!method.getName().equals(name) || method.getParameterCount() != arguments.length) {
                continue;
            }
            boolean compatible = true;
            for (int index = 0; index < arguments.length; index++) {
                Class<?> parameter = method.getParameterTypes()[index];
                if (arguments[index] != null && !parameter.isInstance(arguments[index]) && !parameter.isPrimitive()) {
                    compatible = false;
                }
            }
            if (compatible) {
                matches.add(method);
            }
        }
        if (matches.size() != 1) {
            throw new IllegalArgumentException("Expected one matching method: " + contract.getName() + "." + name + ", found " + matches);
        }
        try {
            return matches.getFirst().invoke(receiver, arguments);
        } catch (InvocationTargetException exception) {
            if (exception.getCause() instanceof Exception cause) {
                throw cause;
            }
            throw exception;
        }
    }

    public Path diagnose(String reason) throws IOException {
        StringBuilder text = new StringBuilder("reason: " + reason + "\n");
        FrameworkWiring resolver = this.framework.adapt(FrameworkWiring.class);
        for (Bundle bundle : this.framework.getBundleContext().getBundles()) {
            text.append(bundle.getBundleId()).append(' ').append(bundle.getSymbolicName()).append(' ')
                    .append(bundle.getVersion()).append(" state=").append(bundle.getState()).append('\n');
            if (bundle.getState() == Bundle.INSTALLED) {
                for (var requirement : bundle.adapt(BundleRevision.class).getRequirements(null)) {
                    text.append("  requirement ").append(requirement).append(" candidates=")
                            .append(resolver.findProviders(requirement).size()).append('\n');
                }
            }
        }
        try (Service scr = service("org.osgi.service.component.runtime.ServiceComponentRuntime", null, Duration.ZERO)) {
            Collection<?> descriptions = (Collection<?>) scr.call("getComponentDescriptionDTOs", (Object) new Bundle[0]);
            for (Object description : descriptions) {
                text.append("DS ").append(description.getClass().getField("name").get(description))
                        .append(" policy=").append(description.getClass().getField("configurationPolicy").get(description)).append('\n');
                Collection<?> configurations = (Collection<?>) scr.call("getComponentConfigurationDTOs", description);
                for (Object configuration : configurations) {
                    text.append("  state=").append(configuration.getClass().getField("state").get(configuration));
                    Object[] references = (Object[]) configuration.getClass().getField("unsatisfiedReferences").get(configuration);
                    for (Object reference : references) {
                        text.append(" missing=").append(reference.getClass().getField("name").get(reference))
                                .append(" target=").append(reference.getClass().getField("target").get(reference));
                    }
                    text.append('\n');
                }
            }
        } catch (Exception exception) {
            text.append("SCR diagnostics: ").append(exception.getMessage()).append('\n');
        }
        return Files.writeString(this.directory.resolve(reason + ".txt"), text);
    }

    @Override
    public void close() throws Exception {
        for (Service service : List.copyOf(this.services)) {
            service.close();
        }
        this.framework.stop();
        FrameworkEvent event = this.framework.waitForStop(10_000);
        if (event.getType() == FrameworkEvent.WAIT_TIMEDOUT) {
            throw new TimeoutException("Equinox did not stop within 10 seconds: " + this.directory);
        }
    }

    public final class Service implements AutoCloseable {
        private final ServiceReference<?> reference;
        private final Object instance;
        private final Class<?> contract;
        private boolean closed;
        private Service(ServiceReference<?> reference, Object instance, Class<?> contract) {
            this.reference = reference;
            this.instance = instance;
            this.contract = contract;
        }
        public Object call(String method, Object... arguments) throws Exception {
            return invoke(this.contract, this.instance, method, arguments);
        }
        public Object property(String key) { return this.reference.getProperty(key); }
        public Bundle provider() { return this.reference.getBundle(); }
        public Class<?> contract() { return this.contract; }
        @Override
        public void close() {
            if (!this.closed) {
                this.closed = true;
                framework.getBundleContext().ungetService(this.reference);
                services.remove(this);
            }
        }
    }
}
