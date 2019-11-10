/*******************************************************************************
 * Copyright (c) 2016, 2017 Red Hat Inc and others.
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 * Contributors:
 *     Red Hat Inc
 *******************************************************************************/
package org.eclipse.kura.camel.cloud.factory.internal;

import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import org.eclipse.kura.KuraException;
import org.eclipse.kura.camel.component.Configuration;
import org.eclipse.kura.cloudconnection.factory.CloudConnectionFactory;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.locale.LocaleContextHolder;
import org.osgi.framework.BundleContext;
import org.osgi.framework.Filter;
import org.osgi.framework.FrameworkUtil;
import org.osgi.service.component.ComponentContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * An implementation of {@link CloudConnectionFactory} based on Apache Camel
 */
public class CamelCloudServiceFactory implements CloudConnectionFactory {

    private static final Logger logger = LoggerFactory.getLogger(CamelCloudServiceFactory.class);

    public static final String PID = "org.eclipse.kura.camel.cloud.factory.CamelCloudServiceFactory";
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
        if (pid == null || pid.equals(""))
            pid = CLOUD_SERVICE_FACTORY_PID + "-Cloud-" + new Date().getTime();

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

        props.put("cloud.service.pid", pid);
        if (name != null && !name.equals(""))
            props.put(ConfigurationService.KURA_CLOUD_FACTORY_NAME, name);
        if (description != null && !description.equals(""))
            props.put(ConfigurationService.KURA_CLOUD_FACTORY_DESC, description);
        String camelPid = CLOUD_SERVICE_FACTORY_PID + "-" + new Date().getTime();
        this.configurationService.createFactoryConfiguration(CLOUD_SERVICE_FACTORY_PID, camelPid, props, true);
    }

    private static Filter getFilterUnchecked(final String filter) {
        try {
            return FrameworkUtil.createFilter(filter);
        } catch (final Exception e) {
            throw new IllegalStateException(e);
        }
    }

    /**
     * Provide a common way to delete camel factory configurations
     * <p>
     * Right now this is a rather slim implementation used by CamelFactory and the CamelManager
     * </p>
     *
     * @param configurationService
     *            the configuration service to use
     * @param pid
     *            the PID to delete
     */
    static void delete(final ConfigurationService configurationService, final String pid) {
        try {
            configurationService.deleteFactoryConfiguration(pid, true);
        } catch (final KuraException e) {
            logger.warn("Failed to delete: {}", pid, e);
        }
    }

    @Override
    public void createConfiguration(final String pid, String name, String description) throws KuraException {
        add(pid, name, description, Collections.<String, Object> emptyMap());
    }

    @Override
    public void createConfiguration(String pid) throws KuraException {
        add(pid, null, null, Collections.<String, Object> emptyMap());
    }

    @Override
    public void deleteConfiguration(final String pid) throws KuraException {
        List<ComponentConfiguration> configs = configurationService
                .getComponentConfigurations(getFilterUnchecked("(|(cloud.service.pid=" + pid + "))"));
        configs.stream().forEach(config -> delete(this.configurationService, config.getPid()));
    }

    @Override
    public String getFactoryPid() {
        return CLOUD_SERVICE_FACTORY_PID;
    }

    @Override
    public String getCloudName(String pid) {
        try {
            List<ComponentConfiguration> configs = configurationService
                    .getComponentConfigurations(getFilterUnchecked("(|(cloud.service.pid=" + pid + "))"));
            if (configs == null || configs.size() > 1)
                return CLOUD_SERVICE_FACTORY_PID;
            ComponentConfiguration config = configs.get(0);
            String name = (String) config.getConfigurationProperties()
                    .get(ConfigurationService.KURA_CLOUD_FACTORY_NAME);
            if (name != null)
                return name;
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
        List<ComponentConfiguration> configs = configurationService
                .getComponentConfigurations(getFilterUnchecked("(|(cloud.service.pid=" + pid + "))"));
        return configs.stream().map(ComponentConfiguration::getPid).collect(Collectors.toList());
    }

    @Override
    public Set<String> getManagedCloudConnectionPids() throws KuraException {
        final Set<String> result = new HashSet<>();

        for (final ComponentConfiguration cc : this.configurationService.getComponentConfigurations()) {
            if (cc.getDefinition() != null && CLOUD_SERVICE_FACTORY_PID.equals(cc.getDefinition().getId())) {
                String pid = (String) cc.getConfigurationProperties().get("cloud.service.pid");
                result.add(pid);
            }
        }
        return result;
    }
}
