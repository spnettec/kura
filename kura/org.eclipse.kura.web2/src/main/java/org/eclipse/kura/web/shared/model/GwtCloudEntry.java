/*******************************************************************************
 * Copyright (c) 2018, 2020 Eurotech and/or its affiliates and others
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

import org.eclipse.kura.configuration.ConfigurationService;

public class GwtCloudEntry extends KuraBaseModel implements Serializable {

    /**
     *
     */
    private static final long serialVersionUID = -8526545631929926543L;

    public String getPid() {
        return get("pid");
    }

    public String getName() {
        return get(ConfigurationService.KURA_SERVICE_NAME);
    }

    public String getCloudName() {
        return get(ConfigurationService.KURA_CLOUD_FACTORY_NAME);
    }

    public void setPid(String pid) {
        set("pid", pid);
    }

    public void setName(String name) {
        set(ConfigurationService.KURA_SERVICE_NAME, name);
    }

    public void setCloudName(String name) {
        set(ConfigurationService.KURA_CLOUD_FACTORY_NAME, name);
    }

    public void setComponentDescription(String componentDescription) {
        set(ConfigurationService.KURA_SERVICE_DESC, componentDescription);
    }

    public String getComponentDescription() {
        return get(ConfigurationService.KURA_SERVICE_DESC);
    }

    public String getFactoryPid() {
        return get("factoryPid");
    }

    public String getFactoryName() {
        return get("factoryName");
    }

    public void setFactoryPid(final String factoryPid) {
        set("factoryPid", factoryPid);
    }

    public void setFactoryName(final String factoryName) {
        set("factoryName", factoryName);
    }

    public String getDefaultFactoryPid() {
        return get("defaultFactoryPid");
    }

    public void setDefaultFactoryPid(final String defaultFactoryPid) {
        set("defaultFactoryPid", defaultFactoryPid);
    }

    public String getDefaultFactoryPidRegex() {
        return get("defaultFactoryPidRegex");
    }

    public void setDefaultFactoryPidRegex(final String defaultFactoryPidRegex) {
        set("defaultFactoryPidRegex", defaultFactoryPidRegex);
    }

    @Override
    public int hashCode() {
        final String pid = getPid();
        final int prime = 31;
        int result = 1;
        result = prime * result + ((pid == null) ? 0 : pid.hashCode());
        return result;
    }

    @Override
    public boolean equals(Object obj) {
        if (this == obj)
            return true;
        if (obj == null)
            return false;
        if (getClass() != obj.getClass())
            return false;
        GwtCloudEntry other = (GwtCloudEntry) obj;

        final String pid = getPid();
        final String otherPid = other.getPid();

        if (pid == null) {
            if (otherPid != null)
                return false;
        } else if (!pid.equals(otherPid))
            return false;
        return true;
    }

}
