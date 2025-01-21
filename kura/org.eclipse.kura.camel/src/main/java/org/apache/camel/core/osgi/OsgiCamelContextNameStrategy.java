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

import static org.apache.camel.core.osgi.OsgiCamelContextPublisher.CONTEXT_NAME_PROPERTY;

import java.util.concurrent.atomic.AtomicInteger;

import org.apache.camel.spi.CamelContextNameStrategy;
import org.osgi.framework.BundleContext;

/**
 * In OSGi we want to use a {@link CamelContextNameStrategy} that finds a free name in the
 * OSGi Service Registry to be used for auto assigned names.
 * <p/>
 * If there is a name clash in the OSGi registry, then a new candidate name is used by appending
 * a unique counter.
 */
public class OsgiCamelContextNameStrategy implements CamelContextNameStrategy {

    private static final AtomicInteger CONTEXT_COUNTER = new AtomicInteger(0);
    private final BundleContext context;
    private final String prefix = "camel";
    private volatile String name;

    public OsgiCamelContextNameStrategy(BundleContext context) {
        this.context = context;
    }

    @Override
    public String getName() {
        if (name == null) {
            name = getNextName();
        }
        return name;
    }

    @Override
    public synchronized String getNextName() {
        // false = do no check fist, but add the counter asap, so we have camel-1
        return OsgiNamingHelper.findFreeCamelContextName(context, prefix, CONTEXT_NAME_PROPERTY, CONTEXT_COUNTER,
                false);
    }

    @Override
    public boolean isFixedName() {
        return false;
    }

}
