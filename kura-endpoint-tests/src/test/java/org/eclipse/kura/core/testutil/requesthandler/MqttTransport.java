/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.testutil.requesthandler;

import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import org.eclipse.kura.internal.json.marshaller.unmarshaller.JsonMarshallUnmarshallImpl;
import org.eclipse.kura.message.KuraPayload;
import org.eclipse.paho.client.mqttv3.*;
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence;

/** Observer side of the upstream control-request protocol; the fixture owns the real Kura pipeline. */
public class MqttTransport implements Transport {
    private final String brokerUri;
    private final String appId;
    private final String observerId = "observer-" + UUID.randomUUID();
    private final JsonMarshallUnmarshallImpl json = new JsonMarshallUnmarshallImpl();
    private final Map<String, CompletableFuture<KuraPayload>> pending = new ConcurrentHashMap<>();
    private MqttClient client;

    public MqttTransport(String brokerUri, String appId) { this.brokerUri = brokerUri; this.appId = appId; }
    @Override
    public TransportType getType() { return TransportType.MQTT; }

    @Override
    public void init() {
        if (this.client != null) { return; }
        try {
            this.client = new MqttClient(this.brokerUri.replace("mqtt://", "tcp://"), this.observerId, new MemoryPersistence());
            this.client.setTimeToWait(5000);
            this.client.setCallback(new MqttCallback() {
                @Override
                public void connectionLost(Throwable cause) { pending.values().forEach(future -> future.completeExceptionally(cause)); }
                @Override
                public void deliveryComplete(IMqttDeliveryToken token) { }
                @Override
                public void messageArrived(String topic, MqttMessage message) {
                    CompletableFuture<KuraPayload> future = pending.get(topic.substring(topic.lastIndexOf('/') + 1));
                    if (future == null) { return; }
                    try { future.complete(json.unmarshal(new String(message.getPayload(), StandardCharsets.UTF_8), KuraPayload.class)); }
                    catch (Exception e) { future.completeExceptionally(e); }
                }
            });
            MqttConnectOptions options = new MqttConnectOptions();
            options.setConnectionTimeout(5);
            options.setCleanSession(true);
            this.client.connect(options);
            this.client.subscribe(replyPrefix() + "+", 1);
        } catch (Exception e) {
            try { close(); } catch (Exception cleanup) { e.addSuppressed(cleanup); }
            throw new IllegalStateException("Cannot connect MQTT observer", e);
        }
    }

    @Override
    public Response runRequest(String resource, MethodSpec method) { return runRequest(resource, method, null); }
    @Override
    public Response runRequest(String resource, MethodSpec method, String body) {
        String id = UUID.randomUUID().toString();
        CompletableFuture<KuraPayload> future = new CompletableFuture<>();
        this.pending.put(id, future);
        try {
            KuraPayload request = new KuraPayload();
            request.addMetric("request.id", id);
            request.addMetric("requester.client.id", this.observerId);
            if (body != null) { request.setBody(body.getBytes(StandardCharsets.UTF_8)); }
            this.client.publish("EDC/test-account/test-client/" + this.appId + "/" + method.getRequestHandlerMethod() + resource,
                    this.json.marshal(request).getBytes(StandardCharsets.UTF_8), 1, false);
            KuraPayload reply = future.get(10, TimeUnit.SECONDS);
            int status = ((Number) reply.getMetric("response.code")).intValue();
            return new Response(status, Optional.ofNullable(reply.getBody())
                    .map(bytes -> new String(bytes, StandardCharsets.UTF_8)).filter(value -> !value.isEmpty()));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("MQTT request interrupted", e);
        } catch (Exception e) { throw new IllegalStateException("MQTT request failed", e); }
        finally { this.pending.remove(id); }
    }
    private String replyPrefix() { return "EDC/test-account/" + this.observerId + "/" + this.appId + "/REPLY/"; }

    @Override
    public void close() {
        try {
            if (this.client != null) {
                try { if (this.client.isConnected()) { this.client.disconnectForcibly(1000, 1000); } }
                finally { this.client.close(); }
            }
        } catch (MqttException e) { throw new IllegalStateException("Cannot close MQTT observer", e); }
        finally {
            this.client = null;
            this.pending.values().forEach(future -> future.cancel(true));
            this.pending.clear();
        }
    }
}
