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

public class Configuration {

    static final String CONFIG_SERVICE_PID = "com.eclipsesource.jaxrs.connector";
    static final String PROPERTY_ROOT = "root";
    static final String PROPERTY_PUBLISH_DELAY = "publishDelay";
    static final long DEFAULT_PUBLISH_DELAY = 150;
    private final long publishDelay;
    private String rootPath;

    public Configuration() {
        this.publishDelay = DEFAULT_PUBLISH_DELAY;
    }

    public long getPublishDelay() {
        return this.publishDelay;
    }

    public String getRoothPath() {
        return this.rootPath == null ? "/services" : this.rootPath;
    }

}
