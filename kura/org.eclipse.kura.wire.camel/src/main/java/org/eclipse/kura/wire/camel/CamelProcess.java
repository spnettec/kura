/*******************************************************************************
 * Copyright (c) 2018, 2020 Red Hat Inc and others
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
package org.eclipse.kura.wire.camel;

import static org.apache.camel.impl.engine.DefaultFluentProducerTemplate.on;

import org.apache.camel.CamelContext;
import org.eclipse.kura.wire.WireEmitter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class CamelProcess extends AbstractReceiverWireComponent implements WireEmitter {

    private static final Logger logger = LoggerFactory.getLogger(CamelProcess.class);

    @Override
    protected void processReceive(final CamelContext context, final String endpointUri, final Object envelope)
            throws Exception {

        final Object result = on(context) //
                .withBody(envelope) //
                .to(endpointUri) //
                .request(Object.class);

        logger.debug("Result: {}", result);

        if (result != null) {
            this.wireSupport.emit(result);
        }
    }

}
