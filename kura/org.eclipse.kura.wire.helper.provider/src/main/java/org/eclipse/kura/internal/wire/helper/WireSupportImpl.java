/*******************************************************************************
 * Copyright (c) 2016, 2020 Eurotech and/or its affiliates and others
 * 
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 * 
 * SPDX-License-Identifier: EPL-2.0
 * 
 * Contributors:
 *  Eurotech
 *  Amit Kumar Mondal
 *******************************************************************************/
package org.eclipse.kura.internal.wire.helper;

import static java.util.Objects.requireNonNull;
import static org.eclipse.kura.wire.graph.Constants.WIRE_EMITTER_PORT_PROP_NAME;
import static org.eclipse.kura.wire.graph.Constants.WIRE_RECEIVER_PORT_PROP_NAME;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.SynchronousQueue;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Consumer;

import org.eclipse.kura.wire.WireComponent;
import org.eclipse.kura.wire.WireEnvelope;
import org.eclipse.kura.wire.WireReceiver;
import org.eclipse.kura.wire.WireRecord;
import org.eclipse.kura.wire.WireSupport;
import org.eclipse.kura.wire.graph.EmitterPort;
import org.eclipse.kura.wire.graph.MultiportWireSupport;
import org.eclipse.kura.wire.graph.Port;
import org.eclipse.kura.wire.graph.ReceiverPort;
import org.osgi.service.wireadmin.Wire;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * The Class WireSupportImpl implements {@link WireSupport}
 */
final class WireSupportImpl implements WireSupport, MultiportWireSupport {

    private static final Logger logger = LoggerFactory.getLogger(WireSupportImpl.class);

    private final List<ReceiverPort> receiverPorts;

    private final List<EmitterPort> emitterPorts;

    private final WireComponent wireComponent;

    private final String servicePid;
    private final String kuraServicePid;

    private final boolean isNulltoEnvenlope;

    private ExecutorService receiverExecutor;

    private final Map<Wire, ReceiverPortImpl> receiverPortByWire;

    WireSupportImpl(final WireComponent wireComponent, final String servicePid, final String kuraServicePid,
            int inputPortCount, int outputPortCount, boolean isNulltoEnvenlope) {
        requireNonNull(wireComponent, "Wire component cannot be null");
        requireNonNull(servicePid, "service pid cannot be null");
        requireNonNull(kuraServicePid, "kura service pid cannot be null");
        this.servicePid = servicePid;
        this.kuraServicePid = kuraServicePid;
        this.wireComponent = wireComponent;
        receiverExecutor = createExecutorService(kuraServicePid);
        if (inputPortCount < 0) {
            throw new IllegalArgumentException("Input port count must be greater or equal than zero");
        }
        if (outputPortCount < 0) {
            throw new IllegalArgumentException("Output port count must be greater or equal than zero");
        }
        this.isNulltoEnvenlope = isNulltoEnvenlope;
        this.receiverPorts = new ArrayList<>(inputPortCount);
        this.emitterPorts = new ArrayList<>(outputPortCount);
        this.receiverPortByWire = new HashMap<>();

        for (int i = 0; i < inputPortCount; i++) {
            receiverPorts.add(new ReceiverPortImpl());
        }

        for (int i = 0; i < outputPortCount; i++) {
            emitterPorts.add(new EmitterPortImpl());
        }
    }

    private ExecutorService createExecutorService(String kuraServicePid) {
        int cores = Runtime.getRuntime().availableProcessors();
        return new ThreadPoolExecutor(1, cores * 2, 60L, TimeUnit.SECONDS, new SynchronousQueue<>(),
                new WireDefaultThreadFactory(kuraServicePid), new ThreadPoolExecutor.DiscardOldestPolicy());
    }

    private void clearReceiverPorts() {
        this.receiverPortByWire.clear();
        for (final ReceiverPort port : this.receiverPorts) {
            ((PortImpl) port).connectedWires.clear();
        }
    }

    private void clearEmitterPorts() {
        for (final EmitterPort port : this.emitterPorts) {
            ((PortImpl) port).connectedWires.clear();
        }
    }

    /** {@inheritDoc} */
    @Override
    public synchronized void consumersConnected(final Wire[] wires) {
        clearEmitterPorts();
        if (wires == null || wires.length == 0) {
            return;
        }
        for (Wire w : wires) {
            try {
                final int outputPort = (Integer) w.getProperties().get(WIRE_EMITTER_PORT_PROP_NAME.value());
                ((PortImpl) this.emitterPorts.get(outputPort)).connectedWires.add(w);
            } catch (Exception e) {
                logger.warn("Failed to assign outgoing wire to port", e);
            }
        }
    }

    /** {@inheritDoc} */
    @SuppressWarnings("unchecked")
    @Override
    public synchronized void emit(Object wireRecords) {
        requireNonNull(wireRecords, "Wire Records cannot be null");
        if (List.class.isAssignableFrom(wireRecords.getClass())) {
            if (((List<?>) wireRecords).isEmpty()) {
                if (this.isNulltoEnvenlope) {
                    wireRecords = createWireEnvelope(Collections.emptyList());
                }
            } else if (((List<?>) wireRecords).get(0) instanceof WireRecord) {
                wireRecords = createWireEnvelope((List<WireRecord>) wireRecords);
            }
        } else if (wireRecords instanceof WireEnvelope) {
            wireRecords = ((WireEnvelope) wireRecords).getRecords();
            wireRecords = createWireEnvelope((List<WireRecord>) wireRecords);
        } else if (wireRecords instanceof WireRecord) {
            wireRecords = createWireEnvelope(Collections.singletonList((WireRecord) wireRecords));
        }
        final Object envelope = wireRecords;

        for (EmitterPort emitterPort : this.emitterPorts) {
            try {
                emitterPort.emit(envelope);
            } catch (Exception e) {
                logger.error("emit error", e);
            }
        }
    }

    /** {@inheritDoc} */
    @Override
    public synchronized Object polled(final Wire wire) {
        return wire.getLastValue();
    }

    /** {@inheritDoc} */
    @Override
    public synchronized void producersConnected(final Wire[] wires) {
        clearReceiverPorts();
        if (wires == null) {
            receiverExecutor.shutdownNow();
            return;
        }
        if (receiverExecutor.isShutdown()) {
            receiverExecutor = createExecutorService(this.kuraServicePid);
        }
        for (Wire w : wires) {
            try {
                final int receiverPortIndex = (Integer) w.getProperties().get(WIRE_RECEIVER_PORT_PROP_NAME.value());
                final ReceiverPortImpl receiverPort = (ReceiverPortImpl) this.receiverPorts.get(receiverPortIndex);
                receiverPort.connectedWires.add(w);
                this.receiverPortByWire.put(w, receiverPort);
            } catch (Exception e) {
                logger.warn("Failed to assign incomimg wire to port", e);
            }
        }
    }

    /** {@inheritDoc} */
    @Override
    public void updated(final Wire wire, final Object value) {
        if (wire == null) {
            logger.warn("Wire cannot be null");
            return;
        }
        final Object envelopeValue = value;
        if (wireComponent instanceof WireReceiver) {
            receiverExecutor.execute(() -> {
                try {
                    ((WireReceiver) WireSupportImpl.this.wireComponent).onWireReceive(envelopeValue);
                } catch (Exception e) {
                    logger.error("Excute receive massage error", e);
                }
            });
        } else {
            receiverExecutor.execute(() -> {
                try {
                    final ReceiverPortImpl receiverPort = WireSupportImpl.this.receiverPortByWire.get(wire);
                    receiverPort.consumer.accept(envelopeValue);
                } catch (Exception e) {
                    logger.error("Excute consumer massage error", e);
                }
            });
        }
    }

    @Override
    public List<EmitterPort> getEmitterPorts() {
        return Collections.unmodifiableList(this.emitterPorts);
    }

    @Override
    public List<ReceiverPort> getReceiverPorts() {
        return Collections.unmodifiableList(this.receiverPorts);
    }

    private abstract class PortImpl implements Port {

        List<Wire> connectedWires = new CopyOnWriteArrayList<>();

        @Override
        public List<Wire> listConnectedWires() {
            return Collections.unmodifiableList(connectedWires);
        }
    }

    private class EmitterPortImpl extends PortImpl implements EmitterPort {

        @Override
        public void emit(Object envelope) {
            for (final Wire wire : this.connectedWires) {
                wire.update(envelope);
            }
        }
    }

    private class ReceiverPortImpl extends PortImpl implements ReceiverPort {

        Consumer<Object> consumer = envelope -> {
            // do nothing
        };

        @Override
        public void onWireReceive(Consumer<Object> consumer) {
            requireNonNull(consumer);
            this.consumer = consumer;
        }
    }

    private WireEnvelope createWireEnvelope(List<WireRecord> records) {
        return new WireEnvelope(servicePid, records);
    }

    static class WireDefaultThreadFactory implements ThreadFactory {

        private static final AtomicInteger POOL_NUMBER = new AtomicInteger(1);
        private final ThreadGroup group;
        private final AtomicInteger threadNumber = new AtomicInteger(1);
        private final String namePrefix;

        WireDefaultThreadFactory(String name) {
            group = Thread.currentThread().getThreadGroup();
            namePrefix = "WirePool-" + POOL_NUMBER.getAndIncrement() + "-" + name + "-";
        }

        public Thread newThread(Runnable r) {
            Thread t = new Thread(group, r, namePrefix + threadNumber.getAndIncrement(), 0);
            if (t.isDaemon()) {
                t.setDaemon(false);
            }
            if (t.getPriority() != Thread.NORM_PRIORITY) {
                t.setPriority(Thread.NORM_PRIORITY);
            }
            return t;
        }
    }
}
