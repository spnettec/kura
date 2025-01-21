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
package com.eclipsesource.jaxrs.publisher;

public class ServiceProperties {

    /**
     * <p>
     * When registering a @Path or @Provider annotated object as an OSGi service the connector does publish
     * this resource automatically. Anyway, in some scenarios it's not wanted to publish those services. If you
     * want a resource not publish set this property as a service property with the value <code>false</code>.
     * </p>
     */
    public static final String PUBLISH = "com.eclipsesource.jaxrs.publish";

    private ServiceProperties() {
        // prevent instantiation
    }
}
