/*******************************************************************************
 * Copyright (c) 2011, 2020 Eurotech and/or its affiliates and others
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

import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpSession;

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

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        return GwtComponentServiceInternal.findFilteredComponentConfigurations(session);
    }

    @Override
    public List<GwtConfigComponent> findComponentConfigurations(GwtXSRFToken xsrfToken, String osgiFilter)
            throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        return GwtComponentServiceInternal.findComponentConfigurations(session, osgiFilter);
    }

    @Override
    public List<GwtConfigComponent> findFilteredComponentConfiguration(GwtXSRFToken xsrfToken, String componentPid)
            throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        return GwtComponentServiceInternal.findFilteredComponentConfiguration(session, componentPid);
    }

    @Override
    public List<GwtConfigComponent> findComponentConfigurations(GwtXSRFToken xsrfToken) throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        return GwtComponentServiceInternal.findComponentConfigurations(session);
    }

    @Override
    public List<GwtConfigComponent> findComponentConfiguration(GwtXSRFToken xsrfToken, String componentPid)
            throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        return GwtComponentServiceInternal.findComponentConfiguration(session, componentPid);
    }

    @Override
    public void updateComponentConfiguration(GwtXSRFToken xsrfToken, GwtConfigComponent gwtCompConfig)
            throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        GwtComponentServiceInternal.updateComponentConfiguration(session, gwtCompConfig);
    }

    @Override
    public void createFactoryComponent(GwtXSRFToken xsrfToken, String factoryPid, String pid,
            GwtConfigComponent properties) throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        GwtComponentServiceInternal.createFactoryComponent(session, factoryPid, pid, properties);
    }

    @Override
    public void deleteFactoryConfiguration(GwtXSRFToken xsrfToken, String pid, boolean takeSnapshot)
            throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        GwtComponentServiceInternal.deleteFactoryConfiguration(session, pid, takeSnapshot);
    }

    @Override
    public List<String> findFactoryComponents(GwtXSRFToken xsrfToken) throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        return GwtComponentServiceInternal.findFactoryComponents(session);
    }

    @Override
    public boolean updateProperties(GwtXSRFToken xsrfToken, String pid, Map<String, Object> properties)
            throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        return GwtComponentServiceInternal.updateProperties(session, pid, properties);
    }

    @Override
    public List<String> getDriverFactoriesList(GwtXSRFToken xsrfToken) throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        return GwtComponentServiceInternal.getDriverFactoriesList(session);
    }

    @Override
    public Map<String, String> getPidNamesFromTarget(GwtXSRFToken xsrfToken, String pid, String targetRef)
            throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        return GwtComponentServiceInternal.getPidNamesFromTarget(session, pid, targetRef);
    }

    @Override
    public void createFactoryComponent(GwtXSRFToken xsrfToken, String factoryPid, String pid, String name,
            String componentDescription) throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        final HttpServletRequest request = getThreadLocalRequest();
        final HttpSession session = request.getSession(false);

        Map<String, Object> properties = new HashMap<>();
        properties.put(ConfigurationService.KURA_SERVICE_NAME, name);
        properties.put(ConfigurationService.KURA_SERVICE_DESC, componentDescription);
        GwtComponentServiceInternal.createFactoryComponent(session, factoryPid, pid, properties);

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

}
