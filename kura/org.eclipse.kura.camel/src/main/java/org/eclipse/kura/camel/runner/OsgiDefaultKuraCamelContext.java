/*******************************************************************************
 * Copyright (c) 2021, 2025 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 ******************************************************************************/
package org.eclipse.kura.camel.runner;

import org.apache.camel.TypeConverter;
import org.apache.camel.core.osgi.OsgiBeanRepository;
import org.apache.camel.core.osgi.OsgiCamelContextHelper;
import org.apache.camel.core.osgi.OsgiTypeConverter;
import org.apache.camel.core.osgi.utils.BundleContextUtils;
import org.apache.camel.core.osgi.utils.BundleDelegatingClassLoader;
import org.apache.camel.dsl.java.joor.JavaRoutesBuilderLoader;
import org.apache.camel.impl.DefaultCamelContext;
import org.apache.camel.spi.BeanRepository;
import org.apache.camel.support.DefaultRegistry;
import org.eclipse.kura.camel.runner.dsl.OsgiJavaRoutesBuilderLoader;
import org.osgi.framework.BundleContext;

public class OsgiDefaultKuraCamelContext extends DefaultCamelContext {

    private final BundleContext bundleContext;

    public OsgiDefaultKuraCamelContext(BundleContext bundleContext, BeanRepository registry) {
        super(false);

        // remove the OnCamelContextLifecycleStrategy that camel-core adds by default which does not work well for OSGi
        getLifecycleStrategies()
                .removeIf(l -> l.getClass().getSimpleName().contains("OnCamelContextLifecycleStrategy"));

        this.bundleContext = bundleContext;

        // inject common osgi
        OsgiCamelContextHelper.osgiUpdate(this, bundleContext);

        // and these are blueprint specific
        OsgiBeanRepository repo1 = new OsgiBeanRepository(bundleContext);
        getCamelContextExtension().setRegistry(new DefaultRegistry(repo1, registry));
        // Need to clean up the OSGi service when camel context is closed.
        addLifecycleStrategy(repo1);
        // setup the application context classloader with the bundle classloader
        setApplicationContextClassLoader(new BundleDelegatingClassLoader(bundleContext.getBundle()));

        // bind an OSGi-aware java DSL loader so camel-java-joor-dsl can compile
        // user routes against the camel jars embedded in this bundle. build()
        // runs JavaRoutesBuilderLoader.doBuild() which wires the internal
        // JavaJoorClassLoader; without it compileResources NPEs on first call.
        OsgiJavaRoutesBuilderLoader javaLoader = new OsgiJavaRoutesBuilderLoader();
        javaLoader.setCamelContext(this);
        javaLoader.build();
        getRegistry().bind("routes-builder-loader-" + JavaRoutesBuilderLoader.EXTENSION, javaLoader);

        init();
    }

    @Override
    protected TypeConverter createTypeConverter() {
        // CAMEL-3614: make sure we use a bundle context which imports org.apache.camel.impl.converter package
        BundleContext ctx = BundleContextUtils.getBundleContext(getClass());
        if (ctx == null) {
            ctx = bundleContext;
        }
        return new OsgiTypeConverter(ctx, this, getInjector());
    }
}
