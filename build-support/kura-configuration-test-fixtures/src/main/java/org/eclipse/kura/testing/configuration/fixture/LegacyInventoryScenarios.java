/*******************************************************************************
 * Copyright (c) 2011, 2026 Eurotech and/or its affiliates and others
 * SPDX-License-Identifier: EPL-2.0
 * Contributors: Eurotech, Contributors to the Eclipse Foundation
 ******************************************************************************/
package org.eclipse.kura.testing.configuration.fixture;

import static org.junit.jupiter.api.Assertions.*;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.jar.Attributes;
import java.util.jar.JarEntry;
import java.util.jar.JarOutputStream;
import java.util.jar.Manifest;

import com.eclipsesource.json.Json;
import com.eclipsesource.json.JsonArray;
import com.eclipsesource.json.JsonObject;
import com.eclipsesource.json.JsonValue;

import org.osgi.framework.Bundle;
import org.osgi.framework.BundleContext;
import org.osgi.service.deploymentadmin.DeploymentAdmin;
import org.osgi.service.deploymentadmin.DeploymentPackage;

/** Uses Felix DeploymentAdmin and the real inventory/JSON services, within a disposable framework. */
public class LegacyInventoryScenarios extends LegacyCoreScenarios {
    private static final String PACKAGE_NAME = "org.eclipse.kura.testing.inventory";
    private static final String BUNDLE_NAME = PACKAGE_NAME + ".bundle";
    private static final String BUNDLE_VERSION = "1.0.0.test";
    private final DeploymentPackage deploymentPackage;
    private final Bundle installedBundle;

    public LegacyInventoryScenarios(BundleContext context) throws Exception {
        super(context);
        try {
            DeploymentAdmin admin = service(DeploymentAdmin.class, null);
            assertNull(admin.getDeploymentPackage(PACKAGE_NAME), "Each scenario needs its own framework");
            this.deploymentPackage = admin.installDeploymentPackage(new ByteArrayInputStream(deploymentPackageBytes()));
            assertNotNull(this.deploymentPackage);
            this.installedBundle = this.deploymentPackage.getBundle(BUNDLE_NAME);
            assertNotNull(this.installedBundle);
            assertEquals(Bundle.ACTIVE, this.installedBundle.getState());
        } catch (Exception | Error failure) {
            super.close();
            throw failure;
        }
    }

    public void testGetPackages() throws Exception {
        JsonArray packages = get("deploymentPackages").get("deploymentPackages").asArray();
        assertEquals(1, packages.size());
        JsonObject item = resource(packages, PACKAGE_NAME, null);
        assertEquals("1.0.0", item.getString("version", null));
        assertFalse(item.getBoolean("signed", true));
        JsonArray bundles = item.get("bundles").asArray();
        assertEquals(1, bundles.size());
        assertBundle(resource(bundles, BUNDLE_NAME, null));
    }

    public void testGetBundles() throws Exception {
        assertBundle(resource(get("bundles").get("bundles").asArray(), BUNDLE_NAME, null));
    }

    public void testGetInventory() throws Exception {
        JsonArray inventory = get("inventory").get("inventory").asArray();
        assertEquals(BUNDLE_VERSION, resource(inventory, BUNDLE_NAME, "BUNDLE").getString("version", null));
        assertEquals("1.0.0", resource(inventory, PACKAGE_NAME, "DP").getString("version", null));
        assertEquals("1.0", resource(inventory, "fixture-os-package", "DEB").getString("version", null));
    }

    public void testGetSystemPackages() throws Exception {
        JsonArray packages = get("systemPackages").get("systemPackages").asArray();
        assertEquals(1, packages.size());
        assertEquals("1.0", resource(packages, "fixture-os-package", "DEB").getString("version", null));
    }

    private void assertBundle(JsonObject item) {
        assertEquals(BUNDLE_VERSION, item.getString("version", null));
        assertEquals(this.installedBundle.getBundleId(), item.getLong("id", -1));
        assertEquals("ACTIVE", item.getString("state", null));
        assertFalse(item.getBoolean("signed", true));
    }

    private JsonObject get(String resource) throws Exception {
        byte[] body = call("INVENTORY-V1", "GET", List.of(resource), null);
        assertNotNull(body);
        return Json.parse(new String(body, StandardCharsets.UTF_8)).asObject();
    }

    private static JsonObject resource(JsonArray array, String name, String type) {
        for (JsonValue value : array) {
            JsonObject item = value.asObject();
            if (name.equals(item.getString("name", null)) && (type == null || type.equals(item.getString("type", null)))) {
                return item;
            }
        }
        return fail("Missing resource " + name + "/" + type + " in " + array);
    }

    private static byte[] deploymentPackageBytes() throws Exception {
        // An empty, startable test bundle replaces the historical precompiled HelloWorld artifact.
        Manifest bundle = new Manifest();
        Attributes attributes = bundle.getMainAttributes();
        attributes.putValue("Manifest-Version", "1.0");
        attributes.putValue("Bundle-ManifestVersion", "2");
        attributes.putValue("Bundle-SymbolicName", BUNDLE_NAME);
        attributes.putValue("Bundle-Version", BUNDLE_VERSION);
        ByteArrayOutputStream bundleBytes = new ByteArrayOutputStream();
        try (JarOutputStream jar = new JarOutputStream(bundleBytes, bundle)) {
            // Manifest-only bundle: no hardware, network or application activator.
        }
        String path = "bundles/fixture.jar";
        Manifest manifest = new Manifest();
        manifest.getMainAttributes().putValue("Manifest-Version", "1.0");
        manifest.getMainAttributes().putValue("DeploymentPackage-SymbolicName", PACKAGE_NAME);
        manifest.getMainAttributes().putValue("DeploymentPackage-Version", "1.0.0");
        Attributes bundleEntry = new Attributes();
        bundleEntry.putValue("Bundle-SymbolicName", BUNDLE_NAME);
        bundleEntry.putValue("Bundle-Version", BUNDLE_VERSION);
        manifest.getEntries().put(path, bundleEntry);
        ByteArrayOutputStream result = new ByteArrayOutputStream();
        try (JarOutputStream jar = new JarOutputStream(result, manifest)) {
            jar.putNextEntry(new JarEntry(path));
            jar.write(bundleBytes.toByteArray());
            jar.closeEntry();
        }
        return result.toByteArray();
    }

    @Override
    public void close() throws Exception {
        try {
            this.deploymentPackage.uninstall();
            assertEquals(Bundle.UNINSTALLED, this.installedBundle.getState());
        } finally {
            super.close();
        }
    }
}
