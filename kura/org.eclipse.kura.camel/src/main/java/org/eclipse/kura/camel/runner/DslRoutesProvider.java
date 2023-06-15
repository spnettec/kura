/*******************************************************************************
 * Copyright (c) 2016, 2020 Red Hat Inc and others
 * 
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 * 
 * SPDX-License-Identifier: EPL-2.0
 * 
 * Contributors:
 *  Red Hat Inc
 *******************************************************************************/
package org.eclipse.kura.camel.runner;

import java.util.Objects;

import org.apache.camel.CamelContext;
import org.apache.camel.impl.engine.DefaultRoutesLoader;
import org.apache.camel.spi.Resource;
import org.apache.camel.support.ResourceHelper;

public class DslRoutesProvider implements RoutesProvider {

    private final String inputString;
    private final String fileName;

    public DslRoutesProvider(final String xml, String fileName) {
        Objects.requireNonNull(xml);
        this.inputString = xml;
        this.fileName = fileName;
    }

    public static DslRoutesProvider fromString(final String xml, String fileName) {
        return new DslRoutesProvider(xml, fileName);
    }

    @Override
    public void applyRoutes(CamelContext camelContext) throws Exception {
        Resource resource = ResourceHelper.fromString(fileName, this.inputString);
        try (DefaultRoutesLoader routesLoader = new DefaultRoutesLoader(camelContext)) {
            routesLoader.loadRoutes(resource);
        }

    }
}