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

import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.camel.camelcloud.CamelCloudService;
import org.eclipse.kura.camel.component.Configuration;
import org.eclipse.kura.cloudconnection.factory.CloudConnectionFactory;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.locale.LocaleContextHolder;
import org.osgi.framework.BundleContext;
import org.osgi.framework.InvalidSyntaxException;
import org.osgi.service.cm.ConfigurationAdmin;
import org.osgi.service.component.ComponentContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * An implementation of {@link CloudConnectionFactory} based on Apache Camel
 */
public class CamelCloudServiceFactory implements CloudConnectionFactory {

    private static final Logger logger = LoggerFactory.getLogger(CamelCloudServiceFactory.class);

    // public static final String PID = "org.eclipse.kura.camel.cloud.factory.CamelCloudServiceFactory";
    public static final String CLOUD_SERVICE_FACTORY_PID = "org.eclipse.kura.camel.cloud.factory.CamelFactory";
    private ConfigurationService configurationService;

    private BundleContext bundleContext;

    public void activate(final ComponentContext context) {
        this.bundleContext = context.getBundleContext();
    }

    public void setConfigurationService(final ConfigurationService configurationService) {
        this.configurationService = configurationService;
    }

    /**
     * Add a new CamelFactory
     *
     * @param userPid
     *            the PID as entered by the user
     * @param properties
     *            the provided configuration properties
     * @throws KuraException
     *             if anything goes wrong
     */
    protected void add(String pid, String name, String description, final Map<String, Object> properties)
            throws KuraException {
        logger.info("Add: {}", pid);
        if (pid == null || pid.equals("")) {
            pid = CLOUD_SERVICE_FACTORY_PID + "-Cloud-" + new Date().getTime();
        }

        final Map<String, Object> props = new HashMap<>();

        String xml = Configuration.asString(properties, "xml");
        if (xml == null || xml.trim().isEmpty()) {
            xml = "<routes xmlns=\"http://camel.apache.org/schema/spring\"></routes>";
        }

        props.put("xml", xml);

        final Integer serviceRanking = Configuration.asInteger(properties, "serviceRanking");
        if (serviceRanking != null) {
            props.put("serviceRanking", serviceRanking);
        }

        // props.put("cloud.service.pid", pid);
        if (name != null && !name.equals("")) {
            props.put(ConfigurationService.KURA_CLOUD_FACTORY_NAME, name);
        }
        if (description != null && !description.equals("")) {
            props.put(ConfigurationService.KURA_CLOUD_FACTORY_DESC, description);
        }

        this.configurationService.createFactoryConfiguration(CLOUD_SERVICE_FACTORY_PID, pid, props, true);
    }

    @Override
    public void createConfiguration(final String pid, String name, String description) throws KuraException {
        add(pid, name, description, Collections.emptyMap());
    }

    @Override
    public void createConfiguration(String pid) throws KuraException {
        add(pid, null, null, Collections.emptyMap());
    }

    @Override
    public void deleteConfiguration(final String pid) throws KuraException {
        this.configurationService.deleteFactoryConfiguration(pid, true);
    }

    @Override
    public String getFactoryPid() {
        return CLOUD_SERVICE_FACTORY_PID;
    }

    @Override
    public String getCloudName(String pid) {
        try {
            ComponentConfiguration config = this.configurationService.getComponentConfiguration(pid);
            String name = (String) config.getConfigurationProperties()
                    .get(ConfigurationService.KURA_CLOUD_FACTORY_NAME);
            if (name != null) {
                return name;
            }
            return CLOUD_SERVICE_FACTORY_PID;
        } catch (Exception e) {
            return CLOUD_SERVICE_FACTORY_PID;
        }
    }

    @Override
    public String getFactoryName() {
        try {
            ComponentConfiguration config = this.configurationService
                    .getDefaultComponentConfiguration(CLOUD_SERVICE_FACTORY_PID);
            return config.getLocalizedDefinition(LocaleContextHolder.getLocale().getLanguage()).getName();
        } catch (Exception e) {
            return CLOUD_SERVICE_FACTORY_PID;
        }
    }

    @Override
    public List<String> getStackComponentsPids(final String pid) throws KuraException {
        List<String> componentPids = new ArrayList<>();
        componentPids.add(pid);
        return componentPids;
    }

    @Override
    public Set<String> getManagedCloudConnectionPids() throws KuraException {
        try {
            return this.bundleContext.getServiceReferences(CamelCloudService.class, null).stream().filter(ref -> {
                final Object kuraServicePid = ref.getProperty(ConfigurationService.KURA_SERVICE_PID);

                if (!(kuraServicePid instanceof String)) {
                    return false;
                }
                final String factoryPid = (String) ref.getProperty(ConfigurationAdmin.SERVICE_FACTORYPID);
                return factoryPid.equals(CLOUD_SERVICE_FACTORY_PID);
            }).map(ref -> (String) ref.getProperty(ConfigurationService.KURA_SERVICE_PID)).collect(Collectors.toSet());
        } catch (InvalidSyntaxException e) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_ATTRIBUTE_INVALID, e);
        }
    }
}
