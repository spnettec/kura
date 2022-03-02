/*******************************************************************************
 * Copyright (c) 2011,2015 Frank Appel and others.
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 * Contributors:
 *    Frank Appel - initial API and implementation
 *    Holger Staudacher - ongoing development
 *    ProSyst Software GmbH. - compatibility with OSGi specification 4.2 APIs
 ******************************************************************************/
package com.eclipsesource.jaxrs.publisher.internal;

import org.osgi.framework.BundleContext;
import org.osgi.framework.ServiceReference;
import org.osgi.service.http.HttpService;
import org.osgi.util.tracker.ServiceTracker;

public class HttpTracker extends ServiceTracker<Object, Object> {

    private final JAXRSConnector connector;

    HttpTracker(BundleContext context, JAXRSConnector connector) {
        super(context, HttpService.class.getName(), null);
        this.connector = connector;
    }

    @Override
    public Object addingService(ServiceReference<Object> reference) {
        return this.connector.addHttpService(reference);
    }

    @Override
    public void removedService(ServiceReference<Object> reference, Object service) {
        if (service instanceof HttpService) {
            this.connector.removeHttpService((HttpService) service);
        }
    }
}
