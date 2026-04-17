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
 *******************************************************************************/
package org.eclipse.kura.core.comm;

import java.io.IOException;

import org.eclipse.kura.comm.CommConnection;
import org.eclipse.kura.comm.CommURI;

public class CommConnectionFactory implements org.eclipse.kura.comm.CommConnectionFactory {

    @Override
    public CommConnection createConnection(final CommURI uri) throws IOException {
        return new CommConnectionImpl(uri);
    }
}
