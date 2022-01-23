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
import org.apache.camel.FluentProducerTemplate;
import org.eclipse.kura.wire.WireEnvelope;

public class CamelProduce extends AbstractReceiverWireComponent {

    private FluentProducerTemplate template = null;

    @Override
    protected void processReceive(final CamelContext context, final String endpointUri, final WireEnvelope envelope)
            throws Exception {
        if (template == null) {
            template = on(context);
        } else {
            if (template.getCamelContext() != context) {
                template.close();
                template = on(context);
            }
        }
        template //
                .withBody(envelope) //
                .to(endpointUri) //
                .asyncSend();
    }

    @Override
    protected void deactivate() {
        super.deactivate();
        if (template != null) {
            try {
                template.close();
            } catch (Exception e) {
            } finally {
                template = null;
            }
        }
    }

}
