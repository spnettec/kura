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

import org.apache.camel.CamelContext;
import org.apache.camel.RuntimeCamelException;
import org.apache.camel.impl.engine.DefaultLanguageResolver;
import org.apache.camel.spi.Language;
import org.apache.camel.spi.LanguageResolver;
import org.apache.camel.support.ResolverHelper;
import org.osgi.framework.BundleContext;
import org.osgi.framework.InvalidSyntaxException;
import org.osgi.framework.ServiceReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class OsgiLanguageResolver extends DefaultLanguageResolver {

    private static final Logger LOG = LoggerFactory.getLogger(OsgiLanguageResolver.class);

    private final BundleContext bundleContext;

    public OsgiLanguageResolver(BundleContext bundleContext) {
        this.bundleContext = bundleContext;
    }

    @Override
    public Language resolveLanguage(String name, CamelContext context) {
        // lookup in registry first
        Language lang = ResolverHelper.lookupLanguageInRegistryWithFallback(context, name);
        if (lang != null) {
            return lang;
        }

        lang = getLanguage(name, context);
        if (lang != null) {
            return lang;
        }
        LanguageResolver resolver = getLanguageResolver("default", context);
        if (resolver != null) {
            return resolver.resolveLanguage(name, context);
        }
        return super.resolveLanguage(name, context);
    }

    protected Language getLanguage(String name, CamelContext context) {
        LOG.trace("Finding Language: {}", name);
        try {
            ServiceReference<?>[] refs = bundleContext.getServiceReferences(LanguageResolver.class.getName(),
                    "(language=" + name + ")");
            if (refs != null) {
                for (ServiceReference<?> ref : refs) {
                    Object service = bundleContext.getService(ref);
                    if (LanguageResolver.class.isAssignableFrom(service.getClass())) {
                        LanguageResolver resolver = (LanguageResolver) service;
                        return resolver.resolveLanguage(name, context);
                    }
                }
            }

            return null;
        } catch (InvalidSyntaxException e) {
            throw RuntimeCamelException.wrapRuntimeCamelException(e);
        }
    }

    protected LanguageResolver getLanguageResolver(String name, CamelContext context) {
        LOG.trace("Finding LanguageResolver: {}", name);
        try {
            ServiceReference<?>[] refs = bundleContext.getServiceReferences(LanguageResolver.class.getName(),
                    "(resolver=" + name + ")");
            if (refs != null) {
                for (ServiceReference<?> ref : refs) {
                    Object service = bundleContext.getService(ref);
                    if (LanguageResolver.class.isAssignableFrom(service.getClass())) {
                        LanguageResolver resolver = (LanguageResolver) service;
                        return resolver;
                    }
                }
            }
            return null;
        } catch (InvalidSyntaxException e) {
            throw RuntimeCamelException.wrapRuntimeCamelException(e);
        }
    }

}
