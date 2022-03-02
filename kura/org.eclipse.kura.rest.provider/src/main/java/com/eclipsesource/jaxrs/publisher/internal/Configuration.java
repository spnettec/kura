/*******************************************************************************
 * Copyright (c) 2012,2015 EclipseSource and others.
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 * Contributors:
 *    Holger Staudacher - initial API and implementation, ongoing development
 *    ProSyst Software GmbH. - compatibility with OSGi specification 4.2 APIs
 ******************************************************************************/
package com.eclipsesource.jaxrs.publisher.internal;

import java.util.Dictionary;

import org.osgi.service.cm.ConfigurationException;
import org.osgi.service.cm.ManagedService;

@SuppressWarnings("rawtypes")
public class Configuration implements ManagedService {

    static final String CONFIG_SERVICE_PID = "com.eclipsesource.jaxrs.connector";
    static final String PROPERTY_ROOT = "root";
    static final String PROPERTY_PUBLISH_DELAY = "publishDelay";
    static final long DEFAULT_PUBLISH_DELAY = 150;

    private final JAXRSConnector connector;
    private long publishDelay;
    private String rootPath;

    public Configuration(JAXRSConnector jaxRsConnector) {
        this.connector = jaxRsConnector;
        this.publishDelay = DEFAULT_PUBLISH_DELAY;
    }

    @Override
    public void updated(Dictionary properties) throws ConfigurationException {
        if (properties != null) {
            String root = String.valueOf(properties.get(PROPERTY_ROOT));
            ensureRootIsPresent(root);
            ensureRootIsValid(root);
            this.rootPath = root;
            this.publishDelay = getPublishDelay(properties);
            this.connector.updateConfiguration(this);
        }
    }

    private void ensureRootIsValid(String rootPath) throws ConfigurationException {
        if (!rootPath.startsWith("/")) {
            throw new ConfigurationException(PROPERTY_ROOT, "Root path does not start with a /");
        }
    }

    private void ensureRootIsPresent(Object root) throws ConfigurationException {
        if (root == null || !(root instanceof String)) {
            throw new ConfigurationException(PROPERTY_ROOT, "Property is not set or invalid.");
        }
    }

    private long getPublishDelay(Dictionary properties) {
        Object interval = properties.get(PROPERTY_PUBLISH_DELAY);
        if (interval == null) {
            return DEFAULT_PUBLISH_DELAY;
        }
        return (Long) interval;
    }

    public long getPublishDelay() {
        return this.publishDelay;
    }

    public String getRoothPath() {
        return this.rootPath == null ? "/services" : this.rootPath;
    }

}
