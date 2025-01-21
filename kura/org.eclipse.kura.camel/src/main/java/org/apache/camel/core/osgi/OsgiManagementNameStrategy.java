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
import org.apache.camel.impl.engine.DefaultManagementNameStrategy;
import org.osgi.framework.BundleContext;

/**
 * OSGi enhanced {@link org.apache.camel.spi.ManagementNameStrategy}.
 * <p/>
 * This {@link org.apache.camel.spi.ManagementNameStrategy} supports the default
 * tokens (see {@link DefaultManagementNameStrategy}) and the following additional OSGi specific tokens
 * <ul>
 * <li>#bundleId# - The bundle id</li>
 * <li>#version# - The bundle version</li>
 * <li>#symbolicName# - The bundle symbolic name</li>
 * </ul>
 * <p/>
 * This implementation will by default use a name pattern as <tt>#symbolicName#</tt> and in case
 * of a clash (such as multiple versions of the same symbolicName),
 * then the pattern will fallback to append an unique counter <tt>#symbolicName#-#counter#</tt>.
 *
 * @see DefaultManagementNameStrategy
 */
public class OsgiManagementNameStrategy extends DefaultManagementNameStrategy {

    private static final AtomicInteger CONTEXT_COUNTER = new AtomicInteger(0);
    private final BundleContext bundleContext;

    public OsgiManagementNameStrategy(CamelContext camelContext, BundleContext bundleContext) {
        super(camelContext, "#symbolicName#-#name#", "#symbolicName#-#name#-#counter#");
        this.bundleContext = bundleContext;
    }

    @Override
    protected String customResolveManagementName(String pattern, String answer) {
        String bundleId = "" + bundleContext.getBundle().getBundleId();
        String symbolicName = bundleContext.getBundle().getSymbolicName();
        if (symbolicName == null) {
            symbolicName = "";
        }
        String version = bundleContext.getBundle().getVersion().toString();

        answer = answer.replace("#bundleId#", bundleId);
        answer = answer.replace("#symbolicName#", symbolicName);
        answer = answer.replace("#version#", version);

        // we got a candidate then find a free name
        // true = check fist if the candidate as-is is free, if not then use the counter
        answer = OsgiNamingHelper.findFreeCamelContextName(bundleContext, answer,
                OsgiCamelContextPublisher.CONTEXT_MANAGEMENT_NAME_PROPERTY, CONTEXT_COUNTER, true);

        return answer;
    }

}
