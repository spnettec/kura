/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.testing.configuration.fixture;

import java.util.Map;

import org.eclipse.kura.configuration.ConfigurableComponent;

/** A real SCR component that exposes the properties delivered by ConfigAdmin. */
public class LegacyConfigurationComponent implements ConfigurableComponent {
    private volatile Map<String, Object> properties = Map.of();

    public void updated(Map<String, Object> properties) {
        this.properties = Map.copyOf(properties);
    }

    public Map<String, Object> getProperties() {
        return this.properties;
    }
}
