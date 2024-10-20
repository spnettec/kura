/**
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
 */
package org.eclipse.kura.internal.driver.opcua;

import static java.util.Objects.isNull;
import static java.util.Objects.requireNonNull;

import java.util.Collection;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

import org.eclipse.kura.channel.ChannelRecord;
import org.eclipse.kura.channel.listener.ChannelListener;
import org.eclipse.kura.configuration.ConfigurableComponent;
import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.driver.ChannelDescriptor;
import org.eclipse.kura.driver.Driver;
import org.eclipse.kura.driver.PreparedRead;
import org.eclipse.kura.internal.driver.opcua.request.ListenRequest;
import org.eclipse.kura.internal.driver.opcua.request.ReadParams;
import org.eclipse.kura.internal.driver.opcua.request.Request;
import org.eclipse.kura.internal.driver.opcua.request.TreeListenParams;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * The Class {@link OpcUaDriver} is an OPC-UA Driver implementation for Kura Asset-Driver
 * Topology. Currently it only supports reading and writing from/to a specific
 * node. As of now, it doesn't support method execution or history read.
 * <br/>
 * <br/>
 * This OPC-UA Driver can be used in cooperation with Kura Asset Model and in
 * isolation as well. In case of isolation, the properties needs to be provided
 * externally.
 * <br/>
 * <br/>
 * The required properties are enlisted in {@link OpcUaChannelDescriptor} and
 * the driver connection specific properties are enlisted in
 * {@link OpcUaOptions}
 *
 * @see Driver
 * @see OpcUaOptions
 * @see OpcUaChannelDescriptor
 *
 */
public final class OpcUaDriver implements Driver, ConfigurableComponent {

    private static final Logger logger = LoggerFactory.getLogger(OpcUaDriver.class);

    private Optional<ConnectionManager> connectionManager = Optional.empty();
    private Optional<CompletableFuture<ConnectionManager>> connectTask = Optional.empty();

    private final ListenerRegistrationRegistry nodeListeneresRegistrations = new ListenerRegistrationRegistry();
    private final ListenerRegistrationRegistry subtreeListenerRegistrations = new ListenerRegistrationRegistry();

    private CryptoService cryptoService;
    private OpcUaOptions options;
    private long connectAttempt = 0;
    private int autoConnectAttempt = 0;

    protected ScheduledExecutorService connectionMonitorExecutor;
    private ScheduledFuture<?> connectionMonitorFuture;

    protected synchronized void activate(final Map<String, Object> properties) {
        this.connectionMonitorExecutor = Executors.newSingleThreadScheduledExecutor();
        logger.info("Activating OPC-UA Driver...");
        extractProperties(properties);
        logger.info("Activating OPC-UA Driver... Done");
    }

    protected synchronized void bindCryptoService(final CryptoService cryptoService) {
        if (isNull(this.cryptoService)) {
            this.cryptoService = cryptoService;
        }
    }

    protected synchronized void unbindCryptoService(final CryptoService cryptoService) {
        if (this.cryptoService == cryptoService) {
            this.cryptoService = null;
        }
    }

    protected CompletableFuture<ConnectionManager> connectAsync() {
        if (this.connectionManager.isPresent()) {
            return CompletableFuture.completedFuture(this.connectionManager.get());
        }
        return connectAsyncInternal();
    }

    private synchronized CompletableFuture<ConnectionManager> connectAsyncInternal() {
        if (this.connectionManager.isPresent()) {
            return CompletableFuture.completedFuture(this.connectionManager.get());
        }

        if (this.connectTask.isPresent() && !this.connectTask.get().isDone()) {
            return this.connectTask.get();
        }

        this.connectAttempt++;
        final long currentConnectAttempt = this.connectAttempt;
        final CompletableFuture<ConnectionManager> currentConnectTask = ConnectionManager.connect(this.options,
                this::onFailure, this.nodeListeneresRegistrations, this.subtreeListenerRegistrations)
                .thenApply(manager -> {
                    synchronized (this) {
                        if (this.connectAttempt != currentConnectAttempt) {
                            manager.close();
                            throw new IllegalStateException("Connection attempt has been cancelled");
                        } else {
                            this.connectTask = Optional.empty();
                            manager.start();
                            this.connectionManager = Optional.of(manager);
                        }
                        return manager;
                    }
                });
        this.connectTask = Optional.of(currentConnectTask);
        return currentConnectTask;
    }

    protected ConnectionManager connectSync() throws ConnectionException {
        try {
            return connectAsync().get(this.options.getRequestTimeout(), TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ConnectionException(e);
        } catch (Exception e) {
            throw new ConnectionException(e);
        }
    }

    @Override
    public void connect() throws ConnectionException {
        connectSync();
    }

    protected void deactivate() {
        logger.info("Deactivating OPC-UA Driver...");
        try {
            disconnect();
            this.connectionMonitorExecutor.shutdownNow();
        } catch (final ConnectionException e) {
            logger.error("Error while disconnecting....", e);
        }
        logger.info("Deactivating OPC-UA Driver... Done");
    }

    @Override
    public synchronized void disconnect() throws ConnectionException {
        try {
            this.connectAttempt++;
            if (this.connectTask.isPresent()) {
                this.connectTask = Optional.empty();
            }
            if (this.connectionManager.isPresent()) {
                this.connectionManager.get().close();
                this.connectionManager = Optional.empty();
            }
        } catch (Exception e) {
            throw new ConnectionException(e);
        } finally {
            stopConnectionMonitorTask();
        }
    }

    private void extractProperties(final Map<String, Object> properties) {
        requireNonNull(properties, "Properties cannot be null");
        this.options = new OpcUaOptions(properties, this.cryptoService);
    }

    /** {@inheritDoc} */
    @Override
    public ChannelDescriptor getChannelDescriptor() {
        return new OpcUaChannelDescriptor();
    }

    /** {@inheritDoc} */
    @Override
    public void write(final List<ChannelRecord> records) throws ConnectionException {
        final ConnectionManager connection = connectSync();
        try {
            connection.write(Request.extractWriteRequests(records));
        } catch (Exception e) {
            throw new ConnectionException(e);
        }
    }

    /** {@inheritDoc} */
    @Override
    public void read(final List<ChannelRecord> records) throws ConnectionException {
        final ConnectionManager connection = connectSync();
        try {
            connection.read(Request.extractReadRequests(records));
        } catch (Exception e) {
            throw new ConnectionException(e);
        }
    }

    /** {@inheritDoc} */
    @Override
    public void registerChannelListeners(final Map<ChannelListener, Map<String, Object>> listenerChannelConfigs)
            throws ConnectionException {
        List<ListenRequest> listenRequests = listenerChannelConfigs.entrySet().stream()
                .map(lc -> ListenRequest.extractListenRequest(lc.getValue(), lc.getKey())).collect(Collectors.toList());
        List<ListenRequest> treeListenRequests = listenRequests.stream()
                .filter(req -> req.getParameters() instanceof TreeListenParams).collect(Collectors.toList());
        List<ListenRequest> nodeListenRequests = listenRequests.stream()
                .filter(req -> !(req.getParameters() instanceof TreeListenParams)).collect(Collectors.toList());

        if (!treeListenRequests.isEmpty()) {
            this.subtreeListenerRegistrations.registerListeners(treeListenRequests);
        }
        if (!nodeListenRequests.isEmpty()) {
            this.nodeListeneresRegistrations.registerListeners(nodeListenRequests);
        }

        connectAsync();
        startConnectionMonitorTask();
    }

    /** {@inheritDoc} */
    @Override
    public void unregisterChannelListeners(final Collection<ChannelListener> listeners) throws ConnectionException {
        this.nodeListeneresRegistrations.unregisterListeners(listeners);
        this.subtreeListenerRegistrations.unregisterListeners(listeners);
    }

    /**
     * OSGi service component callback while updating.
     *
     * @param properties
     *            the properties
     */
    public void updated(final Map<String, Object> properties) {
        logger.info("Updating OPC-UA Driver...");

        extractProperties(properties);

        try {
            final boolean reconnect = this.connectionManager.isPresent();
            disconnect();

            if (reconnect) {
                connectAsync();
            }
        } catch (ConnectionException e) {
            logger.warn("Unable to Disconnect...");
        }

        logger.info("Updating OPC-UA Driver... Done");
    }

    private void onFailure(final ConnectionManager manager, final Throwable ex) {
        if (this.connectionManager.isPresent() && this.connectionManager.get() == manager) {
            logger.debug("Unrecoverable failure, forcing disconnect", ex);
            try {
                disconnect();
            } catch (ConnectionException e) {
                logger.warn("Unable to Disconnect...");
            } finally {
                startConnectionMonitorTask();
            }
        } else {
            logger.debug("Ignoring failure from old connection", ex);
        }
    }

    @Override
    public PreparedRead prepareRead(List<ChannelRecord> channelRecords) {
        requireNonNull(channelRecords, "Channel Record list cannot be null");

        return new OpcUaPreparedRead(Request.extractReadRequests(channelRecords), channelRecords);
    }

    private synchronized void startConnectionMonitorTask() {
        if (this.connectionMonitorFuture != null && !this.connectionMonitorFuture.isDone()) {
            return;
        }
        this.connectionMonitorFuture = this.connectionMonitorExecutor.scheduleAtFixedRate(() -> {

            String originalName = Thread.currentThread().getName();
            Thread.currentThread().setName("OpcUaDriver:ReconnectTask");
            try {
                if (!OpcUaDriver.this.connectionManager.isPresent()) {
                    connectAsync();
                    OpcUaDriver.this.autoConnectAttempt++;
                }
            } catch (Exception e) {
                logger.warn("Connect failed", e);
            } finally {
                Thread.currentThread().setName(originalName);
                if (OpcUaDriver.this.connectionManager.isPresent()) {
                    OpcUaDriver.this.autoConnectAttempt = 0;
                    logger.info("Connected. Reconnect task will be terminated.");
                    throw new RuntimeException("OpcUaDriver Connected. Reconnect task will be terminated.");
                } else {
                    if (OpcUaDriver.this.autoConnectAttempt > OpcUaDriver.this.options.getMaxConnectRetry()) {
                        logger.error("Auto connect retry {} times. Reconnect task will be terminated.",
                                OpcUaDriver.this.autoConnectAttempt);
                        throw new RuntimeException("Auto connect retry. Reconnect task will be terminated.");
                    }
                }
            }

        }, 10, 10, TimeUnit.SECONDS);
    }

    private synchronized void stopConnectionMonitorTask() {
        if (this.connectionMonitorFuture != null && !this.connectionMonitorFuture.isDone()) {

            logger.info("Reconnect task running. Stopping it");

            this.connectionMonitorFuture.cancel(true);
        }
    }

    private class OpcUaPreparedRead implements PreparedRead {

        private final List<Request<ReadParams>> requests;
        private final List<ChannelRecord> channelRecords;

        public OpcUaPreparedRead(final List<Request<ReadParams>> requests, final List<ChannelRecord> records) {
            this.requests = requests;
            this.channelRecords = records;
        }

        @Override
        public List<ChannelRecord> execute() throws ConnectionException {
            try {
                final ConnectionManager connection = connectSync();
                connection.read(this.requests);
                return Collections.unmodifiableList(this.channelRecords);
            } catch (Exception e) {
                throw new ConnectionException(e);
            }
        }

        @Override
        public List<ChannelRecord> getChannelRecords() {
            return Collections.unmodifiableList(this.channelRecords);
        }

        @Override
        public void close() {
            // no need
        }
    }
}
