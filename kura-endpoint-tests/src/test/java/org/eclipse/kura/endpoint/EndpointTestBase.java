/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.endpoint;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import java.util.*;
import java.util.concurrent.*;
import org.eclipse.kura.core.cloud.CloudServiceImpl;
import org.eclipse.kura.core.data.BaseCloudTests;
import org.eclipse.kura.core.testutil.TestUtil;
import org.eclipse.kura.core.testutil.requesthandler.*;
import org.eclipse.kura.core.testutil.requesthandler.Transport.MethodSpec;
import org.eclipse.kura.cloudconnection.listener.CloudConnectionListener;
import org.eclipse.kura.internal.json.marshaller.unmarshaller.JsonMarshallUnmarshallImpl;
import org.eclipse.kura.rest.provider.test.util.AbstractJwtRestScenario;
import org.eclipse.kura.system.SystemService;
import org.eclipse.kura.system.SystemAdminService;
import org.junit.jupiter.api.*;
import org.osgi.framework.*;
import org.osgi.service.component.ComponentContext;
import org.osgi.service.event.EventAdmin;

/** Real HTTP and SQL-backed MQTT, with explicit component activation instead of global SCR/configuration. */
@Timeout(60)
abstract class EndpointTestBase extends BaseCloudTests {
    protected CloudFixture cloud;
    protected HttpFixture http;
    private ComponentContext cloudContext;
    private ExecutorService birthPublisher;
    private ServiceRegistration<?> registration;
    private RequestAssertions assertions;

    @BeforeEach
    @SuppressWarnings({ "rawtypes", "unchecked" })
    void startEndpoints() throws Exception {
        this.assertions = null;
        this.cloud = null;
        this.birthPublisher = null;
        this.registration = null;
        this.http = new HttpFixture();
        this.http.start();
        this.cloudContext = mock(ComponentContext.class);
        BundleContext registry = mock(BundleContext.class);
        when(this.cloudContext.getBundleContext()).thenReturn(registry);
        Dictionary<String, Object> properties = new Hashtable<>();
        properties.put("kura.service.pid", "endpoint.cloud");
        when(this.cloudContext.getProperties()).thenReturn(properties);
        this.registration = mock(ServiceRegistration.class);
        when(registry.registerService(anyString(), any(), any(Dictionary.class))).thenReturn(this.registration);
        this.cloud = new CloudFixture();
        this.birthPublisher = (ExecutorService) TestUtil.getFieldValue(this.cloud, "scheduledBirthPublisher");
        this.cloud.setDataService(this.dataService);
        SystemService system = mock(SystemService.class);
        when(system.getDeviceName()).thenReturn("endpoint-test");
        this.cloud.setSystemService(system);
        SystemAdminService systemAdmin = mock(SystemAdminService.class);
        when(systemAdmin.getUptime()).thenReturn("30000");
        this.cloud.setSystemAdminService(systemAdmin);
        this.cloud.setEventAdmin(mock(EventAdmin.class));
        JsonMarshallUnmarshallImpl json = new JsonMarshallUnmarshallImpl();
        this.cloud.setJsonMarshaller(json);
        this.cloud.setJsonUnmarshaller(json);
        this.cloud.start(this.cloudContext, Map.of("kura.service.pid", "endpoint.cloud",
                "payload.encoding", "simple-json", "topic.control-prefix", "EDC"));
        CompletableFuture<Void> connected = new CompletableFuture<>();
        CloudConnectionListener listener = mock(CloudConnectionListener.class);
        doAnswer(invocation -> { connected.complete(null); return null; }).when(listener).onConnectionEstablished();
        this.cloud.registerCloudConnectionListener(listener);
        try {
            this.cloud.connect();
            connected.get(5, TimeUnit.SECONDS);
        } finally { this.cloud.unregisterCloudConnectionListener(listener); }
    }

    protected void useTransport(TransportType type, String appId, String servicePath) {
        Transport transport;
        if (type == TransportType.REST) {
            RestTransport rest = new RestTransport(this.http.address(), servicePath);
            rest.setBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));
            transport = rest;
        } else { transport = new MqttTransport(this.brokerUri, appId); }
        this.assertions = new RequestAssertions(transport);
    }

    protected Transport.Response runRequest(String path, MethodSpec method) { return this.assertions.rawRequest(path, method); }

    protected void whenRequestIsPerformed(MethodSpec method, String path) { this.assertions.request(method, path, null); }
    protected void whenRequestIsPerformed(MethodSpec method, String path, String body) { this.assertions.request(method, path, body); }
    protected void thenRequestSucceeds() { this.assertions.success(); }
    protected void thenResponseCodeIs(int status) { this.assertions.status(status); }
    protected void thenResponseBodyIsNotEmpty() { this.assertions.notEmpty(); }
    protected void thenResponseBodyIsEmpty() { this.assertions.empty(); }
    protected void thenResponseBodyEqualsJson(String expected) { this.assertions.json(expected); }

    @AfterEach
    void stopEndpoints() throws Exception {
        try { if (this.assertions != null) { this.assertions.close(); } }
        finally {
            try {
                if (this.cloud != null) {
                    this.cloud.stop(this.cloudContext);
                    assertTrue(this.birthPublisher.awaitTermination(5, TimeUnit.SECONDS));
                    verify(this.registration, times(2)).unregister();
                }
            } finally { if (this.http != null) { this.http.close(); } }
        }
    }

    protected static class CloudFixture extends CloudServiceImpl {
        void start(ComponentContext context, Map<String, Object> properties) { super.activate(context, properties); }
        void stop(ComponentContext context) { super.deactivate(context); }
    }

    protected static class HttpFixture extends AbstractJwtRestScenario implements AutoCloseable {
        void start() throws Exception {
            setUpHttp();
            identities().create("endpoint.admin", "Endpoint-Admin-1!", List.of("kura.admin"));
        }
        org.eclipse.kura.rest.provider.test.util.IdentityFixture identityFixture() { return identities(); }
        void resource(Object resource) { addResource(resource); }
        String address() { return this.baseUrl; }
        @Override
        public void close() throws Exception { tearDownHttp(); }
    }

    private static class RequestAssertions extends AbstractRequestHandlerTest {
        RequestAssertions(Transport transport) { super(transport); }
        void request(MethodSpec method, String path, String body) { whenRequestIsPerformed(method, path, body); }
        Transport.Response rawRequest(String path, MethodSpec method) { return this.transport.runRequest(path, method); }
        void success() { thenRequestSucceeds(); }
        void status(int value) { thenResponseCodeIs(value); }
        void notEmpty() { thenResponseBodyIsNotEmpty(); }
        void empty() { thenResponseBodyIsEmpty(); }
        void json(String value) { thenResponseBodyEqualsJson(value); }
    }
}
