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

import org.apache.camel.impl.DefaultCamelContext;
import org.apache.camel.util.ObjectHelper;
import org.osgi.framework.BundleContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public final class OsgiCamelContextHelper {

    private static final Logger LOG = LoggerFactory.getLogger(OsgiCamelContextHelper.class);

    private OsgiCamelContextHelper() {
        // helper class
    }

    public static void osgiUpdate(DefaultCamelContext camelContext, BundleContext bundleContext) {
        ObjectHelper.notNull(bundleContext, "BundleContext");

        LOG.debug("Using OsgiCamelContextNameStrategy");
        camelContext.setNameStrategy(new OsgiCamelContextNameStrategy(bundleContext));
        LOG.debug("Using OsgiManagementNameStrategy");
        camelContext.setManagementNameStrategy(new OsgiManagementNameStrategy(camelContext, bundleContext));
        LOG.debug("Using OsgiClassResolver");
        camelContext.setClassResolver(new OsgiClassResolver(camelContext, bundleContext));
        LOG.debug("Using OsgiFactoryFinderResolver");
        camelContext.setFactoryFinderResolver(new OsgiFactoryFinderResolver(bundleContext));
        LOG.debug("Using OsgiPackageScanClassResolver");
        camelContext.setPackageScanClassResolver(new OsgiPackageScanClassResolver(bundleContext));
        LOG.debug("Using OsgiComponentResolver");
        camelContext.setComponentResolver(new OsgiComponentResolver(bundleContext));
        LOG.debug("Using OsgiLanguageResolver");
        camelContext.setLanguageResolver(new OsgiLanguageResolver(bundleContext));
        LOG.debug("Using OsgiDataFormatResolver");
        camelContext.setDataFormatResolver(new OsgiDataFormatResolver(bundleContext));
    }

}
