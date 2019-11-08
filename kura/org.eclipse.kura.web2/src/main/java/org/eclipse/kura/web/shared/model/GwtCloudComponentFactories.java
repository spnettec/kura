/*******************************************************************************
 * Copyright (c) 2018 Eurotech and/or its affiliates
 *
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 *******************************************************************************/
package org.eclipse.kura.web.shared.model;

import java.io.Serializable;
import java.util.List;
import java.util.Map;

public class GwtCloudComponentFactories implements Serializable {

    private Map<String, String> cloudConnectionFactoryPidNames;

    private List<GwtCloudEntry> pubSubFactories;

    /**
     * 
     */
    private static final long serialVersionUID = -1968801905394521346L;

    public GwtCloudComponentFactories() {
    }

    public Map<String, String> getCloudConnectionFactoryPidNames() {
        return cloudConnectionFactoryPidNames;
    }

    public void setCloudConnectionFactoryPidNames(final Map<String, String> cloudConnectionFactoryPidNameNames) {
        this.cloudConnectionFactoryPidNames = cloudConnectionFactoryPidNameNames;
    }

    public List<GwtCloudEntry> getPubSubFactories() {
        return pubSubFactories;
    }

    public void setPubSubFactories(final List<GwtCloudEntry> pubSubFactories) {
        this.pubSubFactories = pubSubFactories;
    }

}
