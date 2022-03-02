/*******************************************************************************
 * Copyright (c) 2015 EclipseSource and others.
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 * Contributors:
 *    Holger Staudacher - initial API and implementation, ongoing development
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
