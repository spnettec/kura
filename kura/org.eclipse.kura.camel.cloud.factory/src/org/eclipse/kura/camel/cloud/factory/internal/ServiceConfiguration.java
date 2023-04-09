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

import java.util.Objects;

/**
 * The configuration of a Camel based {@link org.eclipse.kura.cloud.CloudService} instance
 */
public class ServiceConfiguration {

    private String xml;
    private String initCode;
    private String scriptEngineName;
    private boolean enableJmx;

    /**
     * Set the router XML
     *
     * @param xml
     *            must not be {@code null}
     */
    public void setXml(String xml) {
        this.xml = xml;
    }

    public String getXml() {
        return this.xml;
    }

    public void setInitCode(String initCode) {
        this.initCode = initCode;
    }

    public String getInitCode() {
        return this.initCode;
    }

    public void setEnableJmx(boolean enableJmx) {
        this.enableJmx = enableJmx;
    }

    public String getScriptEngineName() {
        return scriptEngineName;
    }

    public void setScriptEngineName(String scriptEngineName) {
        this.scriptEngineName = scriptEngineName;
    }

    public boolean isEnableJmx() {
        return this.enableJmx;
    }

    public boolean isValid() {
        if (this.xml == null || this.xml.trim().isEmpty()) {
            return false;
        }
        return true;
    }

    @Override
    public int hashCode() {
        return Objects.hash(enableJmx, initCode, scriptEngineName, xml);
    }

    @Override
    public boolean equals(Object obj) {
        if (this == obj) {
            return true;
        }
        if (obj == null) {
            return false;
        }
        if (getClass() != obj.getClass()) {
            return false;
        }
        ServiceConfiguration other = (ServiceConfiguration) obj;
        return enableJmx == other.enableJmx && Objects.equals(initCode, other.initCode)
                && Objects.equals(scriptEngineName, other.scriptEngineName) && Objects.equals(xml, other.xml);
    }

}
