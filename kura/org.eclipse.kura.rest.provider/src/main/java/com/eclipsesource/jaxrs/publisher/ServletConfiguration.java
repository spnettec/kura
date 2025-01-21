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

import java.util.Dictionary;

import org.osgi.service.http.HttpContext;
import org.osgi.service.http.HttpService;

/**
 * <p>
 * Service that allows contribution of initial parameters and HttpContext for the Jersey servlet.
 * Only the first tracked service implementing this interface will be used.
 * </p>
 *
 * @since 4.2
 */
public interface ServletConfiguration {

    /**
     * <p>
     * Returns an HttpContext or <code>null</code> for the given httpService and rootPath.
     * </p>
     *
     * @param httpService
     *                        the {@link HttpService} to configure the servlet for.
     * @param rootPath
     *                        the configured root path of the servlet to register.
     * @return the {@link HttpContext} to use for the servlet registration.
     */
    HttpContext getHttpContext(HttpService httpService, String rootPath);

    /**
     * <p>
     * Returns initial parameters or <code>null</code> for the given httpService and rootPath.
     * </p>
     *
     * @param httpService
     *                        the {@link HttpService} to configure the servlet for.
     * @param rootPath
     *                        the configured root path of the servlet to register.
     * @return the init properties to use for the servlet registration.
     */
    Dictionary<String, String> getInitParams(HttpService httpService, String rootPath);

}
