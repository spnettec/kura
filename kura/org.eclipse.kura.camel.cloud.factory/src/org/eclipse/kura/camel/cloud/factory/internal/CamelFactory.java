/*******************************************************************************
 * Copyright (c) 2016, 2020 Red Hat Inc and others.
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 * Contributors:
 *     Red Hat Inc
 *     Eurotech
 *
 *******************************************************************************/
package org.eclipse.kura.camel.cloud.factory.internal;

import static org.eclipse.kura.camel.component.Configuration.asBoolean;
import static org.eclipse.kura.camel.component.Configuration.asString;

import java.util.Map;

import org.eclipse.kura.KuraException;
import org.eclipse.kura.camel.camelcloud.CamelCloudService;
import org.eclipse.kura.cloud.CloudClient;
import org.eclipse.kura.configuration.ConfigurableComponent;
import org.osgi.framework.FrameworkUtil;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * A Kura component which takes care of creating a {@link CloudService} based in Apache Camel
 * <p>
 * This component does not directly register as {@link CloudService}, but can be managed
 * through the Kura configuration system and will forward this configuration to the
 * {@link XmlCamelCloudService} which will take care of the lifecycle of the Camel context.
 * </p>
 */
public class CamelFactory implements ConfigurableComponent, CamelCloudService {

    private static final Logger logger = LoggerFactory.getLogger(CamelFactory.class);

    private XmlCamelCloudService service;

    private ServiceConfiguration configuration;

    public void activate(final Map<String, Object> properties) throws Exception {
        setFromProperties(properties);
    }

    public void modified(final Map<String, Object> properties) throws Exception {
        setFromProperties(properties);
    }

    private void setFromProperties(final Map<String, Object> properties) throws Exception {

        final ServiceConfiguration serviceConfiguration = new ServiceConfiguration();
        serviceConfiguration.setXml(asString(properties, "xml"));
        serviceConfiguration.setInitCode(asString(properties, "initCode"));
        serviceConfiguration.setEnableJmx(asBoolean(properties, "enableJmx", true));

        createService(serviceConfiguration);
    }

    public void deactivate() {
        if (this.service != null) {
            try {
                this.service.stop();
            } catch (Exception e) {
                logger.warn("Failed to stop", e);
            }
            this.service = null;
        }
    }

    private void createService(final ServiceConfiguration configuration) throws Exception {

        if (this.configuration == configuration) {
            // null to null?
            return;
        }
        if (this.configuration != null && this.configuration.equals(configuration)) {
            // no change
            return;
        }

        // stop old service

        if (this.service != null) {
            this.service.stop();
            this.service = null;
        }

        // start new service
        if (configuration.isValid()) {
            this.service = new XmlCamelCloudService(FrameworkUtil.getBundle(CamelFactory.class).getBundleContext(),
                    configuration);
            this.service.start();
        }

        this.configuration = configuration;
    }

    @Override
    public CloudClient newCloudClient(String appId) throws KuraException {
        return this.service.getService().newCloudClient(appId);
    }

    @Override
    public String[] getCloudApplicationIdentifiers() {
        return this.service.getService().getCloudApplicationIdentifiers();
    }

    @Override
    public boolean isConnected() {
        return this.service.getService().isConnected();
    }

    @Override
    public void registerBaseEndpoint(String applicationId, String baseEndpoint) {
        this.service.getService().registerBaseEndpoint(applicationId, baseEndpoint);

    }

    @Override
    public void release(String applicationId) {
        this.service.getService().release(applicationId);
    }
}
