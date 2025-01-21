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
package org.apache.camel.core.osgi.utils;

import java.io.IOException;
import java.net.URL;
import java.util.Enumeration;

import org.osgi.framework.Bundle;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * A ClassLoader delegating to a given OSGi bundle.
 *
 */
public class BundleDelegatingClassLoader extends ClassLoader {

    private static final Logger LOG = LoggerFactory.getLogger(BundleDelegatingClassLoader.class);
    private final Bundle bundle;
    private final ClassLoader classLoader;

    public BundleDelegatingClassLoader(Bundle bundle) {
        this(bundle, null);
    }

    public BundleDelegatingClassLoader(Bundle bundle, ClassLoader classLoader) {
        this.bundle = bundle;
        this.classLoader = classLoader;
    }

    @Override
    protected Class<?> findClass(String name) throws ClassNotFoundException {
        LOG.trace("FindClass: {}", name);
        return bundle.loadClass(name);
    }

    @Override
    protected URL findResource(String name) {
        LOG.trace("FindResource: {}", name);
        URL resource = bundle.getResource(name);
        if (classLoader != null && resource == null) {
            resource = classLoader.getResource(name);
        }
        return resource;
    }

    @Override
    @SuppressWarnings({ "unchecked", "rawtypes" })
    protected Enumeration findResources(String name) throws IOException {
        LOG.trace("FindResource: {}", name);
        return bundle.getResources(name);
    }

    @Override
    protected Class<?> loadClass(String name, boolean resolve) throws ClassNotFoundException {
        LOG.trace("LoadClass: {}, resolve: {}", name, resolve);
        Class<?> clazz;
        try {
            clazz = findClass(name);
        } catch (ClassNotFoundException cnfe) {
            if (classLoader != null) {
                try {
                    clazz = classLoader.loadClass(name);
                } catch (ClassNotFoundException e) {
                    throw new ClassNotFoundException(
                            name + " from bundle " + bundle.getBundleId() + " (" + bundle.getSymbolicName() + ")",
                            cnfe);
                }
            } else {
                throw new ClassNotFoundException(
                        name + " from bundle " + bundle.getBundleId() + " (" + bundle.getSymbolicName() + ")", cnfe);
            }
        }
        if (resolve) {
            resolveClass(clazz);
        }
        return clazz;
    }

    public Bundle getBundle() {
        return bundle;
    }

    @Override
    public String toString() {
        return String.format("BundleDelegatingClassLoader(%s)", bundle);
    }
}
