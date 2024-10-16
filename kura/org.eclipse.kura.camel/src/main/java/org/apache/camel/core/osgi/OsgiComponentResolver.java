/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.camel.core.osgi;

import org.apache.camel.CamelContext;
import org.apache.camel.Component;
import org.apache.camel.RuntimeCamelException;
import org.apache.camel.impl.engine.DefaultComponentResolver;
import org.apache.camel.spi.ComponentResolver;
import org.osgi.framework.BundleContext;
import org.osgi.framework.InvalidSyntaxException;
import org.osgi.framework.ServiceReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class OsgiComponentResolver extends DefaultComponentResolver {

    private static final Logger LOG = LoggerFactory.getLogger(OsgiComponentResolver.class);

    private final BundleContext bundleContext;

    public OsgiComponentResolver(BundleContext bundleContext) {
        this.bundleContext = bundleContext;
    }

    @Override
    public Component resolveComponent(String name, CamelContext context) {
        Component componentReg = super.resolveComponent(name, context);
        if (componentReg != null) {
            return componentReg;
        }

        // Check in OSGi bundles
        try {
            Component component = getComponent(name, context);
            if (component == null) {
                component = super.resolveComponent(name, context);
            }
            return component;
        } catch (Exception e) {
            throw RuntimeCamelException.wrapRuntimeCamelException(e);
        }
    }

    protected Component getComponent(String name, CamelContext context) throws Exception {
        LOG.trace("Finding Component: {}", name);
        try {
            ServiceReference<?>[] refs = bundleContext.getServiceReferences(ComponentResolver.class.getName(),
                    "(component=" + name + ")");
            if (refs != null) {
                for (ServiceReference<?> ref : refs) {
                    Object service = bundleContext.getService(ref);
                    if (ComponentResolver.class.isAssignableFrom(service.getClass())) {
                        ComponentResolver resolver = (ComponentResolver) service;
                        return resolver.resolveComponent(name, context);
                    }
                }
            }
            return null;
        } catch (InvalidSyntaxException e) {
            throw RuntimeCamelException.wrapRuntimeCamelException(e);
        }
    }

}
