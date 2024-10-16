/*******************************************************************************
 * Copyright (c) 2017, 2020 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.wire.graph;

import java.util.List;

import org.eclipse.kura.wire.WireSupport;
import org.osgi.annotation.versioning.ProviderType;

/**
 * This interface extends {@link WireSupport} to provide multi-port support in Wires.
 *
 * @since 1.4
 */
@ProviderType
public interface MultiportWireSupport extends WireSupport {

    /**
     * Returns the list of EmitterPorts of a Wire Component
     *
     * @return a list of {@link EmitterPort}
     */
    public List<EmitterPort> getEmitterPorts();

    /**
     * Returns the list of ReceiverPorts associated to a Wire Component
     *
     * @return a list of {@link ReceiverPort}
     */
    public List<ReceiverPort> getReceiverPorts();

}
