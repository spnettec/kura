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

import org.apache.camel.spi.ClassResolver;
import org.apache.camel.spi.FactoryFinder;
import org.apache.camel.spi.FactoryFinderResolver;
import org.osgi.framework.BundleContext;

public class OsgiFactoryFinderResolver implements FactoryFinderResolver {

    private final BundleContext bundleContext;

    public OsgiFactoryFinderResolver(BundleContext bundleContext) {
        this.bundleContext = bundleContext;
    }

    @Override
    public FactoryFinder resolveFactoryFinder(ClassResolver classResolver, String resourcePath) {
        return new OsgiFactoryFinder(bundleContext, classResolver, resourcePath);
    }

    @Override
    public FactoryFinder resolveBootstrapFactoryFinder(ClassResolver classResolver, String resourcePath) {
        return new OsgiFactoryFinder(bundleContext, classResolver, resourcePath);
    }

}
