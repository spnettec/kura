/*******************************************************************************
 * Copyright (c) 2011, 2020 Red Hat Inc and others
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
package org.eclipse.kura.camel.cloud;

import static org.apache.camel.builder.ExchangeBuilder.anExchange;
import static org.eclipse.kura.camel.camelcloud.KuraCloudClientConstants.CAMEL_KURA_CLOUD_CONTROL;
import static org.eclipse.kura.camel.camelcloud.KuraCloudClientConstants.CAMEL_KURA_CLOUD_DEVICEID;
import static org.eclipse.kura.camel.camelcloud.KuraCloudClientConstants.CAMEL_KURA_CLOUD_QOS;
import static org.eclipse.kura.camel.camelcloud.KuraCloudClientConstants.CAMEL_KURA_CLOUD_RETAIN;
import static org.eclipse.kura.camel.camelcloud.KuraCloudClientConstants.CAMEL_KURA_CLOUD_TOPIC;

import org.apache.camel.Endpoint;
import org.apache.camel.Exchange;
import org.apache.camel.Processor;
import org.apache.camel.support.DefaultConsumer;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.cloud.CloudClient;
import org.eclipse.kura.cloud.CloudClientListener;
import org.eclipse.kura.message.KuraPayload;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Consumer implementation for {@link KuraCloudComponent}
 */
public class KuraCloudConsumer extends DefaultConsumer implements CloudClientListener {

    private static final Logger log = LoggerFactory.getLogger(KuraCloudConsumer.class);
    private final CloudClient cloudClient;

    public KuraCloudConsumer(final Endpoint endpoint, final Processor processor, final CloudClient cloudClient) {
        super(endpoint, processor);
        this.cloudClient = cloudClient;
    }

    // Life-cycle

    @Override
    protected void doStart() throws Exception {
        super.doStart();

        log.debug("Starting CloudClientListener.");

        this.cloudClient.addCloudClientListener(this);
        if (this.cloudClient.isConnected()) {
            performSubscribe();
        }
    }

    @Override
    protected void doStop() throws Exception {
        try {
            this.cloudClient.unsubscribe(getEndpoint().getTopic());
        } catch (final Exception e) {
            log.info("Failed to unsubscribe", e);
        }
        this.cloudClient.removeCloudClientListener(this);
        log.debug("Stopping CloudClientListener.");
        super.doStop();
    }

    // CloudClientListener callbacks

    @Override
    public void onControlMessageArrived(final String deviceId, final String appTopic, final KuraPayload msg,
            final int qos, final boolean retain) {
        onInternalMessageArrived(deviceId, appTopic, msg, qos, retain, true);
    }

    @Override
    public void onMessageArrived(final String deviceId, final String appTopic, final KuraPayload msg, final int qos,
            final boolean retain) {
        onInternalMessageArrived(deviceId, appTopic, msg, qos, retain, false);
    }

    @Override
    public void onConnectionLost() {
        log.debug("Executing empty 'onConnectionLost' callback.");
    }

    @Override
    public void onConnectionEstablished() {
        log.debug("Executing 'onConnectionEstablished'.");
        performSubscribe();
    }

    private void performSubscribe() {
        try {
            log.debug("Perform subscribe: {} / {}", this.cloudClient, getEndpoint().getTopic());
            this.cloudClient.subscribe(getEndpoint().getTopic(), 0);
        } catch (final KuraException e) {
            log.warn("Failed to subscribe", e);
        }
    }

    @Override
    public void onMessageConfirmed(final int messageId, final String appTopic) {
        log.debug("Executing empty 'onMessageConfirmed' callback with message ID {} and application topic {}.",
                messageId, appTopic);
    }

    @Override
    public void onMessagePublished(final int messageId, final String appTopic) {
        log.debug("Executing empty 'onMessagePublished' callback with message ID {} and application topic {}.",
                messageId, appTopic);
    }

    // Helpers

    private void onInternalMessageArrived(final String deviceId, final String appTopic, final KuraPayload message,
            final int qos, final boolean retain, final boolean control) {
        log.debug("Received message with deviceId {}, application topic {}.", deviceId, appTopic);

        final Exchange exchange = anExchange(getEndpoint().getCamelContext()) //
                .withBody(message) //
                .withHeader(CAMEL_KURA_CLOUD_TOPIC, appTopic) //
                .withHeader(CAMEL_KURA_CLOUD_DEVICEID, deviceId) //
                .withHeader(CAMEL_KURA_CLOUD_QOS, qos) //
                .withHeader(CAMEL_KURA_CLOUD_CONTROL, control) //
                .withHeader(CAMEL_KURA_CLOUD_RETAIN, retain) //
                .build();
        exchange.setExchangeId(getEndpoint().getId());

        try {
            getProcessor().process(exchange);
        } catch (final Exception e) {
            handleException("Error while processing an incoming message:", e);
        }
    }

    // Getters

    @Override
    public KuraCloudEndpoint getEndpoint() {
        return (KuraCloudEndpoint) super.getEndpoint();
    }

}
