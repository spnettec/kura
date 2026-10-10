/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.testing;

import static org.junit.jupiter.api.Assertions.*;

import java.lang.reflect.InvocationTargetException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.concurrent.TimeUnit;

import org.eclipse.kura.testing.osgi.EquinoxExtension;
import org.eclipse.kura.testing.osgi.EquinoxRuntime;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.osgi.framework.Bundle;
import org.osgi.framework.BundleContext;
import org.osgi.framework.ServiceReference;

/** Controller has no Kura business classes; scenarios execute inside the installed test bundle. */
@ExtendWith(EquinoxExtension.class)
@Timeout(value = 60, unit = TimeUnit.SECONDS)
class ConfigurationServiceRuntimeIT {
    private static final String FIXTURE = "org.eclipse.kura.testing.configuration.fixtures";
    private static final String SCENARIOS = "org.eclipse.kura.testing.configuration.fixture.ConfigurationServiceScenarios";
    private static final String CONFIGURATION = "org.eclipse.kura.configuration.ConfigurationService";
    private static final String OCD = "org.eclipse.kura.configuration.metatype.OCDService";
    private static final String SYSTEM = "org.eclipse.kura.system.SystemService";
    private static final String COMPONENT = "org.eclipse.kura.core.configuration.CfgSvcTestComponent";
    private static final String SELF_COMPONENT = "org.eclipse.kura.core.configuration.CfgSvcTestSelfComponent";
    private static final Set<String> RESOLVE_ONLY = Set.of("org.eclipse.kura.core", "org.eclipse.kura.core.inventory",
            "org.apache.felix.deploymentadmin", "org.eclipse.kura.emulator");

    @TempDir Path data;

    @ParameterizedTest(name = "{0}")
    @ValueSource(strings = {
        "testPlaintextSnapshotRetainsEmbeddedXml",
        "testGetFactoryComponentPids",
        "testCreateFactoryConfigurationNulls",
        "testCreateFactoryExistingPid",
        "testCreateFactoryConfigurationMergePropertiesAndSnapshot",
        "testCreateFactoryConfigurationWithDefaultPassword",
        "testCreateFactoryConfigurationWithCustomPassword",
        "testDeleteFactoryConfigurationNulls",
        "testDeleteFactoryConfigurationNonExistingFactoryPid",
        "testDeleteFactoryConfigurationWithSnapshot",
        "testGetConfigurableComponentPids",
        "testGetConfigurableComponentPidsAdd",
        "testGetComponentConfigurations",
        "testGetComponentConfigurationsFilterNonExistentPid",
        "testGetComponentConfigurationsFilterCofServicePid",
        "testGetComponentConfigurationsFilterExistentPid",
        "testGetComponentConfigurationNull",
        "testGetComponentConfiguration",
        "testGetDefaultComponentConfigurationNull",
        "testGetDefaultComponentConfigurationNonExisting",
        "testGetDefaultComponentConfiguration",
        "testGetDefaultComponentConfigurationExisting",
        "testGetDefaultSelfConfiguringComponentConfigurationExisting",
        "testUpdateConfigurationPidPropertiesNull",
        "testUpdateConfigurationPidPropertiesNullProps",
        "testUpdateConfigurationPidPropertiesEmptyProps",
        "testUpdateConfigurationPidPropertiesValid",
        "testUpdateConfigurationPidPropertiesInvalid",
        "testUpdateConfigurationPidPropertiesNoSnapshot",
        "testUpdateConfigurationsConfigs",
        "testSnapshot",
        "testRollbackEmpty",
        "testRollbackNotSaved",
        "testRollback",
        "testRollbackId",
        "testRollbackShouldDeleteFactoryComponent",
        "testRollbackShouldCreateFactoryComponent",
        "testEncryptSnapshots",
        "testShouldGetFactoryComponentDefinitions",
        "testShouldGetServiceProviderDefinitions",
        "testUpdateKeepsThePasswordTypeInTheSnapshot",
        "testUpdateDoesNotAlterAnUntouchedPasswordProperty",
        "testUpdateKeepsThePasswordTypeOfAPropertyTheMetatypeDoesNotDeclare",
        "testRollbackKeepsThePasswordTypeOfAPropertyTheMetatypeDoesNotDeclare",
        "testRollbackDropsThePasswordTypeWhenTheTargetSnapshotHoldsAPlainString",
        "testRollbackRestoresThePreviousPasswordValueAndType",
        "testRollbackToIdRestoresThePasswordOfThatSnapshot"
    })
    void upstreamConfigurationScenario(String name, EquinoxRuntime runtime) throws Exception {
        assertThrows(ClassNotFoundException.class, () -> Class.forName(CONFIGURATION));
        List<Bundle> bundles = new ArrayList<>();
        for (String directory : List.of("target/it-bundles", "target/config-it-bundles")) {
            try (var paths = Files.list(Path.of(directory))) {
                for (Path jar : paths.filter(path -> path.toString().endsWith(".jar")).sorted().toList()) {
                    bundles.add(runtime.install(jar));
                }
            }
        }
        runtime.resolve(bundles);
        assertEquals("org.eclipse.kura.api", runtime.packageProvider(FIXTURE, "org.eclipse.kura.configuration"));
        assertEquals("org.eclipse.kura.core.configuration",
                runtime.packageProvider(FIXTURE, "org.eclipse.kura.core.configuration"));
        assertEquals("junit-jupiter-api", runtime.packageProvider(FIXTURE, "org.junit.jupiter.api"));
        Files.createDirectories(data.resolve("snapshots"));
        Properties properties = new Properties();
        properties.setProperty("kura.snapshots.encrypt", name.equals("testPlaintextSnapshotRetainsEmbeddedXml") ? "false" : "true");
        try (var system = runtime.register("org.eclipse.kura.api", SYSTEM, (proxy, method, arguments) ->
                switch (method.getName()) {
                    case "hashCode" -> System.identityHashCode(proxy);
                    case "equals" -> proxy == arguments[0];
                    case "toString" -> "isolated configuration system paths";
                    case "getKuraDataDirectory" -> data.toString();
                    case "getKuraSnapshotsDirectory" -> data.resolve("snapshots").toString();
                    case "getKuraSnapshotsCount" -> 10;
                    case "getProperties" -> properties;
                    default -> null;
                }, Map.of("service.ranking", Integer.MAX_VALUE))) {
            runtime.start(bundles.stream().filter(bundle -> !RESOLVE_ONLY.contains(bundle.getSymbolicName())).toList());
            try (var configuration = runtime.service(CONFIGURATION, null, Duration.ofSeconds(10))) {
                long deadline = System.nanoTime() + Duration.ofSeconds(8).toNanos();
                while (!((Set<?>) configuration.call("getConfigurableComponentPids")).containsAll(Set.of(COMPONENT, SELF_COMPONENT))
                        && System.nanoTime() < deadline) {
                    Thread.sleep(25);
                }
                assertTrue(((Set<?>) configuration.call("getConfigurableComponentPids"))
                        .containsAll(Set.of(COMPONENT, SELF_COMPONENT)), "SCR fixture components must activate: " + configuration.call("getConfigurableComponentPids"));
                invokeScenario(runtime.bundle(FIXTURE), name);
            } catch (Exception | Error failure) {
                runtime.diagnose("configuration-scenario-failure");
                throw failure;
            }
        }
    }

    private static void invokeScenario(Bundle fixture, String name) throws Exception {
        BundleContext context = fixture.getBundleContext();
        List<ServiceReference<?>> references = new ArrayList<>();
        try {
            List<Object> services = new ArrayList<>();
            List<Class<?>> contracts = new ArrayList<>();
            for (String contract : List.of(CONFIGURATION, OCD, SYSTEM)) {
                ServiceReference<?> reference = context.getServiceReference(contract);
                assertNotNull(reference, contract);
                references.add(reference);
                Object service = context.getService(reference);
                assertNotNull(service, contract);
                services.add(service);
                contracts.add(fixture.loadClass(contract));
            }
            Class<?> scenarios = fixture.loadClass(SCENARIOS);
            Object scenario = scenarios.getConstructor(contracts.toArray(Class<?>[]::new)).newInstance(services.toArray());
            scenarios.getMethod("prepare").invoke(scenario);
            scenarios.getMethod(name).invoke(scenario);
        } catch (InvocationTargetException e) {
            if (e.getCause() instanceof Error error) { throw error; }
            if (e.getCause() instanceof Exception exception) { throw exception; }
            throw e;
        } finally {
            for (ServiceReference<?> reference : references) { context.ungetService(reference); }
        }
    }
}
