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
 *******************************************************************************/
package org.eclipse.kura.web.shared.model;

import java.io.Serializable;
import java.util.ArrayList;
import java.util.List;

import org.eclipse.kura.configuration.ConfigurationService;

public class GwtConfigComponent extends KuraBaseModel implements Serializable {

    private static final long serialVersionUID = -6388356998309026758L;

    private List<GwtConfigParameter> m_parameters;
    
    public GwtConfigComponent() {
        this.m_parameters = new ArrayList<>();
    }

    public GwtConfigComponent(GwtConfigComponent other) {
        this();
        this.data.putAll(other.data);
        for (GwtConfigParameter parameter : other.m_parameters) {
            this.m_parameters.add(new GwtConfigParameter(parameter));
        }
    }

    public String getComponentDescription() {
        return this.get(ConfigurationService.KURA_SERVICE_DESC);
    }

    public String getComponentIcon() {
        return this.get("componentIcon");
    }

    public String getComponentId() {
        return this.get("componentId");
    }

    public String getComponentName() {
        return this.get(ConfigurationService.KURA_SERVICE_NAME);
    }

    public String getFactoryId() {
        return this.get("factoryPid");
    }

    public GwtConfigParameter getParameter(final String id) {
        for (final GwtConfigParameter param : this.m_parameters) {
            if (id.equals(param.getId())) {
                return param;
            }
        }
        return null;
    }

    public List<GwtConfigParameter> getParameters() {
        return this.m_parameters;
    }

    public boolean isFactoryComponent() {
        if (this.get("factoryComponent") != null) {
            return this.get("factoryComponent");
        }
        return false;
    }

    public boolean isWireComponent() {
        if (this.get("isWireComponent") != null) {
            return this.get("isWireComponent");
        }
        return false;
    }

    public boolean isDriver() {
        if (this.get("isDriver") != null) {
            return this.get("isDriver");
        }
        return false;
    }

    public void setComponentDescription(final String componentDescription) {
        set(ConfigurationService.KURA_SERVICE_DESC, componentDescription);
    }

    public void setComponentIcon(final String componentIcon) {
        set("componentIcon", componentIcon);
    }

    public void setComponentId(final String componentId) {
        set("componentId", componentId);
    }

    public void setComponentName(final String componentName) {
        set(ConfigurationService.KURA_SERVICE_NAME, componentName);
    }

    public void setFactoryComponent(final boolean isFactory) {
        set("factoryComponent", isFactory);
    }

    public void setFactoryPid(final String factoryPid) {
        set("factoryPid", factoryPid);
    }

    public void setParameters(final List<GwtConfigParameter> parameters) {
        this.m_parameters = parameters;
    }

    public void setIsWireComponent(final boolean isWireComponent) {
        set("isWireComponent", isWireComponent);
    }

    public void setIsDriver(final boolean isDriver) {
        set("isDriver", isDriver);
    }

    public boolean isValid() {
        return getComponentId() != null && getFactoryId() != null && getParameters() != null;
    }

    public String getParameterValue(String id) {
        for (GwtConfigParameter param : this.m_parameters) {
            if (id.equals(param.getId())) {
                return param.getValue();
            }
        }
        return null;
    }

}
