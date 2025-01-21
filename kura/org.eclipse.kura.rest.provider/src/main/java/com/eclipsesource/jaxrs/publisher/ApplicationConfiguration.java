/*******************************************************************************
 * Copyright (c) 2021, 2025 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 ******************************************************************************/
package com.eclipsesource.jaxrs.publisher;

import java.util.Map;

/**
 * <p>
 * Service that allows configuration of the JAX-RS Application. Multiple registrations will be tracked.
 * </p>
 *
 * @since 4.3
 */
public interface ApplicationConfiguration {

    /**
     * <p>
     * Will be called before the JAX-RS Application is registered. Please note that
     * one {@link ApplicationConfiguration} can overwrite the values of other {@link ApplicationConfiguration}s. It
     * depends on the order they are available in the OSGi container.
     * </p>
     *
     * @see getProperties()
     */
    Map<String, Object> getProperties();

}
