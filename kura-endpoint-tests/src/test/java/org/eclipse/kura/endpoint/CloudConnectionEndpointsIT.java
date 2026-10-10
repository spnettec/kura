/*******************************************************************************
 * Copyright (c) 2023, 2026 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 ******************************************************************************/
package org.eclipse.kura.endpoint;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.CALLS_REAL_METHODS;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockStatic;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Hashtable;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import org.eclipse.kura.cloudconnection.CloudConnectionConstants;
import org.eclipse.kura.cloudconnection.CloudConnectionManager;
import org.eclipse.kura.cloudconnection.factory.CloudConnectionFactory;
import org.eclipse.kura.cloudconnection.publisher.CloudPublisher;
import org.eclipse.kura.cloudconnection.subscriber.CloudSubscriber;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.testutil.requesthandler.Transport.MethodSpec;
import org.eclipse.kura.core.testutil.requesthandler.Transport.Response;
import org.eclipse.kura.core.testutil.requesthandler.TransportType;
import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.internal.rest.cloudconnection.provider.CloudConnectionRestService;
import org.eclipse.osgi.launch.EquinoxFactory;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.mockito.ArgumentCaptor;
import org.mockito.MockedStatic;
import org.osgi.framework.Bundle;
import org.osgi.framework.BundleContext;
import org.osgi.framework.Constants;
import org.osgi.framework.FrameworkEvent;
import org.osgi.framework.FrameworkUtil;
import org.osgi.framework.ServiceRegistration;
import org.osgi.framework.launch.Framework;
import org.osgi.service.cm.ConfigurationAdmin;
import org.osgi.service.component.runtime.ServiceComponentRuntime;
import org.osgi.service.component.runtime.dto.ComponentDescriptionDTO;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

/** Loopback HTTP/MQTT with a real registry; SCR and cloud factories are controlled boundaries. */
class CloudConnectionEndpointsIT extends EndpointTestBase {

    private static final String ENDPOINT = "custom.cloud";
    private static final String FACTORY = "test.cloud.factory";
    private static final String PUBLISHER_FACTORY = "test.publisher.factory";
    private static final String SUBSCRIBER_FACTORY = "test.subscriber.factory";
    private ConfigurationService configurations;
    private CloudConnectionFactory factory;
    private CloudConnectionManager manager;
    private ServiceComponentRuntime scr;
    @TempDir Path storage;
    private Framework framework;
    private BundleContext context;
    private CloudConnectionRestService endpoint;
    private final List<ServiceRegistration<?>> registrations = new ArrayList<>();
    private final Gson gson = new Gson();

    @BeforeEach
    void registerEndpoint() throws Exception {
        // BaseCloudTests owns one broker per class; each invocation needs fresh service state.
        this.configurations = mock(ConfigurationService.class);
        this.factory = mock(CloudConnectionFactory.class);
        this.manager = mock(CloudConnectionManager.class);
        this.scr = mock(ServiceComponentRuntime.class);
        this.framework = new EquinoxFactory().newFramework(Map.of(Constants.FRAMEWORK_STORAGE, this.storage.toString(),
                Constants.FRAMEWORK_STORAGE_CLEAN, Constants.FRAMEWORK_STORAGE_CLEAN_ONFIRSTINIT));
        this.framework.start();
        this.context = this.framework.getBundleContext();
        register(CloudConnectionFactory.class, "factory.service", this.factory,
                Map.of("kura.ui.csf.pid.default", "custom.cloud", "kura.ui.csf.pid.regex", ".*"));
        register(CloudConnectionManager.class, ENDPOINT, this.manager, Map.of());
        register(ConfigurationService.class, "configuration.service", this.configurations, Map.of());
        register(ServiceComponentRuntime.class, "scr", this.scr, Map.of());
        register(CloudPublisher.class, "test.publisher", mock(CloudPublisher.class), pubsubProperties(PUBLISHER_FACTORY));
        register(CloudSubscriber.class, "test.subscriber", mock(CloudSubscriber.class), pubsubProperties(SUBSCRIBER_FACTORY));
        when(this.factory.getFactoryPid()).thenReturn(FACTORY);
        when(this.factory.getManagedCloudConnectionPids()).thenReturn(Set.of(ENDPOINT));
        when(this.factory.getStackComponentsPids(ENDPOINT)).thenReturn(List.of(ENDPOINT, "data.123", "transport.123"));
        when(this.scr.getComponentDescriptionDTOs()).thenReturn(List.of(description(PUBLISHER_FACTORY, CloudPublisher.class),
                description(SUBSCRIBER_FACTORY, CloudSubscriber.class)));
        this.endpoint = new CloudConnectionRestService();
        this.endpoint.bindConfigurationService(this.configurations);
        this.endpoint.bindCryptoService(mock(CryptoService.class));
        this.endpoint.bindUserAdmin(this.http.identityFixture().userAdmin);
        // Both helpers capture their BundleContext at activation. Close this thread-local mock before
        // HTTP/MQTT workers handle any request; their service lookups use the real Equinox registry.
        Bundle bundle = mock(Bundle.class);
        when(bundle.getBundleContext()).thenReturn(this.context);
        try (MockedStatic<FrameworkUtil> frameworkScope = mockStatic(FrameworkUtil.class, CALLS_REAL_METHODS)) {
            frameworkScope.when(() -> FrameworkUtil.getBundle(any(Class.class))).thenReturn(bundle);
            this.endpoint.activate();
        }
        this.endpoint.bindRequestHandlerRegistry(this.cloud);
        this.http.resource(this.endpoint);
    }

    @AfterEach
    void unregisterEndpoint() throws Exception {
        try {
            if (this.endpoint != null) { this.endpoint.unbindRequestHandlerRegistry(this.cloud); }
            this.registrations.forEach(ServiceRegistration::unregister);
            this.registrations.clear();
        } finally {
            if (this.framework != null) {
                this.framework.stop();
                assertEquals(FrameworkEvent.STOPPED, this.framework.waitForStop(5000).getType());
            }
        }
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldGetCloudComponentInstances(TransportType type) throws Exception {
        useTransport(type, "CLD-V1", "cloudconnection/v1");
        JsonObject response = request("GET", "/instances", null);
        assertEquals(1, response.getAsJsonArray("cloudEndpointInstances").size());
        JsonObject endpoint = response.getAsJsonArray("cloudEndpointInstances").get(0).getAsJsonObject();
        assertEquals(ENDPOINT, endpoint.get("cloudEndpointPid").getAsString());
        assertEquals(FACTORY, endpoint.get("cloudConnectionFactoryPid").getAsString());
        assertEquals("DISCONNECTED", endpoint.get("state").getAsString());
        Set<String> pubsubPids = new HashSet<>();
        response.getAsJsonArray("pubsubInstances").forEach(value -> pubsubPids.add(value.getAsJsonObject().get("pid").getAsString()));
        assertEquals(Set.of("test.publisher", "test.subscriber"), pubsubPids);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldGetStackComponentPids(TransportType type) throws Exception {
        useTransport(type, "CLD-V1", "cloudconnection/v1");
        JsonObject response = request("POST", "/cloudEndpoint/stackComponentPids", endpointRequest(ENDPOINT));
        Set<String> pids = new HashSet<>();
        response.getAsJsonArray("pids").forEach(value -> pids.add(value.getAsString()));
        assertEquals(Set.of(ENDPOINT, "data.123", "transport.123"), pids);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldCreateCloudEndpoint(TransportType type) throws Exception {
        useTransport(type, "CLD-V1", "cloudconnection/v1");
        request("POST", "/cloudEndpoint", endpointRequest("custom.created"));
        verify(this.factory).createConfiguration("custom.created");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldDeleteCloudEndpoint(TransportType type) throws Exception {
        useTransport(type, "CLD-V1", "cloudconnection/v1");
        request("DELETE", "/cloudEndpoint", endpointRequest(ENDPOINT));
        verify(this.factory).deleteConfiguration(ENDPOINT);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldGetCloudComponentFactories(TransportType type) throws Exception {
        useTransport(type, "CLD-V1", "cloudconnection/v1");
        JsonObject response = request("GET", "/factories", null);
        assertEquals(1, response.getAsJsonArray("cloudConnectionFactories").size());
        assertEquals(FACTORY, response.getAsJsonArray("cloudConnectionFactories").get(0).getAsJsonObject()
                .get("cloudConnectionFactoryPid").getAsString());
        Set<String> pids = new HashSet<>();
        response.getAsJsonArray("pubSubFactories").forEach(value -> pids.add(value.getAsJsonObject().get("factoryPid").getAsString()));
        assertEquals(Set.of(PUBLISHER_FACTORY, SUBSCRIBER_FACTORY), pids);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldCreatePublisherInstance(TransportType type) throws Exception {
        useTransport(type, "CLD-V1", "cloudconnection/v1");
        createPubSub("new.publisher", PUBLISHER_FACTORY);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldCreateSubscriberInstance(TransportType type) throws Exception {
        useTransport(type, "CLD-V1", "cloudconnection/v1");
        createPubSub("new.subscriber", SUBSCRIBER_FACTORY);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldDeletePublisherInstance(TransportType type) throws Exception {
        useTransport(type, "CLD-V1", "cloudconnection/v1");
        request("DELETE", "/pubSub", Map.of("pid", "test.publisher"));
        verify(this.configurations).deleteFactoryConfiguration("test.publisher", true);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldDeleteSubscriberInstance(TransportType type) throws Exception {
        useTransport(type, "CLD-V1", "cloudconnection/v1");
        request("DELETE", "/pubSub", Map.of("pid", "test.subscriber"));
        verify(this.configurations).deleteFactoryConfiguration("test.subscriber", true);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldGetConfigurations(TransportType type) throws Exception {
        useTransport(type, "CLD-V1", "cloudconnection/v1");
        when(this.configurations.getComponentConfiguration("transport.123"))
                .thenReturn(new ComponentConfigurationImpl("transport.123", null, Map.of("username", "local.user")));
        when(this.configurations.getComponentConfiguration("test.publisher"))
                .thenReturn(new ComponentConfigurationImpl("test.publisher", null, Map.of("app.id", "设备")));
        JsonObject response = request("POST", "/configurations", Map.of("pids", List.of("transport.123", "test.publisher")));
        Map<String, JsonObject> configs = new HashMap<>();
        response.getAsJsonArray("configs").forEach(value -> configs.put(value.getAsJsonObject().get("pid").getAsString(), value.getAsJsonObject()));
        assertEquals(Set.of("transport.123", "test.publisher"), configs.keySet());
        assertEquals("local.user", configs.get("transport.123").getAsJsonObject("properties").getAsJsonObject("username").get("value").getAsString());
        assertEquals("设备", configs.get("test.publisher").getAsJsonObject("properties").getAsJsonObject("app.id").get("value").getAsString());
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    @SuppressWarnings("unchecked")
    void shouldUpdateStackComponentConfigurations(TransportType type) throws Exception {
        useTransport(type, "CLD-V1", "cloudconnection/v1");
        request("PUT", "/configurations", Map.of("configs", List.of(Map.of("pid", "transport.123", "properties",
                Map.of("username", Map.of("type", "STRING", "value", "updated.user"),
                        "keep-alive", Map.of("type", "INTEGER", "value", 30)))), "takeSnapshot", true));
        ArgumentCaptor<List<ComponentConfiguration>> configs = ArgumentCaptor.forClass(List.class);
        verify(this.configurations).updateConfigurations(configs.capture(), eq(true));
        assertEquals(1, configs.getValue().size());
        assertEquals("transport.123", configs.getValue().getFirst().getPid());
        assertEquals(Map.of("username", "updated.user", "keep-alive", 30), configs.getValue().getFirst().getConfigurationProperties());
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldConnectEndpoint(TransportType type) throws Exception {
        useTransport(type, "CLD-V1", "cloudconnection/v1");
        request("POST", "/cloudEndpoint/connect", Map.of("cloudEndpointPid", ENDPOINT));
        verify(this.manager).connect();
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldDisconnectEndpoint(TransportType type) throws Exception {
        useTransport(type, "CLD-V1", "cloudconnection/v1");
        request("POST", "/cloudEndpoint/disconnect", Map.of("cloudEndpointPid", ENDPOINT));
        verify(this.manager).disconnect();
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldCheckEndpointStatus(TransportType type) throws Exception {
        useTransport(type, "CLD-V1", "cloudconnection/v1");
        assertEquals(false, request("POST", "/cloudEndpoint/isConnected", Map.of("cloudEndpointPid", ENDPOINT)).get("connected").getAsBoolean());
        when(this.manager.isConnected()).thenReturn(true);
        assertEquals(true, request("POST", "/cloudEndpoint/isConnected", Map.of("cloudEndpointPid", ENDPOINT)).get("connected").getAsBoolean());
    }

    private void createPubSub(String pid, String factoryPid) throws Exception {
        request("POST", "/pubSub", Map.of("pid", pid, "factoryPid", factoryPid, "cloudEndpointPid", ENDPOINT));
        verify(this.configurations).createFactoryConfiguration(factoryPid, pid,
                Map.of(CloudConnectionConstants.CLOUD_ENDPOINT_SERVICE_PID_PROP_NAME.value(), ENDPOINT), true);
    }

    private Map<String, String> endpointRequest(String pid) {
        return Map.of("cloudConnectionFactoryPid", FACTORY, "cloudEndpointPid", pid);
    }

    private Map<String, Object> pubsubProperties(String factoryPid) {
        return Map.of(ConfigurationAdmin.SERVICE_FACTORYPID, factoryPid,
                CloudConnectionConstants.CLOUD_ENDPOINT_SERVICE_PID_PROP_NAME.value(), ENDPOINT);
    }

    private ComponentDescriptionDTO description(String factoryPid, Class<?> serviceInterface) {
        ComponentDescriptionDTO description = new ComponentDescriptionDTO();
        description.name = factoryPid;
        description.serviceInterfaces = new String[] { serviceInterface.getName() };
        description.properties = Map.of("service.pid", factoryPid,
                CloudConnectionConstants.CLOUD_CONNECTION_FACTORY_PID_PROP_NAME.value(), FACTORY);
        return description;
    }

    private void register(Class<?> serviceInterface, String pid, Object service, Map<String, Object> additional) {
        Map<String, Object> properties = new HashMap<>(additional);
        properties.put(ConfigurationService.KURA_SERVICE_PID, pid);
        this.registrations.add(this.context.registerService(serviceInterface.getName(), service, new Hashtable<>(properties)));
    }

    private JsonObject request(String method, String path, Object body) {
        MethodSpec spec = new MethodSpec(method, "DELETE".equals(method) ? "DEL" : method);
        if (body == null) { whenRequestIsPerformed(spec, path); }
        else { whenRequestIsPerformed(spec, path, this.gson.toJson(body)); }
        Response response = expectResponse();
        assertEquals(200, response.getStatus(), () -> response.getBody().orElse(""));
        return response.getBody().filter(value -> !value.isBlank())
                .map(value -> JsonParser.parseString(value).getAsJsonObject()).orElseGet(JsonObject::new);
    }

    @Test
    void httpRequiresCredentials() {
        useTransport(TransportType.REST, "CLD-V1", "cloudconnection/v1");
        givenBasicCredentials(Optional.empty());
        whenRequestIsPerformed(new MethodSpec("GET"), "/instances");
        thenResponseCodeIs(401);
    }

    @Test
    void httpRejectsIncorrectPassword() {
        useTransport(TransportType.REST, "CLD-V1", "cloudconnection/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:wrong-password"));
        whenRequestIsPerformed(new MethodSpec("GET"), "/instances");
        thenResponseCodeIs(401);
    }

    @Test
    void httpRejectsIdentityWithoutCloudPermission() throws Exception {
        this.http.identityFixture().create("cloud.reader", "Endpoint-Reader-1!", List.of());
        useTransport(TransportType.REST, "CLD-V1", "cloudconnection/v1");
        givenBasicCredentials(Optional.of("cloud.reader:Endpoint-Reader-1!"));
        whenRequestIsPerformed(new MethodSpec("GET"), "/instances");
        thenResponseCodeIs(403);
    }

    @Test
    void httpAcceptsCloudPermissionWithoutAdministratorRole() throws Exception {
        this.http.identityFixture().create("cloud.reader", "Endpoint-Reader-1!", List.of("rest.cloudconnection"));
        useTransport(TransportType.REST, "CLD-V1", "cloudconnection/v1");
        givenBasicCredentials(Optional.of("cloud.reader:Endpoint-Reader-1!"));
        JsonObject response = request("GET", "/instances", null);
        assertEquals(ENDPOINT, response.getAsJsonArray("cloudEndpointInstances").get(0).getAsJsonObject()
                .get("cloudEndpointPid").getAsString());
    }
}
