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
 *    Ivan Iliev - added ServletConfigurationTracker
 ******************************************************************************/
package com.eclipsesource.jaxrs.publisher.internal;

import javax.ws.rs.Path;

import org.osgi.framework.Bundle;
import org.osgi.framework.BundleActivator;
import org.osgi.framework.BundleContext;
import org.osgi.framework.BundleException;
import org.osgi.framework.FrameworkUtil;
import org.osgi.framework.ServiceReference;
import org.osgi.framework.ServiceRegistration;

import com.eclipsesource.jaxrs.publisher.ResourceFilter;

public class Activator implements BundleActivator {

    private ServiceRegistration<?> connectorRegistration;
    private JAXRSConnector jaxRsConnector;
    private HttpTracker httpTracker;
    private ResourceTracker allTracker;
    private ServletConfigurationTracker servletConfigurationTracker;
    private ApplicationConfigurationTracker applicationConfigurationTracker;

    @Override
    public void start(BundleContext context) throws Exception {
        System.setProperty("javax.ws.rs.ext.RuntimeDelegate",
                "org.glassfish.jersey.server.internal.RuntimeDelegateImpl");
        startJerseyServer();
        this.jaxRsConnector = new JAXRSConnector(context);
        this.connectorRegistration = context.registerService(JAXRSConnector.class.getName(), this.jaxRsConnector, null);
        openHttpServiceTracker(context);
        openServletConfigurationTracker(context);
        openApplicationConfigurationTracker(context);
        openAllServiceTracker(context);
    }

    private void startJerseyServer() throws BundleException {
        Bundle bundle = getJerseyAPIBundle();
        if (bundle.getState() != Bundle.ACTIVE) {
            bundle.start();
        }
    }

    private void openHttpServiceTracker(BundleContext context) {
        this.httpTracker = new HttpTracker(context, this.jaxRsConnector);
        this.httpTracker.open();
    }

    private void openServletConfigurationTracker(BundleContext context) {
        this.servletConfigurationTracker = new ServletConfigurationTracker(context, this.jaxRsConnector);
        this.servletConfigurationTracker.open();
    }

    private void openApplicationConfigurationTracker(BundleContext context) {
        this.applicationConfigurationTracker = new ApplicationConfigurationTracker(context, this.jaxRsConnector);
        this.applicationConfigurationTracker.open();
    }

    private void openAllServiceTracker(BundleContext context) {
        ResourceFilter allResourceFilter = getResourceFilter(context);
        this.allTracker = new ResourceTracker(context, allResourceFilter.getFilter(), this.jaxRsConnector);
        this.allTracker.open();
    }

    private ResourceFilter getResourceFilter(BundleContext context) {
        ServiceReference<?> filterReference = context.getServiceReference(ResourceFilter.class.getName());
        if (filterReference != null) {
            return (ResourceFilter) context.getService(filterReference);
        }
        return new AllResourceFilter(context);
    }

    @Override
    public void stop(BundleContext context) throws Exception {
        this.httpTracker.close();
        this.servletConfigurationTracker.close();
        this.applicationConfigurationTracker.close();
        this.allTracker.close();
        this.connectorRegistration.unregister();
    }

    // For testing purpose
    Bundle getJerseyAPIBundle() {
        return FrameworkUtil.getBundle(Path.class);
    }
}
