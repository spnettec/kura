/*******************************************************************************
 * Copyright (c) 2018, 2020 Eurotech and/or its affiliates and others
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

package org.eclipse.kura.internal.wire.helper;

import static java.util.Objects.requireNonNull;

import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;

import org.eclipse.kura.wire.graph.PortAggregator;
import org.eclipse.kura.wire.graph.ReceiverPort;

public class BarrierAggregator implements PortAggregator {

    private int fullSlots = 0;
    private final List<Object> envelopes;
    private Consumer<List<Object>> consumer = envelopes -> {
        // do nothing
    };

    public BarrierAggregator(List<ReceiverPort> ports) {
        requireNonNull(ports);
        this.envelopes = new ArrayList<>(ports.size());

        for (int i = 0; i < ports.size(); i++) {
            this.envelopes.add(null);
            final Integer port = i;

            ports.get(i).onWireReceive(envelope -> {
                synchronized (this.envelopes) {
                    if (this.envelopes.get(port) == null) {
                        this.fullSlots++;
                    }
                    this.envelopes.set(port, envelope);
                    if (this.fullSlots == this.envelopes.size()) {
                        this.consumer.accept(this.envelopes);
                        clearSlots();
                    }
                }
            });
        }
    }

    private void clearSlots() {
        this.fullSlots = 0;
        for (int i = 0; i < this.envelopes.size(); i++) {
            this.envelopes.set(i, null);
        }
    }

    @Override
    public void onWireReceive(Consumer<List<Object>> consumer) {
        requireNonNull(consumer);
        this.consumer = consumer;
    }

}
