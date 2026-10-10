/* Copyright (c) 2026 Contributors to the Eclipse Foundation. SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.testing.fullruntime;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Hashtable;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import org.eclipse.kura.configuration.ConfigurableComponent;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.configuration.metatype.OCD;
import org.eclipse.kura.system.SystemService;
import org.eclipse.kura.wire.graph.MultiportWireConfiguration;
import org.eclipse.kura.wire.graph.WireComponentConfiguration;
import org.eclipse.kura.wire.graph.WireGraphConfiguration;
import org.eclipse.kura.wire.graph.WireGraphService;
import org.osgi.framework.BundleActivator;
import org.osgi.framework.BundleContext;
import org.osgi.framework.ServiceReference;
import org.osgi.service.event.Event;
import org.osgi.service.event.EventAdmin;
import org.osgi.service.event.EventHandler;
import org.osgi.service.wireadmin.WireAdmin;

/** Business acceptance inside a complete, isolated development application. */
public final class FullRuntimeProbe implements BundleActivator {
    private static final String FACTORY = "org.eclipse.kura.core.configuration.TestFactoryComponent";
    private final List<ServiceReference<?>> references = new ArrayList<>();

    @Override
    public void start(BundleContext context) throws Exception {
        String scenario = System.getProperty("kura.acceptance.configuration.scenario");
        if (scenario != null) {
            new ConfigurationScenarioProbe().run(context, scenario);
            return;
        }
        Path home = Path.of(System.getProperty("kura.home")).toAbsolutePath().normalize();
        Path result = home.resolve("full-runtime-probe-result.json");
        String pid = "acceptance.mac.full." + UUID.randomUUID();
        ConfigurationService configuration = null;
        boolean created = false;
        String evidence = "";
        Exception failure = null;
        try {
            require(context.getBundles().length >= 277, "Complete application bundle set is required");
            SystemService system = service(context, SystemService.class);
            require(owner(context, SystemService.class).equals("org.eclipse.kura.core.system"), "Production SystemService owner");
            require(system.getClass().getName().equals("org.eclipse.kura.core.system.SystemServiceImpl"), "Production SystemService implementation");
            require(Path.of(system.getKuraHome()).toAbsolutePath().normalize().equals(home), "Actual Kura home");
            Path snapshots = Path.of(system.getKuraSnapshotsDirectory()).toAbsolutePath().normalize();
            require(snapshots.startsWith(home), "Isolated actual snapshot directory");
            configuration = service(context, ConfigurationService.class);
            require(owner(context, ConfigurationService.class).equals("org.eclipse.kura.core.configuration"), "Production configuration owner");
            String selfPid = "org.eclipse.kura.core.configuration.CfgSvcTestSelfComponent";
            require(selfPid.equals(configuration.getComponentConfiguration(selfPid).getPid()), "Actual self-configuring fixture read");
            require(Integer.valueOf(1).equals(configuration.getComponentConfiguration(
                    "org.eclipse.kura.core.configuration.CfgSvcTestComponent").getConfigurationProperties().get("field.test")),
                    "Actual singleton fixture defaults");
            require(configuration.getFactoryComponentPids().contains(FACTORY), "Upstream fixture factory must arrive through SCR");
            configuration.createFactoryConfiguration(FACTORY, pid, Map.of("field.test", 1), true);
            created = true;
            String filter = "(kura.service.pid=" + pid + ")";
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
            while (context.getServiceReferences(ConfigurableComponent.class, filter).isEmpty()
                    && System.nanoTime() < deadline) {
                Thread.sleep(25);
            }
            require(!context.getServiceReferences(ConfigurableComponent.class, filter).isEmpty(), "Actual factory SCR instance");
            String xml = "<probe>one & two</probe>";
            configuration.updateConfiguration(pid, Map.of("field.test", 2, "payload.xml", xml), false);
            Map<String, Object> properties = configuration.getComponentConfiguration(pid).getConfigurationProperties();
            require(Integer.valueOf(2).equals(properties.get("field.test")), "Configuration integer update");
            require(xml.equals(properties.get("payload.xml")), "Embedded XML retained");
            require(properties.get("password.test") instanceof Password, "Default password type retained");
            long snapshot = configuration.snapshot();
            Path file = snapshots.resolve("snapshot_" + snapshot + ".xml");
            require(Files.isRegularFile(file), "Snapshot written through actual SystemService path");
            boolean plaintext = !Boolean.parseBoolean(system.getProperties().getProperty("kura.snapshots.encrypt", "true"));
            if (plaintext) {
                String text = Files.readString(file);
                require(text.contains(pid) && text.contains("<![CDATA[" + xml + "]]>"), "YOFC plaintext snapshot CDATA");
            }
            EventAdmin events = service(context, EventAdmin.class);
            CountDownLatch received = new CountDownLatch(1);
            String topic = "org/eclipse/kura/testing/fullruntime/" + UUID.randomUUID();
            Hashtable<String, Object> eventProperties = new Hashtable<>();
            eventProperties.put("event.topics", topic);
            var registration = context.registerService(EventHandler.class,
                    event -> { if (pid.equals(event.getProperty("nonce"))) { received.countDown(); } }, eventProperties);
            try {
                events.postEvent(new Event(topic, Map.of("nonce", pid)));
                require(received.await(5, TimeUnit.SECONDS), "Actual full application EventAdmin delivery");
            } finally {
                registration.unregister();
            }
            long deliveries = verifyWireRoute(context, configuration, home, pid);
            evidence = "\"bundleCount\":" + context.getBundles().length + ",\"systemProvider\":"
                    + quote(owner(context, SystemService.class)) + ",\"systemImplementation\":" + quote(system.getClass().getName())
                    + ",\"configurationProvider\":" + quote(owner(context, ConfigurationService.class))
                    + ",\"eventProvider\":" + quote(owner(context, EventAdmin.class)) + ",\"snapshotId\":" + snapshot
                    + ",\"plaintextSnapshot\":" + plaintext + ",\"wireDeliveries\":" + deliveries
                    + ",\"singletonAndSelfConfigurationRead\":true";
        } catch (Exception e) {
            failure = e;
        } finally {
            if (created) {
                try {
                    configuration.deleteFactoryConfiguration(pid, true);
                    require(!configuration.getConfigurableComponentPids().contains(pid), "Owned factory configuration cleanup");
                } catch (Exception cleanup) {
                    if (failure == null) { failure = cleanup; } else { failure.addSuppressed(cleanup); }
                }
            }
            for (ServiceReference<?> reference : references) { context.ungetService(reference); }
        }
        if (failure != null) {
            Files.writeString(result, "{\"passed\":false,\"error\":" + quote(failure.toString()) + "}\n");
            throw failure;
        }
        Files.writeString(result, "{\"passed\":true,\"home\":" + quote(home.toString()) + "," + evidence
                + ",\"factoryCreatedUpdatedDeleted\":true,\"eventDelivered\":true}\n");
        System.out.println("FULL_RUNTIME_PROBE_PASS " + result);
    }

    private long verifyWireRoute(BundleContext context, ConfigurationService configuration, Path home, String pid)
            throws Exception {
        WireGraphService graph = service(context, WireGraphService.class);
        WireAdmin admin = service(context, WireAdmin.class);
        WireGraphConfiguration before = graph.get();
        require(before.getWireComponentConfigurations().isEmpty() && before.getWireConfigurations().isEmpty(),
                "Acceptance profile requires an empty initial graph");
        String timer = pid + ".timer";
        String logger = pid + ".logger";
        var timerConfiguration = component(configuration, "org.eclipse.kura.wire.Timer", timer,
                Map.of("type", "SIMPLE", "simple.interval", 1, "simple.time.unit", "SECONDS"));
        var loggerConfiguration = component(configuration, "org.eclipse.kura.wire.Logger", logger,
                Map.of("log.verbosity", "QUIET"));
        try {
            graph.update(new WireGraphConfiguration(List.of(
                    new WireComponentConfiguration(timerConfiguration, Map.of("inputPortCount", 0, "outputPortCount", 1)),
                    new WireComponentConfiguration(loggerConfiguration, Map.of("inputPortCount", 1, "outputPortCount", 0))),
                    List.of(new MultiportWireConfiguration(timer, logger, 0, 0))));
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(12);
            long deliveries = 0;
            Path log = home.resolve("logs/kura.log");
            while (System.nanoTime() < deadline) {
                if (Files.isRegularFile(log)) {
                    try (var lines = Files.lines(log)) {
                        // WireEnvelope keeps the generated SCR service.pid. The timer thread carries kura.service.pid.
                        deliveries = lines.filter(line -> line.contains("WiresTimer_" + timer + "_")
                                && line.contains("Received WireEnvelope from ")).count();
                    }
                }
                if (deliveries >= 3) { break; }
                Thread.sleep(100);
            }
            require(deliveries >= 3, "Actual production Logger must consume three Timer envelopes");
            require(admin.getWires(null) != null && admin.getWires(null).length == 1, "Actual WireAdmin route");
            return deliveries;
        } finally {
            graph.update(before);
            require(graph.get().getWireComponentConfigurations().isEmpty() && graph.get().getWireConfigurations().isEmpty(),
                    "Wire graph cleanup");
            require(admin.getWires(null) == null || admin.getWires(null).length == 0, "WireAdmin cleanup");
            require(!configuration.getConfigurableComponentPids().contains(timer)
                    && !configuration.getConfigurableComponentPids().contains(logger), "Owned Wire component cleanup");
        }
    }

    private static ComponentConfiguration component(ConfigurationService configuration, String factory, String pid,
            Map<String, Object> overrides) throws Exception {
        ComponentConfiguration defaults = configuration.getDefaultComponentConfiguration(factory);
        Map<String, Object> properties = new HashMap<>(defaults.getConfigurationProperties());
        properties.putAll(overrides);
        properties.put("service.factoryPid", factory);
        properties.put("kura.service.pid", pid);
        return new ComponentConfiguration() {
            public String getPid() { return pid; }
            public OCD getDefinition() { return defaults.getDefinition(); }
            public OCD getLocalizedDefinition(String locale) { return defaults.getLocalizedDefinition(locale); }
            public Map<String, Object> getConfigurationProperties() { return properties; }
        };
    }

    private <T> T service(BundleContext context, Class<T> type) {
        ServiceReference<T> reference = context.getServiceReference(type);
        require(reference != null, "Missing service " + type.getName());
        references.add(reference);
        T service = context.getService(reference);
        require(service != null, "Unavailable service " + type.getName());
        return service;
    }

    private static String owner(BundleContext context, Class<?> type) {
        return context.getServiceReference(type).getBundle().getSymbolicName();
    }

    private static void require(boolean condition, String message) {
        if (!condition) { throw new IllegalStateException(message); }
    }

    private static String quote(String value) {
        return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r") + "\"";
    }

    @Override
    public void stop(BundleContext context) { }
}
