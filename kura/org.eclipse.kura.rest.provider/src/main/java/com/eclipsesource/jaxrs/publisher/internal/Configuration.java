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
