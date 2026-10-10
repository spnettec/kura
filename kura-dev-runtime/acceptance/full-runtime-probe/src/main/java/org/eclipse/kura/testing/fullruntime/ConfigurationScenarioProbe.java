/* Copyright (c) 2026 Contributors to the Eclipse Foundation. SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.testing.fullruntime;

import java.lang.reflect.InvocationTargetException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;

import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.configuration.metatype.OCDService;
import org.eclipse.kura.system.SystemService;
import org.osgi.framework.Bundle;
import org.osgi.framework.BundleContext;
import org.osgi.framework.ServiceReference;

/** Invoke the unchanged upstream scenario in a fresh, complete acceptance application. */
final class ConfigurationScenarioProbe {
    private final List<ServiceReference<?>> references = new ArrayList<>();

    void run(BundleContext context, String name) throws Exception {
        Path home = Path.of(System.getProperty("kura.home")).toAbsolutePath().normalize();
        Path allowed = Path.of(System.getProperty("kura.acceptance.root")).toAbsolutePath().normalize();
        require(home.startsWith(allowed) && !home.equals(allowed), "Dedicated per-scenario home required");
        require(Files.isRegularFile(home.resolve(".configuration-acceptance-owned")), "Acceptance ownership marker required");
        Path result = home.resolve("configuration-scenario-result.json");
        Throwable failure = null;
        String evidence = "";
        try {
            require(context.getBundles().length >= 284, "Complete application plus fixtures required");
            SystemService system = service(context, SystemService.class);
            ConfigurationService configuration = service(context, ConfigurationService.class);
            OCDService ocd = service(context, OCDService.class);
            require(system.getClass().getName().equals("org.eclipse.kura.core.system.SystemServiceImpl"), "Production host SystemService required");
            require(owner(context, SystemService.class).equals("org.eclipse.kura.core.system"), "Production SystemService provider required");
            require(owner(context, ConfigurationService.class).equals("org.eclipse.kura.core.configuration"), "Production ConfigurationService provider required");
            require(Path.of(system.getKuraHome()).toAbsolutePath().normalize().equals(home), "Actual host home mismatch");
            require(Path.of(system.getKuraSnapshotsDirectory()).toAbsolutePath().normalize().startsWith(home), "Actual snapshots must be isolated");
            boolean encryption = Boolean.parseBoolean(system.getProperties().getProperty("kura.snapshots.encrypt", "true"));
            require(encryption != name.equals("testPlaintextSnapshotRetainsEmbeddedXml"), "Scenario snapshot encryption mode mismatch");
            Set<String> fixturePids = Set.of("org.eclipse.kura.core.configuration.CfgSvcTestComponent",
                    "org.eclipse.kura.core.configuration.CfgSvcTestSelfComponent");
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(15);
            while (!configuration.getConfigurableComponentPids().containsAll(fixturePids)
                    && System.nanoTime() < deadline) {
                Thread.sleep(25);
            }
            require(configuration.getConfigurableComponentPids().containsAll(fixturePids), "Actual SCR fixtures must arrive");
            Bundle fixture = null;
            for (Bundle bundle : context.getBundles()) {
                if ("org.eclipse.kura.testing.configuration.fixtures".equals(bundle.getSymbolicName())) {
                    fixture = bundle;
                    break;
                }
            }
            require(fixture != null && fixture.getState() == Bundle.ACTIVE, "Active upstream scenario fixture required");
            Class<?> scenarios = fixture.loadClass("org.eclipse.kura.testing.configuration.fixture.ConfigurationServiceScenarios");
            Object instance = scenarios.getConstructor(ConfigurationService.class, OCDService.class, SystemService.class)
                    .newInstance(configuration, ocd, system);
            scenarios.getMethod("prepare").invoke(instance);
            scenarios.getMethod(name).invoke(instance);
            evidence = ",\"bundleCount\":" + context.getBundles().length
                    + ",\"systemProvider\":\"org.eclipse.kura.core.system\""
                    + ",\"systemImplementation\":\"org.eclipse.kura.core.system.SystemServiceImpl\""
                    + ",\"configurationProvider\":\"org.eclipse.kura.core.configuration\""
                    + ",\"snapshotsEncrypted\":" + encryption;
        } catch (InvocationTargetException e) {
            failure = e.getCause();
        } catch (Throwable e) {
            failure = e;
        } finally {
            for (ServiceReference<?> reference : references) {
                context.ungetService(reference);
            }
        }
        Files.writeString(result, "{\"scenario\":" + quote(name) + ",\"passed\":" + (failure == null)
                + ",\"home\":" + quote(home.toString()) + evidence
                + (failure == null ? "" : ",\"error\":" + quote(failure.toString())) + "}\n");
        if (failure != null) {
            failure.printStackTrace();
            throw new IllegalStateException("Complete application configuration scenario failed: " + name, failure);
        }
        System.out.println("CONFIGURATION_SCENARIO_PASS " + name);
    }

    private <T> T service(BundleContext context, Class<T> type) throws InterruptedException {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(15);
        do {
            ServiceReference<T> reference = context.getServiceReference(type);
            if (reference != null) {
                T service = context.getService(reference);
                if (service != null) {
                    references.add(reference);
                    return service;
                }
            }
            Thread.sleep(25);
        } while (System.nanoTime() < deadline);
        throw new IllegalStateException("Missing actual service " + type.getName());
    }

    private static String owner(BundleContext context, Class<?> type) {
        return context.getServiceReference(type).getBundle().getSymbolicName();
    }

    private static void require(boolean condition, String message) {
        if (!condition) {
            throw new IllegalStateException(message);
        }
    }

    private static String quote(String value) {
        return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r") + "\"";
    }
}
