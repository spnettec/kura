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

import java.util.HashMap;
import java.util.Map;

import org.glassfish.jersey.server.ServerProperties;

import com.eclipsesource.jaxrs.publisher.ApplicationConfiguration;

public class DefaultApplicationConfiguration implements ApplicationConfiguration {

    @Override
    public Map<String, Object> getProperties() {
        Map<String, Object> properties = new HashMap<>();
        // don't look for implementations described by META-INF/services/*
        properties.put(ServerProperties.METAINF_SERVICES_LOOKUP_DISABLE, false);
        // disable auto discovery on server, as it's handled via OSGI
        properties.put(ServerProperties.FEATURE_AUTO_DISCOVERY_DISABLE, true);
        return properties;
    }

}
