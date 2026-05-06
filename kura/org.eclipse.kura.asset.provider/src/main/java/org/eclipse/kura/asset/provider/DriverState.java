/*******************************************************************************
 * Copyright (c) 2018, 2023 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.asset.provider;

import java.util.Collection;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Map.Entry;
import java.util.Set;
import java.util.stream.Collectors;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraRuntimeException;
import org.eclipse.kura.asset.provider.BaseAsset.ChannelListenerHolder;
import org.eclipse.kura.channel.Channel;
import org.eclipse.kura.channel.ChannelRecord;
import org.eclipse.kura.channel.listener.ChannelListener;
import org.eclipse.kura.driver.Driver;
import org.eclipse.kura.driver.PreparedRead;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class DriverState {

    private static final Logger logger = LoggerFactory.getLogger(DriverState.class);

    private final Driver driver;
    private final Set<ChannelListenerHolder> attachedListeners;

    private PreparedRead preparedRead;

    public DriverState(final Driver driver) {
        this.driver = driver;
        this.attachedListeners = new HashSet<>();
    }

    public Driver getDriver() {
        return this.driver;
    }

    public PreparedRead getPreparedRead() {
        return this.preparedRead;
    }

    public PreparedRead tryPrepareRead(final List<ChannelRecord> records) {
        PreparedRead pRead;

        try {
            pRead = this.driver.prepareRead(records);
        } catch (final Exception e) {
            pRead = null;
        }

        if (pRead != null) {
            this.preparedRead = pRead;
        }

        return pRead;
    }

    private void closePreparedRead() {
        if (this.preparedRead != null) {
            try {
                this.preparedRead.close();
            } catch (Exception e) {
                logger.warn("Failed to close prepared read", e);
            }
            this.preparedRead = null;
        }
    }

    public void syncChannelListeners(final Set<ChannelListenerHolder> targetState,
            final Map<String, Channel> channels) {
        setChannelListenersInternal(new HashSet<>(targetState), channels);
    }

    private void setChannelListenersInternal(final Set<ChannelListenerHolder> targetState,
            final Map<String, Channel> channels) {

        List<ChannelListenerHolder> tobeRemoved = this.attachedListeners.stream()
                .filter(reg -> !targetState.contains(reg)).collect(Collectors.toList());
        if (!tobeRemoved.isEmpty()) {
            this.detach(tobeRemoved);
        }

        Map<ChannelListenerHolder, Channel> regChannels = targetState.stream().filter(reg -> {
            if (this.attachedListeners.contains(reg)) {
                return false;
            }

            final Channel channel = channels.get(reg.getChannelName());

            return channel != null && channel.isEnabled();
        }).collect(Collectors.toMap(reg -> reg, reg -> channels.get(reg.getChannelName())));
        if (!regChannels.isEmpty()) {
            attach(regChannels);
        }

    }

    private void attach(final Map<ChannelListenerHolder, Channel> regChannels) {
        logger.debug("Registering Channel Listener for monitoring...");
        Map<ChannelListenerHolder, Map<String, Object>> listenerChannelConfigs = regChannels.entrySet().stream()
                .collect(Collectors.toMap(Entry::getKey, regChannel -> regChannel.getValue().getConfiguration()));
        try {
            this.driver.registerChannelListeners(listenerChannelConfigs.entrySet().stream()
                    .collect(Collectors.toMap(Entry::getKey, Entry::getValue)));
            Set<ChannelListenerHolder> regs = regChannels.entrySet().stream().map(Entry::getKey)
                    .collect(Collectors.toSet());
            this.attachedListeners.addAll(regs);
        } catch (KuraRuntimeException kuraError) {
            if (kuraError.getCode() == KuraErrorCode.OPERATION_NOT_SUPPORTED) {
                for (Map.Entry<ChannelListenerHolder, Map<String, Object>> entry : listenerChannelConfigs.entrySet()) {
                    try {
                        this.driver.registerChannelListener(entry.getValue(), entry.getKey());
                        this.attachedListeners.add(entry.getKey());
                    } catch (Exception regError) {
                        logger.warn("Failed to register channel listener", regError);
                    }
                }
            } else {
                logger.warn("Failed to register channel listeners", kuraError);
            }
        } catch (Exception e) {
            logger.warn("Failed to register channel listeners", e);
        }

        logger.debug("Registering Channel Listener for monitoring...done");

    }

    private void detach(final Collection<ChannelListenerHolder> registrations) {
        logger.debug("Unregistering Asset Listener...");

        try {
            Collection<ChannelListener> listeners = registrations.stream()
                    .map(ChannelListenerHolder::getChannelListener).collect(Collectors.toSet());
            this.driver.unregisterChannelListeners(listeners);
            this.attachedListeners.removeAll(registrations);
        } catch (KuraRuntimeException kuraError) {
            if (kuraError.getCode() == KuraErrorCode.OPERATION_NOT_SUPPORTED) {
                for (ChannelListenerHolder registration : registrations) {
                    try {
                        this.driver.unregisterChannelListener(registration.getChannelListener());
                        this.attachedListeners.remove(registration);
                    } catch (Exception regError) {
                        logger.warn("Failed to unregister channel listener", regError);
                    }
                }
            } else {
                logger.warn("Failed to unregister channel listeners", kuraError);
            }
        } catch (Exception e) {
            logger.warn("Failed to unregister channel listeners", e);
        }
        logger.debug("Unregistering Asset Listener...done");
    }

    public synchronized void shutdown() {

        closePreparedRead();
        setChannelListenersInternal(Collections.emptySet(), Collections.emptyMap());
    }
}
