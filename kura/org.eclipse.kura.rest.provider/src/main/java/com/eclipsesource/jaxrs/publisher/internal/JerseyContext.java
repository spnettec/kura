/*******************************************************************************
 * Copyright (c) 2012,2015 EclipseSource and others.
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 * Contributors:
 *    Holger Staudacher - initial API and implementation
 *    Dragos Dascalita  - disbaled autodiscovery
 *    Lars Pfannenschmidt  - made WADL generation configurable
 *    Ivan Iliev - added ServletConfiguration handling, Optimized Performance
 ******************************************************************************/
package com.eclipsesource.jaxrs.publisher.internal;

import java.util.ArrayList;
import java.util.Dictionary;
import java.util.List;
import java.util.Map;

import javax.servlet.ServletException;
import javax.ws.rs.core.Application;

import org.osgi.service.http.HttpContext;
import org.osgi.service.http.HttpService;
import org.osgi.service.http.NamespaceException;

import com.eclipsesource.jaxrs.publisher.ApplicationConfiguration;
import com.eclipsesource.jaxrs.publisher.ServletConfiguration;
import com.eclipsesource.jaxrs.publisher.internal.ServiceContainer.ServiceHolder;

@SuppressWarnings("rawtypes")
public class JerseyContext {

    private final RootApplication application;
    private final HttpService httpService;
    private final ServletContainerBridge servletContainerBridge;
    private final ResourcePublisher resourcePublisher;
    private volatile boolean isApplicationRegistered;
    private ServletConfiguration servletConfiguration;
    private String rootPath;
    private ServiceContainer applicationConfigurations;

    public JerseyContext(HttpService httpService, Configuration configuration,
            ServletConfiguration servletConfiguration, ServiceContainer applicationConfigurations) {
        this.httpService = httpService;
        this.rootPath = configuration.getRoothPath();
        this.application = new RootApplication();
        this.applicationConfigurations = applicationConfigurations;
        applyApplicationConfigurations(applicationConfigurations);
        this.servletContainerBridge = new ServletContainerBridge(this.application);
        this.servletConfiguration = servletConfiguration;
        this.resourcePublisher = new ResourcePublisher(this.servletContainerBridge, configuration.getPublishDelay());
    }

    void applyApplicationConfigurations(ServiceContainer applicationConfigurations) {
        getRootApplication().addProperties(new DefaultApplicationConfiguration().getProperties());
        ServiceHolder[] services = applicationConfigurations.getServices();
        for (ServiceHolder serviceHolder : services) {
            Object service = serviceHolder.getService();
            if (service instanceof ApplicationConfiguration) {
                Map<String, Object> properties = ((ApplicationConfiguration) service).getProperties();
                if (properties != null) {
                    getRootApplication().addProperties(properties);
                }
            }
        }
    }

    public void addResource(Object resource) {
        getRootApplication().addResource(resource);
        registerServletWhenNotAlreadyRegistered();
        this.resourcePublisher.schedulePublishing();
    }

    public void updateConfiguration(Configuration configuration) {
        this.resourcePublisher.setPublishDelay(configuration.getPublishDelay());
        String oldRootPath = this.rootPath;
        this.rootPath = configuration.getRoothPath();
        handleRootPath(oldRootPath);
        applyApplicationConfigurations(this.applicationConfigurations);
        handeRepublish();
    }

    private void handleRootPath(String oldRootPath) {
        // if rootPath has changed and we already have registered our servlet and we need to refresh it
        if (this.isApplicationRegistered && !oldRootPath.equals(this.rootPath)) {
            refreshServletRegistration(oldRootPath);
        }
    }

    public void updateAppConfiguration(ServiceContainer applicationConfigurations) {
        this.applicationConfigurations = applicationConfigurations;
        applyApplicationConfigurations(this.applicationConfigurations);
        handeRepublish();
    }

    public void updateServletConfiguration(ServletConfiguration servletConfiguration) {
        boolean isServletUpdateRequired = this.servletConfiguration != servletConfiguration;
        this.servletConfiguration = servletConfiguration;
        // if servletConfiguration object has changed and we already have a servlet - refresh it
        if (this.isApplicationRegistered && isServletUpdateRequired) {
            refreshServletRegistration(this.rootPath);
        }
        handeRepublish();
    }

    private void handeRepublish() {
        // if application has been marked dirty and we have registered resources - we will republish
        if (this.isApplicationRegistered) {
            this.resourcePublisher.schedulePublishing();
        }
    }

    private void refreshServletRegistration(String pathToUnregister) {
        synchronized (this.servletContainerBridge) {
            safeUnregister(pathToUnregister);
        }
        registerServletWhenNotAlreadyRegistered();
    }

    void registerServletWhenNotAlreadyRegistered() {
        if (!this.isApplicationRegistered) {
            this.isApplicationRegistered = true;
            registerApplication();
        }
    }

    private void registerApplication() {
        ClassLoader loader = getContextClassloader();
        setContextClassloader();
        try {
            registerServlet();
        } catch (ServletException | NamespaceException shouldNotHappen) {
            throw new IllegalStateException(shouldNotHappen);
        } finally {
            resetContextClassloader(loader);
        }
    }

    private ClassLoader getContextClassloader() {
        return Thread.currentThread().getContextClassLoader();
    }

    private void setContextClassloader() {
        Thread.currentThread().setContextClassLoader(getClass().getClassLoader());
    }

    private void registerServlet() throws ServletException, NamespaceException {
        ClassLoader original = getContextClassloader();
        try {
            Thread.currentThread().setContextClassLoader(Application.class.getClassLoader());
            this.httpService.registerServlet(this.rootPath, this.servletContainerBridge, getInitParams(),
                    getHttpContext());
        } finally {
            resetContextClassloader(original);
        }
    }

    private Dictionary getInitParams() {
        if (this.servletConfiguration != null) {
            return this.servletConfiguration.getInitParams(this.httpService, this.rootPath);
        }
        return null;
    }

    private HttpContext getHttpContext() {
        if (this.servletConfiguration != null) {
            return this.servletConfiguration.getHttpContext(this.httpService, this.rootPath);
        }
        return null;
    }

    private void resetContextClassloader(ClassLoader loader) {
        Thread.currentThread().setContextClassLoader(loader);
    }

    public void removeResource(Object resource) {
        boolean isDirty = getRootApplication().removeResource(resource);
        // When removing resources that cause the application to be dirty, it makes sense to turn off
        // request servicing until Jersey is reloaded as Jersey will hold on to the old OSGi instances
        // of registered resources and we may see some exceptions if a request comes in that should be
        // processed by a service that is in the process of deactivating (for example some unset methods
        // were called). This way we'll send out a nice 503 until Jersey reloads which is much cleaner.
        if (isDirty) {
            this.servletContainerBridge.setJerseyReady(false);
        }
        unregisterServletWhenNoResourcePresents();
        this.resourcePublisher.schedulePublishing();
    }

    private void unregisterServletWhenNoResourcePresents() {
        if (!getRootApplication().hasResources() && this.isApplicationRegistered) {
            // unregistering while jersey context is being reloaded can lead to many exceptions
            this.resourcePublisher.cancelPublishing();
            synchronized (this.servletContainerBridge) {
                safeUnregister(this.rootPath);
            }
        }
    }

    public List<Object> eliminate() {
        this.resourcePublisher.cancelPublishing();
        this.resourcePublisher.shutdown();
        if (this.isApplicationRegistered) {
            synchronized (this.servletContainerBridge) {
                safeUnregister(this.rootPath);
            }
        }
        return new ArrayList<>(getRootApplication().getResources());
    }

    void safeUnregister(String rootPath) {
        try {
            // this should call destroy on our servlet container
            this.httpService.unregister(rootPath);
        } catch (Exception jerseyShutdownException) {
            // do nothing because jersey sometimes throws an exception during shutdown
        }
        this.isApplicationRegistered = false;
    }

    // For testing purpose
    RootApplication getRootApplication() {
        return this.application;
    }

    ServletContainerBridge getServletContainerBridge() {
        return this.servletContainerBridge;
    }
}
