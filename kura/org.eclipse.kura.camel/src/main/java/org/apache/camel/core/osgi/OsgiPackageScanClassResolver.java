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
package org.apache.camel.core.osgi;

import java.lang.reflect.Method;
import java.net.URL;
import java.util.Enumeration;
import java.util.LinkedHashSet;
import java.util.Set;

import org.apache.camel.core.osgi.utils.BundleDelegatingClassLoader;
import org.apache.camel.spi.PackageScanFilter;
import org.apache.camel.support.scan.DefaultPackageScanClassResolver;
import org.osgi.framework.Bundle;
import org.osgi.framework.BundleContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class OsgiPackageScanClassResolver extends DefaultPackageScanClassResolver {

    private static final Logger LOG = LoggerFactory.getLogger(OsgiPackageScanClassResolver.class);

    private final Bundle bundle;

    public OsgiPackageScanClassResolver(BundleContext context) {
        this(context.getBundle());
    }

    public OsgiPackageScanClassResolver(Bundle bundle) {
        this.bundle = bundle;
        // add the BundleDelegatingClassLoader to the class loaders
        addClassLoader(new BundleDelegatingClassLoader(bundle));
    }

    @Override
    public void find(PackageScanFilter test, String packageName, Set<Class<?>> classes) {
        super.find(test, packageName, classes);
        packageName = packageName.replace('.', '/');
        // remember the number of classes found so far
        int classesSize = classes.size();
        // look in osgi bundles
        loadImplementationsInBundle(test, packageName, classes);
        // if we did not find any new, then fallback to use regular non bundle class loading
        if (classes.size() == classesSize) {
            // Using the non-OSGi classloaders as a fallback
            // this is necessary when use JBI packaging for servicemix-camel SU
            // so that we get chance to use SU classloader to scan packages in the SU
            LOG.trace("Cannot find any classes in bundles, not trying regular classloaders scanning: {}", packageName);
            for (ClassLoader classLoader : super.getClassLoaders()) {
                if (!isOsgiClassloader(classLoader)) {
                    find(test, packageName, classLoader, classes);
                }
            }
        }
    }

    private static boolean isOsgiClassloader(ClassLoader loader) {
        try {
            Method mth = loader.getClass().getMethod("getBundle", new Class[] {});
            if (mth != null) {
                return true;
            }
        } catch (NoSuchMethodException e) {
            // ignore its not an osgi loader
        }
        return false;
    }

    private void loadImplementationsInBundle(PackageScanFilter test, String packageName, Set<Class<?>> classes) {
        Set<String> urls = getImplementationsInBundle(test, packageName);
        if (urls != null) {
            for (String url : urls) {
                // substring to avoid leading slashes
                addIfMatching(test, url, classes);
            }
        }
    }

    private Set<String> getImplementationsInBundle(PackageScanFilter test, String packageName) {
        Bundle[] bundles;
        if (bundle.getBundleContext() != null) {
            bundles = bundle.getBundleContext().getBundles();
        } else {
            bundles = new Bundle[] { bundle };
        }
        Set<String> urls = new LinkedHashSet<>();
        for (Bundle bd : bundles) {
            LOG.trace("Searching in bundle: {}", bd);
            try {
                Enumeration<URL> paths = bd.findEntries("/" + packageName, "*.class", true);
                while (paths != null && paths.hasMoreElements()) {
                    URL path = paths.nextElement();
                    String pathString = path.getPath();
                    String urlString = pathString.substring(pathString.indexOf(packageName));
                    urls.add(urlString);
                    LOG.trace("Added url: {}", urlString);
                }
            } catch (Throwable t) {
                LOG.warn("Cannot search in bundle: " + bundle + " for classes matching criteria: " + test + " due: "
                        + t.getMessage() + ". This exception will be ignored.", t);
            }
        }
        return urls;
    }

}
