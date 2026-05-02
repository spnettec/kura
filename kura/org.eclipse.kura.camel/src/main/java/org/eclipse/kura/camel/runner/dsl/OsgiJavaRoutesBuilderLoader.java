/*******************************************************************************
 * Copyright (c) 2026 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.camel.runner.dsl;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URL;
import java.net.URLClassLoader;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.List;

import org.apache.camel.CamelContext;
import org.apache.camel.builder.RouteBuilder;
import org.apache.camel.dsl.java.joor.JavaRoutesBuilderLoader;
import org.apache.camel.spi.CamelBeanPostProcessor;
import org.apache.camel.spi.CompilePostProcessor;
import org.apache.camel.support.PluginHelper;
import org.osgi.framework.Bundle;
import org.osgi.framework.FrameworkUtil;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Camel-java-joor-dsl was designed for app-classpath runtimes. In OSGi the
 * camel jars are inside the bundle's {@code lib/} as embedded jars; the JDK
 * compiler that joor invokes can't reach them, so user routes that import
 * camel classes fail with "package org.apache.camel.builder does not exist".
 *
 * <p>This subclass materializes the embedded {@code lib/*.jar} entries to the
 * bundle data area on first use and exposes them via a {@link URLClassLoader}.
 * Camel's MultiCompile then scrapes those URLs to build the {@code -classpath}
 * option for the underlying javac invocation.
 */
public class OsgiJavaRoutesBuilderLoader extends JavaRoutesBuilderLoader {

    private static final Logger logger = LoggerFactory.getLogger(OsgiJavaRoutesBuilderLoader.class);

    @Override
    protected void doBuild() throws Exception {
        super.doBuild();
        // Camel's JavaRoutesBuilderLoader runs bean post-processing only for
        // non-RouteBuilder pojos, so @BindToRegistry methods on a user
        // RouteBuilder are silently dropped. camel-main / spring-boot
        // post-process all RoutesBuilders via their runtime; in Kura we have
        // to do it ourselves. Hook a post-compile step that bean-post-
        // processes RouteBuilders after they're instantiated.
        addCompilePostProcessor(new RouteBuilderBeanPostProcessor());
    }

    private static final class RouteBuilderBeanPostProcessor implements CompilePostProcessor {
        @Override
        public void postCompile(CamelContext context, String name, Class<?> clazz, byte[] byteCode,
                Object instance) throws Exception {
            if (!(instance instanceof RouteBuilder)) {
                return;
            }
            CamelBeanPostProcessor bpp = PluginHelper.getBeanPostProcessor(context);
            if (bpp != null) {
                bpp.postProcessBeforeInitialization(instance, instance.getClass().getName());
                bpp.postProcessAfterInitialization(instance, instance.getClass().getName());
            }
        }
    }

    @Override
    protected ClassLoader resolveParentClassLoader() {
        final ClassLoader parent = super.resolveParentClassLoader();
        final Bundle bundle = FrameworkUtil.getBundle(JavaRoutesBuilderLoader.class);
        if (bundle == null) {
            return parent;
        }
        final File storage = bundle.getBundleContext().getDataFile("joor-libs");
        if (storage == null) {
            return parent;
        }
        if (!storage.isDirectory() && !storage.mkdirs()) {
            logger.warn("Cannot create joor-libs storage at {}", storage);
            return parent;
        }

        final List<URL> urls = new ArrayList<>();
        final Enumeration<URL> entries = bundle.findEntries("lib", "*.jar", false);
        while (entries != null && entries.hasMoreElements()) {
            final URL entry = entries.nextElement();
            final String path = entry.getPath();
            final int slash = path.lastIndexOf('/');
            final String name = slash >= 0 ? path.substring(slash + 1) : path;
            final File target = new File(storage, name);
            try {
                if (!target.exists() || target.length() == 0) {
                    try (InputStream is = entry.openStream();
                            OutputStream os = new FileOutputStream(target)) {
                        is.transferTo(os);
                    }
                }
                urls.add(target.toURI().toURL());
            } catch (Exception e) {
                logger.warn("Failed to materialize {} for joor compile classpath", entry, e);
            }
        }

        if (urls.isEmpty()) {
            return parent;
        }
        logger.debug("Built joor compile classpath with {} jars at {}", urls.size(), storage);
        return new URLClassLoader(urls.toArray(new URL[0]), parent);
    }
}
