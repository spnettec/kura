/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.camel.core.osgi;

import java.io.BufferedInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URL;
import java.util.Optional;
import java.util.Properties;

import org.apache.camel.impl.engine.DefaultFactoryFinder;
import org.apache.camel.spi.ClassResolver;
import org.apache.camel.util.IOHelper;
import org.osgi.framework.Bundle;
import org.osgi.framework.BundleContext;

public class OsgiFactoryFinder extends DefaultFactoryFinder {

    private BundleContext bundleContext;

    public OsgiFactoryFinder(BundleContext bundleContext, ClassResolver classResolver, String resourcePath) {
        super(classResolver, resourcePath);
        this.bundleContext = bundleContext;
    }

    private static class BundleEntry {

        URL url;
        Bundle bundle;
    }

    @Override
    public Optional<Class<?>> findClass(String key) {
        final String classKey = key;

        Class<?> answer = addToClassMap(classKey, () -> {
            BundleEntry entry = getResource(key);
            if (entry != null) {
                URL url = entry.url;
                InputStream in = url.openStream();
                // lets load the file
                BufferedInputStream reader = null;
                try {
                    reader = IOHelper.buffered(in);
                    Properties properties = new Properties();
                    properties.load(reader);
                    String className = properties.getProperty("class");
                    if (className == null) {
                        throw new IOException("Expected property is missing: class");
                    }
                    return entry.bundle.loadClass(className);
                } finally {
                    IOHelper.close(reader, key, null);
                    IOHelper.close(in, key, null);
                }
            } else {
                Properties prop = doFindFactoryProperties(key);
                if (prop != null) {
                    return doNewInstance(prop, true).orElse(null);
                } else {
                    return null;
                }
            }
        });

        return Optional.ofNullable(answer);
    }

    // As the META-INF of the Factory could not be export,
    // we need to go through the bundles to look for it
    // NOTE, the first found factory will be return
    public BundleEntry getResource(String name) {
        BundleEntry entry = null;
        Bundle[] bundles;

        bundles = bundleContext.getBundles();

        URL url;
        for (Bundle bundle : bundles) {
            url = bundle.getEntry(getResourcePath() + name);
            if (url != null) {
                entry = new BundleEntry();
                entry.url = url;
                entry.bundle = bundle;
                break;
            }
        }

        return entry;
    }

    private Properties doFindFactoryProperties(String key) throws IOException {
        String uri = getResourcePath() + key;

        InputStream in = classResolver.loadResourceAsStream(uri);
        if (in == null) {
            return null;
        }

        // lets load the file
        BufferedInputStream reader = null;
        try {
            reader = IOHelper.buffered(in);
            Properties properties = new Properties();
            properties.load(reader);
            return properties;
        } finally {
            IOHelper.close(reader, key, null);
            IOHelper.close(in, key, null);
        }
    }

    private Optional<Class<?>> doNewInstance(Properties properties, boolean mandatory) throws IOException {
        String className = properties.getProperty("class");
        if (className == null && mandatory) {
            throw new IOException("Expected property is missing: class");
        } else if (className == null) {
            return Optional.empty();
        }

        Class<?> clazz = classResolver.resolveClass(className);
        return Optional.ofNullable(clazz);
    }
}
