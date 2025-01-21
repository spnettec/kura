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

import javax.ws.rs.Path;
import javax.ws.rs.core.Feature;
import javax.ws.rs.ext.Provider;

import org.osgi.framework.BundleContext;
import org.osgi.framework.Filter;
import org.osgi.framework.ServiceReference;
import org.osgi.util.tracker.ServiceTracker;

public class ResourceTracker extends ServiceTracker<Object, Object> {

    private final BundleContext context;
    private final JAXRSConnector connector;

    public ResourceTracker(BundleContext context, Filter filter, JAXRSConnector connector) {
        super(context, filter, null);
        this.context = context;
        this.connector = connector;
    }

    @Override
    public Object addingService(ServiceReference<Object> reference) {
        Object service = this.context.getService(reference);
        return delegateAddService(reference, service);
    }

    private Object delegateAddService(ServiceReference<?> reference, Object service) {
        Object result;
        if (isResource(service)) {
            result = this.connector.addResource(reference);
        } else {
            this.context.ungetService(reference);
            result = null;
        }
        return result;
    }

    @Override
    public void removedService(ServiceReference<Object> reference, Object service) {
        this.connector.removeResource(service);
        this.context.ungetService(reference);
    }

    @Override
    public void modifiedService(ServiceReference<Object> reference, Object service) {
        this.connector.removeResource(service);
        delegateAddService(reference, service);
    }

    private boolean isResource(Object service) {
        return service != null && (hasRegisterableAnnotation(service) || service instanceof Feature);
    }

    private boolean hasRegisterableAnnotation(Object service) {
        boolean result = isRegisterableAnnotationPresent(service.getClass());
        if (!result) {
            Class<?>[] interfaces = service.getClass().getInterfaces();
            for (Class<?> type : interfaces) {
                result = result || isRegisterableAnnotationPresent(type);
            }
        }
        return result;
    }

    private boolean isRegisterableAnnotationPresent(Class<?> type) {
        return type.isAnnotationPresent(Path.class) || type.isAnnotationPresent(Provider.class);
    }
}
