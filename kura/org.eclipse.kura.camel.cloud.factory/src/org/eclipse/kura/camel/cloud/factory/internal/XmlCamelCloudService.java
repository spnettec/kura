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
package org.eclipse.kura.camel.cloud.factory.internal;

import static org.eclipse.kura.camel.utils.CamelContexts.scriptInitCamelContext;

import java.io.ByteArrayInputStream;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

import javax.script.ScriptException;

import org.apache.camel.CamelContext;
import org.apache.camel.model.RoutesDefinition;
import org.apache.camel.spi.SupervisingRouteController;
import org.apache.camel.support.SimpleRegistry;
import org.apache.camel.xml.in.ModelParser;
import org.eclipse.kura.camel.bean.PayloadFactory;
import org.eclipse.kura.camel.camelcloud.DefaultCamelCloudService;
import org.eclipse.kura.camel.cloud.KuraCloudComponent;
import org.eclipse.kura.camel.runner.OsgiDefaultKuraCamelContext;
import org.osgi.framework.BundleContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * An service managing a single Camel context
 * <p>
 * This service component does manage the lifecycle of a single {@link DefaultCamelCloudService}
 * instance. It will instantiate the Camel context and register the XmlCamelCloudService instance
 * with OSGi.
 * </p>
 */
public class XmlCamelCloudService {

    private static final Logger logger = LoggerFactory.getLogger(XmlCamelCloudService.class);

    private final BundleContext context;

    private final ServiceConfiguration configuration;

    private DefaultCamelCloudService service;

    public DefaultCamelCloudService getService() {
        return this.service;
    }

    private OsgiDefaultKuraCamelContext router;

    // private ServiceRegistration<CloudService> handle;

    public XmlCamelCloudService(final BundleContext context, final ServiceConfiguration configuration) {
        this.context = context;
        this.configuration = configuration;
    }

    public void start() throws Exception {

        // new registry

        final SimpleRegistry simpleRegistry = new SimpleRegistry();
        Map<Class<?>, Object> mapClass = new HashMap<>();
        mapClass.put(PayloadFactory.class, new PayloadFactory());
        simpleRegistry.put("payloadFactory", mapClass);

        // new router

        this.router = new OsgiDefaultKuraCamelContext(this.context, simpleRegistry);

        if (!this.configuration.isEnableJmx()) {
            this.router.disableJMX();
        }
        SupervisingRouteController src = this.router.getRouteController().supervising();
        src.setBackOffDelay(5000);
        src.setBackOffMaxAttempts(3);
        src.setInitialDelay(1000);
        src.setThreadPoolSize(2);
        // call init code

        callInitCode(this.router);

        // new cloud service

        this.service = new DefaultCamelCloudService(this.router);

        // set up

        final KuraCloudComponent cloudComponent = new KuraCloudComponent(this.router, this.service);
        this.router.addComponent("kura-cloud", cloudComponent);

        ModelParser parser = new ModelParser(new ByteArrayInputStream(this.configuration.getXml().getBytes()));
        Optional<RoutesDefinition> value = parser.parseRoutesDefinition();

        if (value.isPresent()) {
            this.router.addRouteDefinitions(value.get().getRoutes());
        }

        // start

        logger.debug("Starting router...");
        this.router.start();
        // final ServiceStatus status = this.router.getStatus();
        // logger.debug("Starting router... {} ({}, {})", status, status == Started, this.service.isConnected());

        // register

        // final Dictionary<String, Object> props = new Hashtable<>();
        // props.put(SERVICE_PID, this.pid);
        // props.put("service.factoryPid", CLOUD_SERVICE_FACTORY_PID);
        // props.put(KURA_SERVICE_PID, this.pid);
        // props.put("kura.cloud.service.factory.pid", PID);

        // this.handle = this.context.registerService(CloudService.class, this.service, props);
    }

    public void stop() throws Exception {
        // if (this.handle != null) {
        // this.handle.unregister();
        // this.handle = null;
        // }
        if (this.service != null) {
            this.service.dispose();
            this.service = null;
        }
        if (this.router != null) {
            this.router.stop();
            this.router = null;
        }
    }

    private void callInitCode(final CamelContext router) throws ScriptException {
        scriptInitCamelContext(router, this.configuration.getInitCode(), XmlCamelCloudService.class.getClassLoader());
    }

}
