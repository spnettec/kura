/**
 * Copyright (c) 2018, 2026 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 */

package org.eclipse.kura.internal.driver.opcua;

import static java.util.concurrent.CompletableFuture.completedFuture;
import static org.eclipse.kura.internal.driver.opcua.Utils.fillRecord;
import static org.eclipse.kura.internal.driver.opcua.Utils.fillValue;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.function.Consumer;

import org.eclipse.kura.channel.listener.ChannelListener;
import org.eclipse.kura.internal.driver.opcua.ListenerRegistrationRegistry.Dispatcher;
import org.eclipse.kura.internal.driver.opcua.request.ListenParams;
import org.eclipse.kura.internal.driver.opcua.request.ListenRequest;
import org.eclipse.milo.opcua.sdk.client.OpcUaClient;
import org.eclipse.milo.opcua.sdk.client.model.objects.BaseEventType;
import org.eclipse.milo.opcua.sdk.client.subscriptions.OpcUaMonitoredItem;
import org.eclipse.milo.opcua.sdk.client.subscriptions.OpcUaSubscription;
import org.eclipse.milo.opcua.stack.core.AttributeId;
import org.eclipse.milo.opcua.stack.core.Identifiers;
import org.eclipse.milo.opcua.stack.core.types.builtin.DataValue;
import org.eclipse.milo.opcua.stack.core.types.builtin.DateTime;
import org.eclipse.milo.opcua.stack.core.types.builtin.NodeId;
import org.eclipse.milo.opcua.stack.core.types.builtin.QualifiedName;
import org.eclipse.milo.opcua.stack.core.types.builtin.StatusCode;
import org.eclipse.milo.opcua.stack.core.types.builtin.Variant;
import org.eclipse.milo.opcua.stack.core.types.builtin.unsigned.UInteger;
import org.eclipse.milo.opcua.stack.core.types.enumerated.MonitoringMode;
import org.eclipse.milo.opcua.stack.core.types.structured.ContentFilter;
import org.eclipse.milo.opcua.stack.core.types.structured.EventFilter;
import org.eclipse.milo.opcua.stack.core.types.structured.SimpleAttributeOperand;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class SubscriptionManager implements ListenerRegistrationRegistry.Listener {

    private static final Logger logger = LoggerFactory.getLogger(SubscriptionManager.class);
    private static final EventFilter DEFAULT_EVENT_FILTER = new EventFilter(new SimpleAttributeOperand[] {
            new SimpleAttributeOperand(Identifiers.BaseEventType,
                    new QualifiedName[] { new QualifiedName(0, BaseEventType.TIME.getBrowseName()) },
                    AttributeId.Value.uid(), null),
            new SimpleAttributeOperand(Identifiers.BaseEventType,
                    new QualifiedName[] { new QualifiedName(0, BaseEventType.MESSAGE.getBrowseName()) },
                    AttributeId.Value.uid(), null) },
            new ContentFilter(null));

    private final OpcUaClient client;
    private final OpcUaOptions options;
    private final ListenerRegistrationRegistry registrations;
    private final AsyncTaskQueue queue;
    private final Runnable transferFailureHandler;

    private long currentRegistrationState;
    private long targetRegistrationState;

    private State state;

    public SubscriptionManager(final OpcUaOptions options, final OpcUaClient client, final AsyncTaskQueue queue,
            final ListenerRegistrationRegistry registrations) {
        this(options, client, queue, registrations, () -> {
        });
    }

    public SubscriptionManager(final OpcUaOptions options, final OpcUaClient client, final AsyncTaskQueue queue,
            final ListenerRegistrationRegistry registrations, final Runnable transferFailureHandler) {
        this.queue = queue;
        this.options = options;
        this.client = client;
        this.registrations = registrations;
        this.transferFailureHandler = transferFailureHandler;

        registrations.addRegistrationItemListener(this);

        this.state = new Unsubscribed();
    }

    @Override
    public synchronized void onRegistrationsChanged() {
        this.targetRegistrationState++;
        this.queue.push(() -> this.state.updateSubscriptionState());
    }

    private synchronized void onSubscriptionTransferFailed() {
        logger.debug("Subscription transfer failed");
        this.state = new Unsubscribed();
        this.transferFailureHandler.run();
        onRegistrationsChanged();
    }

    public synchronized CompletableFuture<Void> close() {
        this.registrations.removeRegistrationItemListener(this);
        return this.state.unsubscribe();
    }

    private interface State {

        CompletableFuture<Void> subscribe();

        CompletableFuture<Void> unsubscribe();

        CompletableFuture<Void> updateSubscriptionState();
    }

    private class Subscribed implements State {

        private final Map<ListenParams, MonitoredItemHandler> monitoredItemHandlers = new HashMap<>();
        final OpcUaSubscription subscription;

        Subscribed(final OpcUaSubscription subscription) {
            this.subscription = subscription;
            subscription.setSubscriptionListener(new OpcUaSubscription.SubscriptionListener() {
                @Override
                public void onTransferFailed(final OpcUaSubscription s, final StatusCode status) {
                    onSubscriptionTransferFailed();
                }
            });
        }

        @Override
        public CompletableFuture<Void> subscribe() {
            return completedFuture(null);
        }

        @Override
        public CompletableFuture<Void> unsubscribe() {
            logger.info("Unsubscribing..");
            for (final MonitoredItemHandler handler : this.monitoredItemHandlers.values()) {
                handler.close();
            }
            this.monitoredItemHandlers.clear();
            SubscriptionManager.this.client.removeSubscription(this.subscription);
            return toCompletableFuture(this.subscription.deleteAsync()).handle((ok, e) -> {
                if (e != null) {
                    logger.debug("Failed to delete subscription", e);
                }
                logger.info("Unsubscribing..done");
                synchronized (SubscriptionManager.this) {
                    SubscriptionManager.this.state = new Unsubscribed();
                }
                return (Void) null;
            });
        }

        @Override
        public CompletableFuture<Void> updateSubscriptionState() {

            synchronized (SubscriptionManager.this) {
                logger.info("Updating subscription state...");
                final long targetState = SubscriptionManager.this.targetRegistrationState;

                if (SubscriptionManager.this.currentRegistrationState == targetState) {
                    logger.info("Target state reached, nothing to do");
                    return completedFuture(null);
                }

                final Consumer<Void> onCompletion = ok -> {
                    logger.info("Updating subscription state...done");
                    synchronized (this) {
                        logger.info("Monitoring {} items", this.monitoredItemHandlers.size());
                        SubscriptionManager.this.currentRegistrationState = targetState;
                    }
                };

                final List<MonitoredItemHandler> toBeCreated = new ArrayList<>();
                final List<MonitoredItemHandler> toBeDeleted = new ArrayList<>();

                SubscriptionManager.this.registrations.computeDifferences(this.monitoredItemHandlers.keySet(),
                        item -> toBeCreated.add(new MonitoredItemHandler(
                                SubscriptionManager.this.registrations.getDispatcher(item))),
                        item -> toBeDeleted.add(this.monitoredItemHandlers.get(item)));

                if (toBeCreated.isEmpty() && toBeDeleted.size() == this.monitoredItemHandlers.size()) {
                    return SubscriptionManager.this.state.unsubscribe() //
                            .thenAccept(onCompletion);
                }

                toBeDeleted.removeIf(handler -> {
                    if (!handler.isAttached()) {
                        this.monitoredItemHandlers.remove(handler.getParams());
                        return true;
                    } else {
                        return false;
                    }
                });

                return applyMonitoredItemChanges(toBeCreated, toBeDeleted).thenAccept(onCompletion);
            }
        }

        private CompletableFuture<Void> applyMonitoredItemChanges(final List<MonitoredItemHandler> toBeCreated,
                final List<MonitoredItemHandler> toBeDeleted) {

            for (final MonitoredItemHandler handler : toBeCreated) {
                final OpcUaMonitoredItem item = handler.buildItem();
                this.subscription.addMonitoredItem(item);
                handler.attach(item);
                synchronized (SubscriptionManager.this) {
                    this.monitoredItemHandlers.put(handler.getParams(), handler);
                }
            }

            for (final MonitoredItemHandler handler : toBeDeleted) {
                handler.getMonitoredItem().ifPresent(this.subscription::removeMonitoredItem);
                handler.close();
                this.monitoredItemHandlers.remove(handler.getParams());
            }

            if (toBeCreated.isEmpty() && toBeDeleted.isEmpty()) {
                return completedFuture(null);
            }

            return CompletableFuture.runAsync(() -> {
                try {
                    this.subscription.synchronizeMonitoredItems();
                } catch (final Exception e) {
                    logger.warn("Failed to synchronize monitored items", e);
                }
                for (final MonitoredItemHandler handler : toBeCreated) {
                    handler.checkCreateResult();
                }
            });
        }
    }

    private class Unsubscribed implements State {

        Unsubscribed() {
        }

        @Override
        public CompletableFuture<Void> unsubscribe() {
            return completedFuture(null);
        }

        @Override
        public CompletableFuture<Void> subscribe() {
            logger.debug("Subscribing...");

            final OpcUaSubscription subscription = new OpcUaSubscription(SubscriptionManager.this.client,
                    SubscriptionManager.this.options.getSubsciptionPublishInterval());
            SubscriptionManager.this.client.addSubscription(subscription);

            return toCompletableFuture(subscription.createAsync()).thenAccept(unit -> {
                logger.debug("Subscribing...done, max notifications per publish: {}",
                        subscription.getMaxNotificationsPerPublish());
                synchronized (SubscriptionManager.this) {
                    SubscriptionManager.this.state = new Subscribed(subscription);
                }
            });
        }

        @Override
        public CompletableFuture<Void> updateSubscriptionState() {
            synchronized (SubscriptionManager.this) {
                if (SubscriptionManager.this.registrations.isEmpty()) {
                    logger.debug("No need to subscribe");
                    return CompletableFuture.completedFuture(null);
                }
            }
            return subscribe() //
                    .thenCompose(ok -> SubscriptionManager.this.state.updateSubscriptionState());
        }
    }

    private static <T> CompletableFuture<T> toCompletableFuture(final CompletionStage<T> stage) {
        if (stage instanceof CompletableFuture) {
            return (CompletableFuture<T>) stage;
        }
        return stage.toCompletableFuture();
    }

    private class MonitoredItemHandler {

        private OpcUaMonitoredItem monitoredItem;
        final Dispatcher dispatcher;

        public MonitoredItemHandler(final Dispatcher dispatcher) {
            this.dispatcher = dispatcher;
        }

        public OpcUaMonitoredItem buildItem() {
            final ListenParams params = this.dispatcher.getParams();
            final boolean isEventNotifier = AttributeId.EventNotifier.uid().equals(params.getReadValueId().getAttributeId());
            final OpcUaMonitoredItem item = new OpcUaMonitoredItem(params.getReadValueId(), MonitoringMode.Reporting);
            item.setSamplingInterval(isEventNotifier ? 0.0 : params.getSamplingInterval());
            item.setQueueSize(UInteger.valueOf(params.getQueueSize()));
            item.setDiscardOldest(params.getDiscardOldest());
            if (isEventNotifier) {
                item.setFilter(DEFAULT_EVENT_FILTER);
            }
            if (isEventNotifier) {
                item.setEventValueListener(this::onEventReceived);
            } else {
                item.setDataValueListener(this::onValueReceived);
            }
            return item;
        }

        public java.util.Optional<OpcUaMonitoredItem> getMonitoredItem() {
            return java.util.Optional.ofNullable(this.monitoredItem);
        }

        public ListenParams getParams() {
            return this.dispatcher.getParams();
        }

        public boolean isAttached() {
            return this.monitoredItem != null;
        }

        public void attach(final OpcUaMonitoredItem item) {
            this.monitoredItem = item;
        }

        public void checkCreateResult() {
            if (this.monitoredItem == null) {
                return;
            }
            final java.util.Optional<StatusCode> code = this.monitoredItem.getCreateResult();
            final NodeId nodeId = this.monitoredItem.getReadValueId().getNodeId();
            if (code.isPresent() && !code.get().isGood()) {
                logger.warn("Got bad status code for monitored item - code: {}, item: {}", code.get(), nodeId);
                this.monitoredItem = null;
                return;
            }
            if (logger.isTraceEnabled()) {
                logger.trace("Added monitored item for {}", nodeId);
            }
        }

        public void onEventReceived(final OpcUaMonitoredItem item, final Variant[] values) {
            this.dispatcher.dispatch(r -> {
                fillValue(values[1], r);

                try {
                    r.setTimestamp(((DateTime) values[0].getValue()).getJavaTime());
                } catch (Exception e) {
                    logger.debug("Failed to extract event Time, using locally generated timestamp");
                    r.setTimestamp(System.currentTimeMillis());
                }
            });
        }

        public void onValueReceived(final OpcUaMonitoredItem item, final DataValue value) {
            this.dispatcher.dispatch(r -> fillRecord(value, r));
        }

        public void close() {
            if (this.monitoredItem != null) {
                this.monitoredItem.setDataValueListener(null);
                this.monitoredItem.setEventValueListener(null);
            }
            this.monitoredItem = null;
        }
    }

    @Override
    public void onListenerRegistered(ListenRequest request) {
        // no need
    }

    @Override
    public void onListenerUnregistered(ChannelListener listener) {
        // no need
    }
}
