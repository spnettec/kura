/*******************************************************************************
 * Copyright (c) 2018, 2026 Red Hat Inc and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Red Hat Inc
 *******************************************************************************/

package org.eclipse.kura.osgi;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.util.Hashtable;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.jar.Attributes;
import java.util.jar.JarOutputStream;
import java.util.jar.Manifest;

import org.eclipse.kura.util.osgi.BundleUtil;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.osgi.framework.Bundle;
import org.osgi.framework.Constants;

class BundleUtilTest extends EquinoxTestBase {

    private Bundle first;
    private Bundle second;

    @BeforeEach
    void registerServices() throws Exception {
        this.first = install("test.first");
        this.second = install("test.second");
        this.first.getBundleContext().registerService(Runnable.class, () -> { },
                new Hashtable<>(Map.of(Constants.SERVICE_PID, "first")));
        this.second.getBundleContext().registerService(Callable.class, () -> "second",
                new Hashtable<>(Map.of(Constants.SERVICE_PID, "second")));
    }

    @Test
    void shouldReturnNoBundleWithWrongProperty() {
        assertEquals(Set.of(), BundleUtil.getBundles(this.context, new Class<?>[] { Runnable.class },
                Map.of(Constants.SERVICE_PID, "missing")));
    }

    @Test
    void shouldReturnOnlyBundleWithRightProperty() {
        assertEquals(Set.of(this.first), BundleUtil.getBundles(this.context,
                new Class<?>[] { Runnable.class, Callable.class }, Map.of(Constants.SERVICE_PID, "first")));
    }

    @Test
    void shouldReturnManyBundlesByHeader() {
        assertEquals(Set.of(this.first, this.second),
                BundleUtil.getBundles(this.context, Map.of(Constants.BUNDLE_VENDOR, "Kura Test Fixtures")));
    }

    private Bundle install(String symbolicName) throws Exception {
        Manifest manifest = new Manifest();
        Attributes headers = manifest.getMainAttributes();
        headers.putValue("Manifest-Version", "1.0");
        headers.putValue(Constants.BUNDLE_MANIFESTVERSION, "2");
        headers.putValue(Constants.BUNDLE_SYMBOLICNAME, symbolicName);
        headers.putValue(Constants.BUNDLE_VERSION, "1.0.0");
        headers.putValue(Constants.BUNDLE_VENDOR, "Kura Test Fixtures");
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (JarOutputStream jar = new JarOutputStream(bytes, manifest)) {
            jar.finish();
        }
        Bundle result = this.context.installBundle(symbolicName, new ByteArrayInputStream(bytes.toByteArray()));
        result.start();
        return result;
    }
}
