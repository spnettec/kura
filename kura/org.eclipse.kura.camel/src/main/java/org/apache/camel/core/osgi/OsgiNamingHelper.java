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

import java.util.concurrent.atomic.AtomicInteger;

import org.apache.camel.CamelContext;
import org.osgi.framework.BundleContext;
import org.osgi.framework.InvalidSyntaxException;
import org.osgi.framework.ServiceReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * A helper to find free names in the OSGi service registry.
 */
public final class OsgiNamingHelper {

    private static final Logger LOG = LoggerFactory.getLogger(OsgiNamingHelper.class);

    private OsgiNamingHelper() {
    }

    /**
     * Checks the OSGi service registry for a free name (uses the counter if there is a clash to find next free name)
     *
     * @param context
     *                       the bundle context
     * @param prefix
     *                       the prefix for the name
     * @param key
     *                       the key to use in the OSGi filter; either
     *                       {@link OsgiCamelContextPublisher#CONTEXT_NAME_PROPERTY}
     *                       or {@link OsgiCamelContextPublisher#CONTEXT_MANAGEMENT_NAME_PROPERTY}.
     * @param counter
     *                       the counter
     * @param checkFirst
     *                       <tt>true</tt> to check the prefix name as-is before using the counter, <tt>false</tt> the
     *                       counter is
     *                       used immediately
     * @return the free name, is never <tt>null</tt>
     */
    public static String findFreeCamelContextName(BundleContext context, String prefix, String key,
            AtomicInteger counter, boolean checkFirst) {
        String candidate = null;
        boolean clash = false;

        do {
            try {
                clash = false;

                if (candidate == null && checkFirst) {
                    // try candidate as-is
                    candidate = prefix;
                } else {
                    // generate new candidate
                    candidate = prefix + "-" + getNextCounter(counter);
                }
                LOG.trace("Checking OSGi Service Registry for existence of existing CamelContext with name: {}",
                        candidate);

                ServiceReference<?>[] refs = context.getServiceReferences(CamelContext.class.getName(),
                        "(" + key + "=" + candidate + ")");
                if (refs != null && refs.length > 0) {
                    for (ServiceReference<?> ref : refs) {
                        Object id = ref.getProperty(key);
                        if (id != null && candidate.equals(id)) {
                            clash = true;
                            break;
                        }
                    }
                }
            } catch (InvalidSyntaxException e) {
                LOG.debug("Error finding free Camel name in OSGi Service Registry due " + e.getMessage()
                        + ". This exception is ignored.", e);
                break;
            }
        } while (clash);

        LOG.debug("Generated free name for bundle id: {}, clash: {} -> {}", context.getBundle().getBundleId(), clash,
                candidate);
        return candidate;
    }

    public static int getNextCounter(AtomicInteger counter) {
        // we want to start counting from 1, so increment first
        return counter.incrementAndGet();
    }

}
