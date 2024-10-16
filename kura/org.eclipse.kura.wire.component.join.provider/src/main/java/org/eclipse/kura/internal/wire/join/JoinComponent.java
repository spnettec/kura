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
package org.eclipse.kura.internal.wire.join;

import static java.util.Objects.isNull;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.function.BiConsumer;
import java.util.stream.Collectors;

import org.eclipse.kura.configuration.ConfigurableComponent;
import org.eclipse.kura.type.TypedValue;
import org.eclipse.kura.wire.WireComponent;
import org.eclipse.kura.wire.WireEmitter;
import org.eclipse.kura.wire.WireEnvelope;
import org.eclipse.kura.wire.WireHelperService;
import org.eclipse.kura.wire.WireRecord;
import org.eclipse.kura.wire.graph.MultiportWireSupport;
import org.eclipse.kura.wire.multiport.MultiportWireReceiver;
import org.osgi.framework.ServiceReference;
import org.osgi.service.component.ComponentContext;
import org.osgi.service.wireadmin.Wire;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public final class JoinComponent implements MultiportWireReceiver, WireEmitter, ConfigurableComponent {

    private static final Logger logger = LoggerFactory.getLogger(JoinComponent.class);

    private volatile WireHelperService wireHelperService;

    private MultiportWireSupport wireSupport;
    private ComponentContext context;
    private JoinComponentOptions joinComponentOptions;

    public void bindWireHelperService(final WireHelperService wireHelperService) {
        if (isNull(this.wireHelperService)) {
            this.wireHelperService = wireHelperService;
        }
    }

    public void unbindWireHelperService(final WireHelperService wireHelperService) {
        if (this.wireHelperService == wireHelperService) {
            this.wireHelperService = null;
        }
    }

    @SuppressWarnings("unchecked")
    protected void activate(final ComponentContext componentContext, final Map<String, Object> properties) {
        logger.debug("Activating Join Wire Component...");
        this.context = componentContext;
        this.wireSupport = (MultiportWireSupport) this.wireHelperService.newWireSupport(this,
                (ServiceReference<WireComponent>) componentContext.getServiceReference());

        updated(properties);

        logger.debug("Activating Join Wire Component... Done");
    }

    public void updated(final Map<String, Object> properties) {
        if (this.joinComponentOptions != null) {
            this.joinComponentOptions.dispose();
        }
        logger.debug("Updating Join Wire Component...");
        this.joinComponentOptions = new JoinComponentOptions(properties, this.context.getBundleContext());

        this.joinComponentOptions.getPortAggregatorFactory().build(this.wireSupport.getReceiverPorts())
                .onWireReceive(this::onWireReceive);

        logger.debug("Updating Join Wire Component... Done");
    }

    private void onWireReceive(List<Object> envelopes) {
        final Object firstEnvelope = envelopes.get(0);
        final Object secondEnvelope = envelopes.get(1);
        if (firstEnvelope instanceof WireEnvelope && secondEnvelope instanceof WireEnvelope) {
            final List<WireRecord> firstRecords = firstEnvelope != null ? ((WireEnvelope) firstEnvelope).getRecords()
                    : Collections.emptyList();
            final List<WireRecord> secondRecords = secondEnvelope != null ? ((WireEnvelope) secondEnvelope).getRecords()
                    : Collections.emptyList();
            final List<WireRecord> result = new ArrayList<>();
            forEachPair(firstRecords.iterator(), secondRecords.iterator(), (first, second) -> {
                if (first == null) {
                    result.add(new WireRecord(covertProperies(second.getProperties())));
                    return;
                }
                if (second == null) {
                    result.add(new WireRecord(covertProperies(first.getProperties())));
                    return;
                }
                final Map<String, TypedValue<?>> resultProperties = new HashMap<>(
                        covertProperies(first.getProperties()));
                resultProperties.putAll(covertProperies(second.getProperties()));
                result.add(new WireRecord(resultProperties));
            });
            this.wireSupport.emit(result);
        } else {
            logger.warn("receive firstEnvelope:{} or secondEnvelope:{} is not WireEnvelope", firstEnvelope,
                    secondEnvelope);
        }
    }

    private <T, U> void forEachPair(Iterator<T> first, Iterator<U> second, BiConsumer<T, U> consumer) {
        while (first.hasNext() || second.hasNext()) {
            final T firstValue = first.hasNext() ? first.next() : null;
            final U secondValue = second.hasNext() ? second.next() : null;
            consumer.accept(firstValue, secondValue);
        }
    }

    protected void deactivate(final ComponentContext componentContext) {
        if (this.joinComponentOptions != null) {
            this.joinComponentOptions.dispose();
        }
        logger.debug("Deactivating Join Wire Component...");
        // remained for debugging purposes
        logger.debug("Deactivating Join Wire Component... Done");
    }

    /** {@inheritDoc} */
    @Override
    public void producersConnected(final Wire[] wires) {
        this.wireSupport.producersConnected(wires);
    }

    /** {@inheritDoc} */
    @Override
    public void updated(final Wire wire, final Object value) {
        this.wireSupport.updated(wire, value);
    }

    @Override
    public Object polled(Wire wire) {
        return this.wireSupport.polled(wire);
    }

    @Override
    public void consumersConnected(Wire[] wires) {
        this.wireSupport.consumersConnected(wires);
    }

    private static Map<String, TypedValue<?>> covertProperies(final Map<String, TypedValue<?>> properties) {
        TypedValue<?> assertName = properties.get("assetName");
        if (assertName == null) {
            return properties;
        }
        return properties.entrySet().stream().filter(v -> {
            return !v.getKey().equals("assetName");
        }).collect(Collectors.toMap(k -> assertName.getValue().toString() + "." + k.getKey(), Map.Entry::getValue));

    }
}
