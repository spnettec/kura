/*******************************************************************************
 * Copyright (c) 2026 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.comm;

import java.io.IOException;

import org.osgi.annotation.versioning.ProviderType;

/**
 * Factory service for opening serial connections managed by Kura.
 *
 * @noimplement This interface is not intended to be implemented by clients.
 */
@ProviderType
public interface CommConnectionFactory {

    /**
     * Opens a serial connection using the supplied URI configuration.
     *
     * @param uri
     *            the serial port configuration
     * @return an open serial connection
     * @throws IOException
     *             if the serial port cannot be opened or configured
     */
    CommConnection createConnection(CommURI uri) throws IOException;
}
