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
package com.eclipsesource.jaxrs.publisher.internal;

import org.osgi.framework.BundleContext;
import org.osgi.framework.ServiceReference;
import org.osgi.util.tracker.ServiceTracker;

import com.eclipsesource.jaxrs.publisher.ApplicationConfiguration;

/**
 * <p>
 * Tracker for OSGi Services implementing the {@link ApplicationConfiguration} interface.
 * </p>
 */
public class ApplicationConfigurationTracker extends ServiceTracker<Object, Object> {

    private final JAXRSConnector connector;

    ApplicationConfigurationTracker(BundleContext context, JAXRSConnector connector) {
        super(context, ApplicationConfiguration.class.getName(), null);
        this.connector = connector;
    }

    @Override
    public Object addingService(ServiceReference<Object> reference) {
        return this.connector.addApplicationConfiguration(reference);
    }

    @Override
    public void removedService(ServiceReference<Object> reference, Object service) {
        if (service instanceof ApplicationConfiguration) {
            this.connector.removeApplicationConfiguration(reference, (ApplicationConfiguration) service);
        }
    }
}
