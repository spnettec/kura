/*******************************************************************************
 * Copyright (c) 2011, 2019 Eurotech and/or its affiliates and others
 *
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 * Contributors:
 *     Eurotech
 *     Red Hat Inc
 *     Amit Kumar Mondal
 *******************************************************************************/
package org.eclipse.kura.web.server;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Date;
import java.util.Dictionary;
import java.util.HashMap;
import java.util.Hashtable;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpSession;

import org.eclipse.kura.KuraException;
import org.eclipse.kura.cloud.factory.CloudServiceFactory;
import org.eclipse.kura.cloudconnection.factory.CloudConnectionFactory;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.configuration.metatype.AD;
import org.eclipse.kura.configuration.metatype.Icon;
import org.eclipse.kura.configuration.metatype.OCD;
import org.eclipse.kura.configuration.metatype.Option;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.locale.LocaleContextHolder;
import org.eclipse.kura.util.service.ServiceUtil;
import org.eclipse.kura.web.server.util.GwtServerUtil;
import org.eclipse.kura.web.server.util.KuraExceptionHandler;
import org.eclipse.kura.web.server.util.ServiceLocator;
import org.eclipse.kura.web.session.Attributes;
import org.eclipse.kura.web.shared.GwtKuraErrorCode;
import org.eclipse.kura.web.shared.GwtKuraException;
import org.eclipse.kura.web.shared.model.GwtConfigComponent;
import org.eclipse.kura.web.shared.model.GwtConfigParameter;
import org.eclipse.kura.web.shared.model.GwtConfigParameter.GwtConfigParameterType;
import org.eclipse.kura.web.shared.model.GwtXSRFToken;
import org.eclipse.kura.web.shared.service.GwtComponentService;
import org.eclipse.kura.web.shared.service.GwtWireGraphService;
import org.eclipse.kura.wire.WireHelperService;
import org.eclipse.kura.wire.graph.WireComponentDefinition;
import org.eclipse.kura.wire.graph.WireComponentDefinitionService;
import org.osgi.framework.BundleContext;
import org.osgi.framework.Filter;
import org.osgi.framework.FrameworkUtil;
import org.osgi.framework.InvalidSyntaxException;
import org.osgi.framework.ServiceReference;
import org.osgi.service.cm.Configuration;
import org.osgi.service.cm.ConfigurationAdmin;
import org.osgi.service.component.runtime.ServiceComponentRuntime;
import org.osgi.service.component.runtime.dto.ReferenceDTO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class GwtComponentServiceImpl extends OsgiRemoteServiceServlet implements GwtComponentService {

    private static final String SUCCESSFULLY_LISTED_COMPONENT_CONFIGS_MESSAGE = "UI Component - Success - Successfully listed component configs for user: {}, session {}";

    private static final String SUCCESSFULLY_LISTED_PIDS_FROM_TARGET_MESSAGE = "UI Component - Success - Successfully listed pids from target for user: {}, session: {}, pid: {}";

    private static final String FAILED_TO_CREATE_COMPONENT_CONFIG_MESSAGE = "UI Component - Failure - Failed to create component config for user: {}, session {}";

    private static final String FAILED_TO_LIST_COMPONENT_CONFIGS_MESSAGE = "UI Component - Failure - Failed to list component configs for user: {}, session {}";

    private static final String SUCCESSFULLY_LISTED_COMPONENT_CONFIG_MESSAGE = "UI Component - Success - Successfully listed component config for user: {}, session {}";

    private static final String FAILED_TO_LIST_COMPONENT_CONFIG_MESSAGE = "UI Component - Failure - Failed to list component config for user: {}, session {}";

    private static final Logger auditLogger = LoggerFactory.getLogger("AuditLogger");

    private static final String DRIVER_PID = "driver.pid";
    private static final String KURA_SERVICE_PID = ConfigurationService.KURA_SERVICE_PID;
    private static final String SERVICE_FACTORY_PID = "service.factoryPid";

    private static final int SERVICE_WAIT_TIMEOUT = 60;

    private static final long serialVersionUID = -4176701819112753800L;

    @Override
    public List<String> findTrackedPids(GwtXSRFToken xsrfToken) throws GwtKuraException {
        checkXSRFToken(xsrfToken);
        ConfigurationService cs = ServiceLocator.getInstance().getService(ConfigurationService.class);

        getThreadLocalRequest();

        return new ArrayList<>(cs.getConfigurableComponentPids());
    }

    @Override
    public List<GwtConfigComponent> findFilteredComponentConfigurations(GwtXSRFToken xsrfToken)
            throws GwtKuraException {
        checkXSRFToken(xsrfToken);
        return findFilteredComponentConfigurationsInternal();
    }

    @Override
    public List<GwtConfigComponent> findComponentConfigurations(GwtXSRFToken xsrfToken, String osgiFilter)
            throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        try {
            final Filter filter = FrameworkUtil.createFilter(osgiFilter);
            List<GwtConfigComponent> result = ServiceLocator.applyToServiceOptionally(ConfigurationService.class,
                    configurationService -> configurationService.getComponentConfigurations(filter) //
                            .stream() //
                            .map(this::createMetatypeOnlyGwtComponentConfigurationInternal) //
                            .filter(Objects::nonNull) //
                            .collect(Collectors.toList()));

            auditLogger.info(SUCCESSFULLY_LISTED_COMPONENT_CONFIGS_MESSAGE,
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
            return result;
        } catch (InvalidSyntaxException e) {
            auditLogger.warn(FAILED_TO_LIST_COMPONENT_CONFIGS_MESSAGE,
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
            throw new GwtKuraException(GwtKuraErrorCode.ILLEGAL_ARGUMENT, e);
        } catch (Exception e) {
            auditLogger.warn(FAILED_TO_LIST_COMPONENT_CONFIGS_MESSAGE,
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
            throw new GwtKuraException(GwtKuraErrorCode.INTERNAL_ERROR, e);
        }
    }

    @Override
    public List<GwtConfigComponent> findFilteredComponentConfiguration(GwtXSRFToken xsrfToken, String componentPid)
            throws GwtKuraException {
        checkXSRFToken(xsrfToken);
        return findFilteredComponentConfigurationInternal(componentPid);
    }

    @Override
    public List<GwtConfigComponent> findComponentConfigurations(GwtXSRFToken xsrfToken) throws GwtKuraException {
        checkXSRFToken(xsrfToken);
        return findComponentConfigurationsInternal();
    }

    @Override
    public List<GwtConfigComponent> findComponentConfiguration(GwtXSRFToken xsrfToken, String componentPid)
            throws GwtKuraException {
        checkXSRFToken(xsrfToken);
        return findComponentConfigurationInternal(componentPid);
    }

    @Override
    public void updateComponentConfiguration(GwtXSRFToken xsrfToken, GwtConfigComponent gwtCompConfig)
            throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        ConfigurationService cs = ServiceLocator.getInstance().getService(ConfigurationService.class);
        try {
            // Build the new properties
            Map<String, Object> properties = new HashMap<>();
            ComponentConfiguration currentCC = cs.getComponentConfiguration(gwtCompConfig.getComponentId());

            Map<String, Object> currentConfigProp = currentCC.getConfigurationProperties();
            for (GwtConfigParameter gwtConfigParam : gwtCompConfig.getParameters()) {
                Object objValue;
                Object currentValue = currentConfigProp.get(gwtConfigParam.getId());

                boolean isReadOnly = gwtConfigParam.getMin() != null
                        && gwtConfigParam.getMin().equals(gwtConfigParam.getMax());
                if (isReadOnly) {
                    objValue = currentValue;
                } else {
                    objValue = GwtServerUtil.getUserDefinedObject(gwtConfigParam, currentValue);
                }
                properties.put(gwtConfigParam.getId(), objValue);
            }

            // Force kura.service.pid into properties, if originally present
            if (currentConfigProp.get(KURA_SERVICE_PID) != null) {
                properties.put(KURA_SERVICE_PID, currentConfigProp.get(KURA_SERVICE_PID));
            }
            //
            // apply them
            cs.updateConfiguration(gwtCompConfig.getComponentId(), properties);
            auditLogger.info(
                    "UI Component - Success - Successfully updated component config for user: {}, session {}, component ID: {}",
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId(),
                    gwtCompConfig.getComponentId());
        } catch (KuraException e) {
            auditLogger.warn("UI Component - Failure - Failed to update component config for user: {}, session {}",
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
            KuraExceptionHandler.handle(e);
        }
    }

    @Override
    public void createFactoryComponent(GwtXSRFToken xsrfToken, String factoryPid, String pid) throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);
        internalCreateFactoryComponent(factoryPid, pid, null);
    }

    @Override
    public void createFactoryComponent(GwtXSRFToken xsrfToken, String factoryPid, String pid, String name,
            String componentDescription) throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);
        Map<String, Object> properties = new HashMap<>();
        properties.put(ConfigurationService.KURA_SERVICE_NAME, name);
        properties.put(ConfigurationService.KURA_SERVICE_DESC, componentDescription);
        internalCreateFactoryComponent(factoryPid, pid, properties);
    }

    @Override
    public void createFactoryComponent(GwtXSRFToken xsrfToken, String factoryPid, String pid,
            GwtConfigComponent properties) throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        Map<String, Object> propertiesMap = GwtServerUtil.fillPropertiesFromConfiguration(properties, null);

        internalCreateFactoryComponent(factoryPid, pid, propertiesMap);
    }

    private void internalCreateFactoryComponent(String factoryPid, String pid, Map<String, Object> properties)
            throws GwtKuraException {

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        ConfigurationService cs = ServiceLocator.getInstance().getService(ConfigurationService.class);
        try {
            if (pid == null || pid.trim().isEmpty())
                pid = factoryPid + "-Component-" + new Date().getTime();
            cs.createFactoryConfiguration(factoryPid, pid, properties, false);

            String filterString = "(" + ConfigurationService.KURA_SERVICE_PID + "=" + pid + ")";

            if (!ServiceUtil.waitForService(filterString, SERVICE_WAIT_TIMEOUT, TimeUnit.SECONDS).isPresent()) {
                cs.deleteFactoryConfiguration(pid, false);
                throw new GwtKuraException("Created component did not start in " + SERVICE_WAIT_TIMEOUT + " seconds");
            }
            cs.snapshot();
            auditLogger.info("UI Component - Success - Successfully created component config for user: {}, session {}",
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
        } catch (KuraException e) {
            auditLogger.warn(FAILED_TO_CREATE_COMPONENT_CONFIG_MESSAGE,
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
            throw new GwtKuraException("A component with the same name already exists!");
        } catch (InterruptedException e) {
            auditLogger.warn(FAILED_TO_CREATE_COMPONENT_CONFIG_MESSAGE,
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
            throw new GwtKuraException("Interrupted while waiting for component creation");
        } catch (InvalidSyntaxException e) {
            auditLogger.warn(FAILED_TO_CREATE_COMPONENT_CONFIG_MESSAGE,
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
            throw new GwtKuraException("Invalid value for " + ConfigurationService.KURA_SERVICE_PID + ": " + pid);
        }
    }

    @Override
    public void deleteFactoryConfiguration(GwtXSRFToken xsrfToken, String pid, boolean takeSnapshot)
            throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        ConfigurationService cs = ServiceLocator.getInstance().getService(ConfigurationService.class);

        try {
            cs.deleteFactoryConfiguration(pid, takeSnapshot);
            auditLogger.info("UI Component - Success - Successfully deleted component config for user: {}, session {}",
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
        } catch (KuraException e) {
            auditLogger.warn("UI Component - Failure - Failed to delete component config for user: {}, session {}",
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
            throw new GwtKuraException("Could not delete component configuration!");
        }
    }

    @Override
    public List<String> findFactoryComponents(GwtXSRFToken xsrfToken) throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        ConfigurationService cs = ServiceLocator.getInstance().getService(ConfigurationService.class);
        List<String> result = new ArrayList<>();
        List<String> cloudConnectionFactoriesToBeHidden = new ArrayList<>();

        // finding all wire components to remove from the list as these factory
        // instances
        // are only shown in Kura Wires UI
        List<String> allWireComponents = findWireComponents();

        // find components that declare the
        // kura.ui.factory.hide component property
        List<String> hiddenFactories = findFactoryHideComponents();

        // finding services with kura.service.ui.hide property
        fillCloudConnectionFactoriesToHideList(cloudConnectionFactoriesToBeHidden);

        // get all the factory PIDs tracked by Configuration Service
        result.addAll(cs.getFactoryComponentPids());

        // remove all the wire components and the services to be hidden as these
        // are shown in different UI
        result.removeAll(allWireComponents);
        result.removeAll(cloudConnectionFactoriesToBeHidden);
        result.removeAll(hiddenFactories);

        auditLogger.info(SUCCESSFULLY_LISTED_COMPONENT_CONFIGS_MESSAGE,
                session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
        return result;
    }

    @Override
    public Map<String, String> findFactoryComponentPidNames(GwtXSRFToken xsrfToken) throws GwtKuraException {
        ConfigurationService cs = ServiceLocator.getInstance().getService(ConfigurationService.class);
        List<String> result = findFactoryComponents(xsrfToken);
        return result.stream().collect(Collectors.toMap(id -> id, pid -> {
            ComponentConfigurationImpl cc;
            try {
                cc = (ComponentConfigurationImpl) cs.getDefaultComponentConfiguration(pid);
            } catch (KuraException e) {
                return "error:" + pid;
            }
            OCD ocd = cc.getLocalizedDefinition(LocaleContextHolder.getLocale().getLanguage());
            return ocd.getName();
        }));
    }

    private List<String> findWireComponents() throws GwtKuraException {
        return ServiceLocator.applyToServiceOptionally(WireComponentDefinitionService.class,
                wireComponentDefinitionService -> wireComponentDefinitionService.getComponentDefinitions().stream()
                        .map(WireComponentDefinition::getFactoryPid).collect(Collectors.toList()));
    }

    private List<String> findFactoryHideComponents() throws GwtKuraException {
        final String hideStr = "kura.ui.factory.hide";
        return ServiceLocator.applyToServiceOptionally(ServiceComponentRuntime.class,
                scr -> scr.getComponentDescriptionDTOs().stream().filter(dto -> {

                    if (dto.properties.containsKey(hideStr)) {
                        Boolean ishide = false;
                        Object ishideObj = dto.properties.get(hideStr);
                        if (ishideObj instanceof Boolean)
                            ishide = (Boolean) ishideObj;
                        else
                            ishide = Boolean.parseBoolean(ishideObj.toString());
                        if (ishide == null || ishide.equals(Boolean.TRUE))
                            return true;
                        else
                            return false;
                    } else if (Arrays.asList(dto.serviceInterfaces).contains("org.eclipse.kura.driver.Driver"))
                        return true;
                    else
                        return false;
                }).map(dto -> dto.name).collect(Collectors.toList()));
    }

    private List<ComponentConfiguration> sortConfigurationsByName(List<ComponentConfiguration> configs) {
        Collections.sort(configs, (arg0, arg1) -> {
            String name0;
            int start = arg0.getPid().lastIndexOf('.');
            int substringIndex = start + 1;
            if (start != -1 && substringIndex < arg0.getPid().length()) {
                name0 = arg0.getPid().substring(substringIndex);
            } else {
                name0 = arg0.getPid();
            }

            String name1;
            start = arg1.getPid().lastIndexOf('.');
            substringIndex = start + 1;
            if (start != -1 && substringIndex < arg1.getPid().length()) {
                name1 = arg1.getPid().substring(substringIndex);
            } else {
                name1 = arg1.getPid();
            }
            return name0.compareTo(name1);
        });
        return configs;
    }

    private String stripPidPrefix(String pid) {
        int start = pid.lastIndexOf('.');
        if (start < 0) {
            return pid;
        } else {
            int begin = start + 1;
            if (begin < pid.length()) {
                return pid.substring(begin);
            } else {
                return pid;
            }
        }
    }

    private void fillCloudConnectionFactoriesToHideList(List<String> hidePidsList) throws GwtKuraException {
        ServiceLocator.withAllServiceReferences(CloudConnectionFactory.class, null, (ref, ctx) -> {
            try {
                CloudConnectionFactory cloudServiceFactory = ctx.getService(ref);
                hidePidsList.add(cloudServiceFactory.getFactoryPid());
            } finally {
                ctx.ungetService(ref);
            }
        });
        ServiceLocator.withAllServiceReferences(CloudServiceFactory.class, null, (ref, ctx) -> {
            try {
                CloudServiceFactory cloudServiceFactory = ctx.getService(ref);
                hidePidsList.add(cloudServiceFactory.getFactoryPid());
            } finally {
                ctx.ungetService(ref);
            }
        });
    }

    private List<GwtConfigComponent> findFilteredComponentConfigurationsInternal() throws GwtKuraException {
        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        ConfigurationService cs = ServiceLocator.getInstance().getService(ConfigurationService.class);
        List<GwtConfigComponent> gwtConfigs = new ArrayList<>();
        try {

            List<ComponentConfiguration> configs = cs.getComponentConfigurations();
            sortConfigurationsByName(configs);

            for (ComponentConfiguration config : configs) {
                GwtConfigComponent gwtConfigComponent = createMetatypeOnlyGwtComponentConfiguration(config);
                if (gwtConfigComponent != null) {
                    gwtConfigs.add(gwtConfigComponent);
                }
            }
        } catch (Exception e) {
            auditLogger.warn(FAILED_TO_LIST_COMPONENT_CONFIGS_MESSAGE,
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
            KuraExceptionHandler.handle(e);
        }

        auditLogger.info(SUCCESSFULLY_LISTED_COMPONENT_CONFIGS_MESSAGE,
                session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
        return gwtConfigs;
    }

    private List<GwtConfigComponent> findComponentConfigurationInternal(String componentPid) throws GwtKuraException {
        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        ConfigurationService cs = ServiceLocator.getInstance().getService(ConfigurationService.class);
        List<GwtConfigComponent> gwtConfigs = new ArrayList<>();
        try {
            ComponentConfiguration config = cs.getComponentConfiguration(componentPid);
            GwtConfigComponent gwtConfigComponent = null;
            if (config != null) {
                gwtConfigComponent = createMetatypeOnlyGwtComponentConfiguration(config);
            }
            GwtConfigComponent fullGwtConfigComponent = null;
            if (gwtConfigComponent != null) {
                fullGwtConfigComponent = addNonMetatypeProperties(gwtConfigComponent, config);
            }
            if (fullGwtConfigComponent != null) {
                gwtConfigs.add(fullGwtConfigComponent);
            }
        } catch (Exception e) {
            auditLogger.warn(FAILED_TO_LIST_COMPONENT_CONFIG_MESSAGE,
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
            KuraExceptionHandler.handle(e);
        }

        auditLogger.info(SUCCESSFULLY_LISTED_COMPONENT_CONFIG_MESSAGE,
                session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
        return gwtConfigs;
    }

    private List<GwtConfigComponent> findFilteredComponentConfigurationInternal(String componentPid)
            throws GwtKuraException {
        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        ConfigurationService cs = ServiceLocator.getInstance().getService(ConfigurationService.class);
        List<GwtConfigComponent> gwtConfigs = new ArrayList<>();
        try {
            ComponentConfiguration config = cs.getComponentConfiguration(componentPid);

            if (config != null) {
                GwtConfigComponent gwtConfigComponent = createMetatypeOnlyGwtComponentConfiguration(config);
                gwtConfigs.add(gwtConfigComponent);
            }
        } catch (Exception e) {
            auditLogger.warn(FAILED_TO_LIST_COMPONENT_CONFIG_MESSAGE,
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
            KuraExceptionHandler.handle(e);
        }

        auditLogger.info(SUCCESSFULLY_LISTED_COMPONENT_CONFIG_MESSAGE,
                session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
        return gwtConfigs;
    }

    private GwtConfigComponent addNonMetatypeProperties(GwtConfigComponent baseGwtConfig,
            ComponentConfiguration config) {
        GwtConfigComponent gwtConfigComponent = null;
        OCD ocd = config.getLocalizedDefinition(LocaleContextHolder.getLocale().getLanguage());
        if (ocd != null && baseGwtConfig != null) {
            gwtConfigComponent = new GwtConfigComponent();

            gwtConfigComponent.setComponentDescription(baseGwtConfig.getComponentDescription());
            gwtConfigComponent.setComponentId(baseGwtConfig.getComponentId());
            gwtConfigComponent.setComponentIcon(baseGwtConfig.getComponentIcon());
            gwtConfigComponent.setComponentName(baseGwtConfig.getComponentName());
            gwtConfigComponent.setProperties(baseGwtConfig.getProperties());

            List<GwtConfigParameter> gwtParams = new ArrayList<>();
            gwtConfigComponent.setParameters(gwtParams);

            List<GwtConfigParameter> nonMetatypeConfigParameters = new ArrayList<>();

            if (config.getConfigurationProperties() != null) {

                List<GwtConfigParameter> nonMetatypeProps = getNonMetatypeProperties(config);
                nonMetatypeConfigParameters.addAll(nonMetatypeProps);
            }
            gwtConfigComponent.setParameters(nonMetatypeConfigParameters);
        }
        return gwtConfigComponent;
    }

    private List<GwtConfigComponent> findComponentConfigurationsInternal() throws GwtKuraException {
        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        ConfigurationService cs = ServiceLocator.getInstance().getService(ConfigurationService.class);
        List<GwtConfigComponent> gwtConfigs = new ArrayList<>();
        try {

            List<ComponentConfiguration> configs = cs.getComponentConfigurations();
            sortConfigurationsByName(configs);

            for (ComponentConfiguration config : configs) {
                GwtConfigComponent gwtConfigComponent = createMetatypeOnlyGwtComponentConfiguration(config);
                gwtConfigs.add(gwtConfigComponent);
            }
        } catch (Exception e) {
            auditLogger.warn(FAILED_TO_LIST_COMPONENT_CONFIG_MESSAGE,
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
            KuraExceptionHandler.handle(e);
        }

        auditLogger.info(SUCCESSFULLY_LISTED_COMPONENT_CONFIG_MESSAGE,
                session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId());
        return gwtConfigs;
    }

    private GwtConfigComponent createMetatypeOnlyGwtComponentConfigurationInternal(ComponentConfiguration config) {
        GwtConfigComponent gwtConfig = null;

        OCD ocd = config.getLocalizedDefinition(LocaleContextHolder.getLocale().getLanguage());
        if (ocd != null) {

            gwtConfig = new GwtConfigComponent();
            gwtConfig.setComponentId(config.getPid());

            Map<String, Object> props = config.getConfigurationProperties();
            if (props != null && props.get(DRIVER_PID) != null) {
                gwtConfig.set(DRIVER_PID, props.get(DRIVER_PID));
            }

            if (props != null && props.get(SERVICE_FACTORY_PID) != null) {
                String name = ocd.getName();
                if (props.containsKey(ConfigurationService.KURA_SERVICE_NAME))
                    name = (String) props.get(ConfigurationService.KURA_SERVICE_NAME);
                if (name == null || name.equals(""))
                    name = stripPidPrefix(config.getPid());
                gwtConfig.setComponentName(name);
                gwtConfig.setFactoryComponent(true);
                gwtConfig.setFactoryPid(String.valueOf(props.get(ConfigurationAdmin.SERVICE_FACTORYPID)));
            } else {
                gwtConfig.setComponentName(ocd.getName());
                gwtConfig.setFactoryComponent(false);
            }
            String descCription = "";
            if (props.containsKey(ConfigurationService.KURA_SERVICE_DESC))
                descCription = (String) props.get(ConfigurationService.KURA_SERVICE_DESC);
            if (descCription == null || descCription.equals(""))
                gwtConfig.setComponentDescription(ocd.getDescription());
            else
                gwtConfig.setComponentDescription(descCription);
            if (ocd.getIcon() != null && !ocd.getIcon().isEmpty()) {
                Icon icon = ocd.getIcon().get(0);
                gwtConfig.setComponentIcon(icon.getResource());
            }

            List<GwtConfigParameter> gwtParams = new ArrayList<>();
            gwtConfig.setParameters(gwtParams);

            if (config.getConfigurationProperties() != null) {
                List<GwtConfigParameter> metatypeProps = getADProperties(config);
                gwtParams.addAll(metatypeProps);
            }
        }
        return gwtConfig;
    }

    private GwtConfigComponent createMetatypeOnlyGwtComponentConfiguration(ComponentConfiguration config)
            throws GwtKuraException {
        final GwtConfigComponent gwtConfig = createMetatypeOnlyGwtComponentConfigurationInternal(config);
        if (gwtConfig != null) {
            gwtConfig.setIsWireComponent(ServiceLocator.applyToServiceOptionally(WireHelperService.class,
                    wireHelperService -> wireHelperService.getServicePid(gwtConfig.getComponentName()) != null));
        }
        return gwtConfig;
    }

    private List<GwtConfigParameter> getNonMetatypeProperties(ComponentConfiguration config) {
        List<GwtConfigParameter> gwtParams = new ArrayList<>();
        for (Map.Entry<String, Object> entry : config.getConfigurationProperties().entrySet()) {
            GwtConfigParameter gwtParam = new GwtConfigParameter();
            gwtParam.setId(entry.getKey());
            Object value = entry.getValue();

            // this could be an array value
            if (value instanceof Object[]) {
                Object[] objValues = (Object[]) value;
                List<String> strValues = new ArrayList<>();
                for (Object v : objValues) {
                    if (v != null) {
                        strValues.add(String.valueOf(v));
                    }
                }
                gwtParam.setValues(strValues.toArray(new String[] {}));
            } else if (value != null) {
                gwtParam.setValue(String.valueOf(value));
            }

            gwtParams.add(gwtParam);
        }
        return gwtParams;
    }

    private List<GwtConfigParameter> getADProperties(ComponentConfiguration config) {
        List<GwtConfigParameter> gwtParams = new ArrayList<>();
        OCD ocd = config.getLocalizedDefinition(LocaleContextHolder.getLocale().getLanguage());
        for (AD ad : ocd.getAD()) {
            GwtConfigParameter gwtParam = new GwtConfigParameter();
            gwtParam.setId(ad.getId());
            gwtParam.setName(ad.getName());
            gwtParam.setDescription(ad.getDescription());
            gwtParam.setType(GwtConfigParameterType.valueOf(ad.getType().name()));
            gwtParam.setRequired(ad.isRequired());
            gwtParam.setCardinality(ad.getCardinality());
            if (ad.getOption() != null && !ad.getOption().isEmpty()) {
                Map<String, String> options = new HashMap<>();
                for (Option option : ad.getOption()) {
                    options.put(option.getLabel(), option.getValue());
                }
                gwtParam.setOptions(options);
            }
            gwtParam.setMin(ad.getMin());
            gwtParam.setMax(ad.getMax());

            // handle the value based on the cardinality of the attribute
            int cardinality = ad.getCardinality();
            Object value = config.getConfigurationProperties().get(ad.getId());
            if (value != null) {
                if (cardinality == 0 || cardinality == 1 || cardinality == -1) {
                    if (gwtParam.getType().equals(GwtConfigParameterType.PASSWORD)) {
                        gwtParam.setValue(GwtServerUtil.PASSWORD_PLACEHOLDER);
                    } else {
                        gwtParam.setValue(String.valueOf(value));
                    }
                } else {
                    // this could be an array value
                    if (value instanceof Object[]) {
                        Object[] objValues = (Object[]) value;
                        List<String> strValues = new ArrayList<>();
                        for (Object v : objValues) {
                            if (v != null) {
                                if (gwtParam.getType().equals(GwtConfigParameterType.PASSWORD)) {
                                    strValues.add(GwtServerUtil.PASSWORD_PLACEHOLDER);
                                } else {
                                    strValues.add(String.valueOf(v));
                                }
                            }
                        }
                        gwtParam.setValues(strValues.toArray(new String[] {}));
                    }
                }
            }
            gwtParams.add(gwtParam);
        }
        return gwtParams;
    }

    @Override
    public boolean updateProperties(GwtXSRFToken xsrfToken, String pid, Map<String, Object> properties)
            throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        final ConfigurationAdmin configAdmin = ServiceLocator.getInstance().getService(ConfigurationAdmin.class);
        final WireHelperService wireHelperService = ServiceLocator.getInstance().getService(WireHelperService.class);
        try {
            final String servicePid = wireHelperService.getServicePid(pid);
            Configuration conf = null;
            if (servicePid != null) {
                conf = configAdmin.getConfiguration(servicePid);
            }
            Dictionary<String, Object> props = null;
            if (conf != null) {
                props = conf.getProperties();
            }
            if (props == null) {
                props = new Hashtable<>();
            }
            for (Map.Entry<String, Object> entry : properties.entrySet()) {
                String key = entry.getKey();
                Object value = entry.getValue();
                props.put(key, value != null ? value : "");
            }
            if (conf != null) {
                conf.update(props);
            }
        } catch (IOException e) {
            auditLogger.info(
                    "UI Component - Failure - Failed to update component config for user: {}, session: {}, pid: {}",
                    session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId(), pid);
            return false;
        }

        auditLogger.info(
                "UI Component - Success - Successfully updated component config for user: {}, session: {}, pid: {}",
                session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId(), pid);

        return true;
    }

    @Override
    public Map<String, String> getPidNamesFromTarget(GwtXSRFToken xsrfToken, String pid, String targetRef)
            throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        Map<String, String> result = new HashMap<>();

        final BundleContext context = FrameworkUtil.getBundle(GwtWireGraphService.class).getBundleContext();
        ServiceReference<ServiceComponentRuntime> scrServiceRef = context
                .getServiceReference(ServiceComponentRuntime.class);
        try {
            final ServiceComponentRuntime scrService = context.getService(scrServiceRef);

            final Set<String> referenceInterfaces = scrService.getComponentDescriptionDTOs().stream().map(component -> {
                ReferenceDTO[] references = component.references;
                for (ReferenceDTO reference : references) {
                    if (targetRef.equals(reference.name)) {
                        return reference.interfaceName;
                    }
                }
                return null;
            }).filter(Objects::nonNull).collect(Collectors.toSet());

            referenceInterfaces.forEach(reference -> {
                try {
                    ServiceReference<?>[] serviceReferences = context.getServiceReferences(reference, null);

                    for (Object serviceReferenceObject : serviceReferences) {
                        if (serviceReferenceObject instanceof ServiceReference) {
                            ServiceReference<?> cloudServiceReference = (ServiceReference<?>) serviceReferenceObject;
                            String servicePid = (String) cloudServiceReference.getProperty(KURA_SERVICE_PID);
                            String serviceName = (String) cloudServiceReference
                                    .getProperty(ConfigurationService.KURA_SERVICE_NAME);
                            result.put(servicePid, serviceName);
                            ServiceLocator.getInstance().ungetService(cloudServiceReference);
                        }
                    }
                } catch (InvalidSyntaxException e) {

                }
            });

        } finally {
            context.ungetService(scrServiceRef);
        }

        auditLogger.info(SUCCESSFULLY_LISTED_PIDS_FROM_TARGET_MESSAGE,
                session.getAttribute(Attributes.AUTORIZED_USER.getValue()), session.getId(), pid);
        return result;
    }

}
