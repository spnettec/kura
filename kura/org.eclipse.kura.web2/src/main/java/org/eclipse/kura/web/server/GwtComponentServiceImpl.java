/*******************************************************************************
 * Copyright (c) 2011, 2021 Eurotech and/or its affiliates and others
 * 
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 * 
 * SPDX-License-Identifier: EPL-2.0
 * 
 * Contributors:
 *  Eurotech
 *  Red Hat Inc
 *  Amit Kumar Mondal
 *******************************************************************************/
package org.eclipse.kura.web.server;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.configuration.metatype.OCD;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.locale.LocaleContextHolder;
import org.eclipse.kura.web.server.util.GwtComponentServiceInternal;
import org.eclipse.kura.web.server.util.ServiceLocator;
import org.eclipse.kura.web.shared.GwtKuraException;
import org.eclipse.kura.web.shared.model.GwtConfigComponent;
import org.eclipse.kura.web.shared.model.GwtXSRFToken;
import org.eclipse.kura.web.shared.service.GwtComponentService;

public class GwtComponentServiceImpl extends OsgiRemoteServiceServlet implements GwtComponentService {

    private static final long serialVersionUID = -4176701819112753800L;

    @Override
    public List<String> findTrackedPids(GwtXSRFToken xsrfToken) throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        return GwtComponentServiceInternal.findTrackedPids();
    }

    @Override
    public List<GwtConfigComponent> findFilteredComponentConfigurations(GwtXSRFToken xsrfToken)
            throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        return GwtComponentServiceInternal.findFilteredComponentConfigurations();
    }

    @Override
    public List<GwtConfigComponent> findComponentConfigurations(GwtXSRFToken xsrfToken, String osgiFilter)
            throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        return GwtComponentServiceInternal.findComponentConfigurations(osgiFilter);
    }

    @Override
    public List<GwtConfigComponent> findFilteredComponentConfiguration(GwtXSRFToken xsrfToken, String componentPid)
            throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        return GwtComponentServiceInternal.findFilteredComponentConfiguration(componentPid);
    }

    @Override
    public List<GwtConfigComponent> findComponentConfigurations(GwtXSRFToken xsrfToken) throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        return GwtComponentServiceInternal.findComponentConfigurations();
    }

    @Override
    public List<GwtConfigComponent> findComponentConfiguration(GwtXSRFToken xsrfToken, String componentPid)
            throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        return GwtComponentServiceInternal.findComponentConfiguration(componentPid);
    }

    @Override
    public void updateComponentConfiguration(GwtXSRFToken xsrfToken, GwtConfigComponent gwtCompConfig)
            throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        updateComponentConfigurationInternal(gwtCompConfig);
    }

    @Override
    public void updateComponentConfigurations(GwtXSRFToken xsrfToken, List<GwtConfigComponent> gwtCompConfigs)
            throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        for (GwtConfigComponent gwtCompConfig : gwtCompConfigs) {
            updateComponentConfigurationInternal(gwtCompConfig);
        }

    }

    @Override
    public void createFactoryComponent(GwtXSRFToken xsrfToken, String factoryPid, String pid,
            GwtConfigComponent properties) throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        GwtComponentServiceInternal.createFactoryComponent(factoryPid, pid, properties);
    }

    @Override
    public void deleteFactoryConfiguration(GwtXSRFToken xsrfToken, String pid, boolean takeSnapshot)
            throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        GwtComponentServiceInternal.deleteFactoryConfiguration(pid, takeSnapshot);
    }

    @Override
    public List<String> findFactoryComponents(GwtXSRFToken xsrfToken) throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        return GwtComponentServiceInternal.findFactoryComponents();
    }

    @Override
    public boolean updateProperties(GwtXSRFToken xsrfToken, String pid, Map<String, Object> properties)
            throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        return GwtComponentServiceInternal.updateProperties(pid, properties);
    }

    @Override
    public List<String> getDriverFactoriesList(GwtXSRFToken xsrfToken) throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        return GwtComponentServiceInternal.getDriverFactoriesList();
    }

    @Override
    public Map<String, String> getPidNamesFromTarget(GwtXSRFToken xsrfToken, String pid, String targetRef)
            throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        return GwtComponentServiceInternal.getPidsFromTarget(pid, targetRef);
    }

    @Override
    public void createFactoryComponent(GwtXSRFToken xsrfToken, String factoryPid, String pid, String name,
            String componentDescription) throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        Map<String, Object> properties = new HashMap<>();
        properties.put(ConfigurationService.KURA_SERVICE_NAME, name);
        properties.put(ConfigurationService.KURA_SERVICE_DESC, componentDescription);
        GwtComponentServiceInternal.createFactoryComponent(factoryPid, pid, properties);

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

    private void updateComponentConfigurationInternal(GwtConfigComponent gwtCompConfig) throws GwtKuraException {
        GwtComponentServiceInternal.updateComponentConfiguration(gwtCompConfig);
    }
}
