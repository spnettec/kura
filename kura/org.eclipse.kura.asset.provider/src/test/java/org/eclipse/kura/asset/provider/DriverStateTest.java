/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 available at
 * https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.asset.provider;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Collection;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraRuntimeException;
import org.eclipse.kura.channel.Channel;
import org.eclipse.kura.channel.ChannelRecord;
import org.eclipse.kura.channel.ChannelType;
import org.eclipse.kura.channel.ScaleOffsetType;
import org.eclipse.kura.channel.listener.ChannelEvent;
import org.eclipse.kura.channel.listener.ChannelListener;
import org.eclipse.kura.driver.ChannelDescriptor;
import org.eclipse.kura.driver.Driver;
import org.eclipse.kura.driver.PreparedRead;
import org.eclipse.kura.type.DataType;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class DriverStateTest {

    @ParameterizedTest(name = "bulk listener API = {0}")
    @ValueSource(booleans = {true, false})
    void removesTheRegisteredWrapperOnReconfigurationAndShutdown(boolean bulk) {
        RecordingDriver driver = new RecordingDriver(bulk);
        DriverState state = new DriverState(driver);
        BaseAsset asset = new BaseAsset();
        Channel channel = new Channel("foo", ChannelType.READ, DataType.STRING,
                ScaleOffsetType.DEFINED_BY_VALUE_TYPE, 1.0d, 0.0d, Map.of());
        AtomicInteger callbacks = new AtomicInteger();
        var holder = asset.new ChannelListenerHolder(channel, event -> callbacks.incrementAndGet());

        state.syncChannelListeners(Set.of(holder), Map.of("foo", channel));
        assertEquals(1, driver.listeners.size());
        assertSame(holder, driver.listeners.iterator().next());
        driver.emit();
        assertEquals(1, callbacks.get());

        state.syncChannelListeners(Set.of(), Map.of("foo", channel));
        assertTrue(driver.listeners.isEmpty(), "Reconfiguration must unregister the same wrapper that was registered");
        driver.emit();
        assertEquals(1, callbacks.get(), "Removed listeners must receive no further events");

        state.syncChannelListeners(Set.of(holder), Map.of("foo", channel));
        assertEquals(1, driver.listeners.size());
        state.shutdown();
        assertTrue(driver.listeners.isEmpty(), "Shutdown must release all driver listener registrations");
        state.shutdown();
        driver.emit();
        assertEquals(1, callbacks.get());
    }

    private static final class RecordingDriver implements Driver {
        private final boolean bulk;
        private final Set<ChannelListener> listeners = Collections.newSetFromMap(new IdentityHashMap<>());

        RecordingDriver(boolean bulk) {
            this.bulk = bulk;
        }

        @Override
        public void registerChannelListeners(Map<ChannelListener, Map<String, Object>> configurations) {
            requireBulk();
            this.listeners.addAll(configurations.keySet());
        }

        @Override
        public void unregisterChannelListeners(Collection<ChannelListener> registrations) {
            requireBulk();
            registrations.forEach(this.listeners::remove);
        }

        private void requireBulk() {
            if (!this.bulk) {
                throw new KuraRuntimeException(KuraErrorCode.OPERATION_NOT_SUPPORTED);
            }
        }

        @Override
        public void registerChannelListener(Map<String, Object> config, ChannelListener listener) {
            this.listeners.add(listener);
        }

        @Override
        public void unregisterChannelListener(ChannelListener listener) {
            this.listeners.remove(listener);
        }

        void emit() {
            ChannelEvent event = new ChannelEvent(ChannelRecord.createReadRecord("foo", DataType.STRING));
            this.listeners.forEach(listener -> listener.onChannelEvent(event));
        }

        @Override
        public void connect() { }

        @Override
        public void disconnect() { }

        @Override
        public ChannelDescriptor getChannelDescriptor() {
            return Collections::emptyList;
        }

        @Override
        public PreparedRead prepareRead(List<ChannelRecord> records) {
            throw new UnsupportedOperationException();
        }

        @Override
        public void read(List<ChannelRecord> records) { }

        @Override
        public void write(List<ChannelRecord> records) { }
    }
}
