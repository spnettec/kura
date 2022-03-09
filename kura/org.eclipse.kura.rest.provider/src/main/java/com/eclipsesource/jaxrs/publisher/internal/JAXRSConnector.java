/*******************************************************************************
 * Copyright (c) 2012,2015 EclipseSource and others.
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 * Contributors:
 *    Holger Staudacher - initial API and implementation
 *    ProSyst Software GmbH. - compatibility with OSGi specification 4.2 APIs
 *    Ivan Iliev - Performance Optimizations
 ******************************************************************************/
package com.eclipsesource.jaxrs.publisher.internal;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.osgi.framework.BundleContext;
import org.osgi.framework.ServiceReference;
import org.osgi.service.http.HttpService;

import com.eclipsesource.jaxrs.publisher.ApplicationConfiguration;
import com.eclipsesource.jaxrs.publisher.ServletConfiguration;
import com.eclipsesource.jaxrs.publisher.internal.ServiceContainer.ServiceHolder;

public class JAXRSConnector {

    private static final String HTTP_SERVICE_PORT_PROPERTY = "org.osgi.service.http.port";
    private static final String RESOURCE_HTTP_PORT_PROPERTY = "http.port";
    private static final String DEFAULT_HTTP_PORT = "80";

    private final Object lock = new Object();
    private final ServiceContainer httpServices;
    private final ServiceContainer resources;
    private final Map<HttpService, JerseyContext> contextMap;
    private final BundleContext bundleContext;
    private final List<ServiceHolder> resourceCache;
    private ServletConfiguration servletConfiguration;
    private final ServiceContainer applicationConfigurations;
    private Configuration configuration;

    JAXRSConnector(BundleContext bundleContext) {
        this.bundleContext = bundleContext;
        this.configuration = new Configuration();
        this.httpServices = new ServiceContainer(bundleContext);
        this.resources = new ServiceContainer(bundleContext);
        this.contextMap = new HashMap<>();
        this.resourceCache = new ArrayList<>();
        this.applicationConfigurations = new ServiceContainer(bundleContext);
    }

    void updateConfiguration(Configuration configuration) {
        synchronized (this.lock) {
            this.configuration = configuration;
            doUpdateConfiguration(configuration);
        }
    }

    HttpService addHttpService(ServiceReference<?> reference) {
        synchronized (this.lock) {
            return doAddHttpService(reference);
        }
    }

    ServletConfiguration setServletConfiguration(ServiceReference<?> reference) {
        if (this.servletConfiguration == null) {
            this.servletConfiguration = (ServletConfiguration) this.bundleContext.getService(reference);
            doUpdateServletConfiguration();
            return this.servletConfiguration;
        }
        return null;
    }

    void unsetServletConfiguration(ServiceReference<?> reference, ServletConfiguration service) {
        if (this.servletConfiguration == service) {
            this.servletConfiguration = null;
            this.bundleContext.ungetService(reference);
            doUpdateServletConfiguration();
        }
    }

    ApplicationConfiguration addApplicationConfiguration(ServiceReference<?> reference) {
        synchronized (this.lock) {
            ApplicationConfiguration service = (ApplicationConfiguration) this.applicationConfigurations.add(reference)
                    .getService();
            doUpdateAppConfiguration();
            return service;
        }
    }

    void removeApplicationConfiguration(ServiceReference<?> reference, ApplicationConfiguration service) {
        synchronized (this.lock) {
            this.applicationConfigurations.remove(service);
            doUpdateAppConfiguration();
        }
    }

    private void doUpdateServletConfiguration() {
        ServiceHolder[] services = this.httpServices.getServices();
        for (ServiceHolder serviceHolder : services) {
            this.contextMap.get(serviceHolder.getService()).updateServletConfiguration(this.servletConfiguration);
        }
    }

    private void doUpdateAppConfiguration() {
        ServiceHolder[] services = this.httpServices.getServices();
        for (ServiceHolder serviceHolder : services) {
            this.contextMap.get(serviceHolder.getService()).updateAppConfiguration(this.applicationConfigurations);
        }
    }

    private void doUpdateConfiguration(Configuration configuration) {
        ServiceHolder[] services = this.httpServices.getServices();
        for (ServiceHolder serviceHolder : services) {
            this.contextMap.get(serviceHolder.getService()).updateConfiguration(configuration);
        }
    }

    HttpService doAddHttpService(ServiceReference<?> reference) {
        ServiceHolder serviceHolder = this.httpServices.add(reference);
        HttpService service = (HttpService) serviceHolder.getService();
        this.contextMap.put(service, createJerseyContext(service, this.configuration, this.servletConfiguration));
        clearCache();
        return service;
    }

    private void clearCache() {
        List<ServiceHolder> cache = new ArrayList<>(this.resourceCache);
        this.resourceCache.clear();
        for (ServiceHolder serviceHolder : cache) {
            registerResource(serviceHolder);
        }
    }

    void removeHttpService(HttpService service) {
        synchronized (this.lock) {
            doRemoveHttpService(service);
        }
    }

    void doRemoveHttpService(HttpService service) {
        JerseyContext context = this.contextMap.remove(service);
        if (context != null) {
            cacheFreedResources(context);
        }
        this.httpServices.remove(service);
    }

    private void cacheFreedResources(JerseyContext context) {
        List<Object> freeResources = context.eliminate();
        for (Object resource : freeResources) {
            this.resourceCache.add(this.resources.find(resource));
        }
    }

    Object addResource(ServiceReference<?> reference) {
        synchronized (this.lock) {
            return doAddResource(reference);
        }
    }

    private Object doAddResource(ServiceReference<?> reference) {
        ServiceHolder serviceHolder = this.resources.add(reference);
        registerResource(serviceHolder);
        return serviceHolder.getService();
    }

    private void registerResource(ServiceHolder serviceHolder) {
        Object port = getPort(serviceHolder);
        registerResource(serviceHolder, port);
    }

    private Object getPort(ServiceHolder serviceHolder) {
        Object port = serviceHolder.getReference().getProperty(RESOURCE_HTTP_PORT_PROPERTY);
        if (port == null) {
            port = this.bundleContext.getProperty(HTTP_SERVICE_PORT_PROPERTY);
            if (port == null) {
                port = DEFAULT_HTTP_PORT;
            }
        }
        return port;
    }

    private void registerResource(ServiceHolder serviceHolder, Object port) {
        HttpService service = findHttpServiceForPort(port);
        if (service != null) {
            JerseyContext jerseyContext = this.contextMap.get(service);
            jerseyContext.addResource(serviceHolder.getService());
        } else {
            cacheResource(serviceHolder);
        }
    }

    private void cacheResource(ServiceHolder serviceHolder) {
        this.resourceCache.add(serviceHolder);
    }

    private HttpService findHttpServiceForPort(Object port) {
        ServiceHolder[] serviceHolders = this.httpServices.getServices();
        HttpService result = null;
        for (ServiceHolder serviceHolder : serviceHolders) {
            Object servicePort = getPort(serviceHolder);
            if (servicePort.equals(port)) {
                result = (HttpService) serviceHolder.getService();
            }
        }
        return result;
    }

    void removeResource(Object resource) {
        synchronized (this.lock) {
            doRemoveResource(resource);
        }
    }

    private void doRemoveResource(Object resource) {
        ServiceHolder serviceHolder = this.resources.find(resource);
        this.resourceCache.remove(serviceHolder);
        HttpService httpService = findHttpServiceForPort(getPort(serviceHolder));
        removeResourcesFromContext(resource, httpService);
        this.resources.remove(resource);
    }

    private void removeResourcesFromContext(Object resource, HttpService httpService) {
        JerseyContext jerseyContext = this.contextMap.get(httpService);
        if (jerseyContext != null) {
            jerseyContext.removeResource(resource);
        }
    }

    // For testing purpose
    JerseyContext createJerseyContext(HttpService service, Configuration configuration,
            ServletConfiguration servletConfiguration) {
        return new JerseyContext(service, configuration, servletConfiguration, this.applicationConfigurations);
    }
}
