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
 *******************************************************************************/
package org.eclipse.kura.endpoint;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.nio.file.Path;
import java.util.*;
import jakarta.ws.rs.core.Response.Status;
import org.eclipse.kura.configuration.ConfigurableComponent;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.security.keystore.KeystoreService;
import org.eclipse.kura.core.testutil.requesthandler.TransportType;
import org.eclipse.kura.core.testutil.requesthandler.Transport.MethodSpec;
import org.eclipse.kura.internal.rest.service.listing.provider.RestServiceListingProvider;
import org.eclipse.kura.internal.rest.service.listing.provider.test.*;
import org.eclipse.kura.internal.rest.service.listing.provider.test.constants.ServiceListeningTestConstants;
import org.eclipse.osgi.launch.EquinoxFactory;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.osgi.framework.*;
import org.osgi.framework.launch.Framework;
import org.osgi.service.component.ComponentContext;
import org.osgi.service.component.runtime.ServiceComponentRuntime;
import org.osgi.service.component.runtime.dto.ComponentDescriptionDTO;
import org.osgi.service.component.runtime.dto.ReferenceDTO;
import com.eclipsesource.json.Json;
import com.eclipsesource.json.JsonArray;

class ServiceListingEndpointsIT extends EndpointTestBase {
    private static final String METHOD_SPEC_GET = "GET";
    private static final String METHOD_SPEC_POST = "POST";
    private static final String PREFIX = "org.eclipse.kura.internal.rest.service.listing.provider.test.";
    @TempDir Path storage;
    private Framework framework;
    private BundleContext registry;
    private RestServiceListingProvider endpoint;
    private TargetFilterTestService target;
    private final List<ServiceRegistration<?>> registrations = new ArrayList<>();

    @BeforeEach
    void registerEndpoint() throws Exception {
        this.registrations.clear();
        this.target = null;
        this.endpoint = null;
        this.framework = new EquinoxFactory().newFramework(Map.of(Constants.FRAMEWORK_STORAGE, this.storage.toString(),
                Constants.FRAMEWORK_STORAGE_CLEAN, Constants.FRAMEWORK_STORAGE_CLEAN_ONFIRSTINIT));
        this.framework.start();
        this.registry = this.framework.getBundleContext();
        this.target = new TargetFilterTestService();
        this.target.activate();
        this.registrations.add(this.registry.registerService(ConfigurableComponent.class, this.target,
                new Hashtable<>(Map.of("kura.service.pid", PREFIX + "TargetFilterTestService"))));
        Object keystore = mock(KeystoreService.class, withSettings().extraInterfaces(ConfigurableComponent.class));
        this.registrations.add(this.registry.registerService(new String[] {
                KeystoreService.class.getName(), ConfigurableComponent.class.getName() }, keystore,
                new Hashtable<>(Map.of("kura.service.pid", "SSLKeystore"))));

        // These are controlled SCR/ConfigurationService boundaries matching the three upstream descriptors.
        ComponentDescriptionDTO first = descriptor("TestFactory1",
                new String[] { TestInterface.class.getName(), ConfigurableComponent.class.getName() },
                Map.of("testProperty", "testValue"));
        ComponentDescriptionDTO second = descriptor("TestFactory2",
                new String[] { ConfigurableComponent.class.getName(), OtherTestInterface.class.getName() },
                Map.of("testProperty", new String[] { "value1", "value2" }));
        ComponentDescriptionDTO targetDescription = descriptor("TargetFilterTestService",
                new String[] { ConfigurableComponent.class.getName() }, Map.of());
        ReferenceDTO reference = new ReferenceDTO();
        reference.name = "TestInterface";
        reference.interfaceName = TestInterface.class.getName();
        targetDescription.references = new ReferenceDTO[] { reference };
        ServiceComponentRuntime scr = mock(ServiceComponentRuntime.class);
        when(scr.getComponentDescriptionDTOs()).thenReturn(List.of(first, second, targetDescription));
        ConfigurationService configuration = mock(ConfigurationService.class);
        when(configuration.getFactoryComponentPids()).thenReturn(Set.of(first.name, second.name));
        ComponentContext context = mock(ComponentContext.class);
        when(context.getBundleContext()).thenReturn(this.registry);
        this.endpoint = new RestServiceListingProvider();
        this.endpoint.setConfigurationService(configuration);
        this.endpoint.setServiceComponentRuntime(scr);
        this.endpoint.activate(context);
        this.endpoint.bindRequestHandlerRegistry(this.cloud);
        this.http.resource(this.endpoint);
    }

    private static ComponentDescriptionDTO descriptor(String name, String[] interfaces, Map<String, Object> properties) {
        ComponentDescriptionDTO result = new ComponentDescriptionDTO();
        result.name = PREFIX + name;
        result.serviceInterfaces = interfaces;
        result.properties = properties;
        result.references = new ReferenceDTO[0];
        return result;
    }

    @AfterEach
    void unregisterEndpoint() throws Exception {
        try {
            if (this.endpoint != null) { this.endpoint.unbindRequestHandlerRegistry(this.cloud); }
            this.registrations.forEach(ServiceRegistration::unregister);
            this.registrations.clear();
            if (this.target != null) { this.target.deactivate(); }
        } finally {
            if (this.framework != null) {
                this.framework.stop();
                assertEquals(FrameworkEvent.STOPPED, this.framework.waitForStop(5000).getType());
            }
        }
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReturnNotFoundIfNoServiceIsRegistered(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), "/nothing");

        thenResponseCodeIs(404);
    }

    @ParameterizedTest
    @EnumSource(value = TransportType.class, names = "REST")
    public void restShouldReturnUnauthorizedStatusWhenNoRestPermissionIsGiven(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");

        givenIdentity("noAuthUser", Optional.of("Endpoint-User-1!"), Collections.emptyList());
        givenBasicCredentials(Optional.empty());

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), "/servicePids");

        thenResponseCodeIs(401);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReturnListOfAllServices(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");

        givenRegisteredService(TestInterface.class, "TestService", Collections.emptyMap());
        givenIdentity("authUser", Optional.of("Endpoint-User-2!"), Collections.emptyList());
        givenBasicCredentials(Optional.of("authUser:Endpoint-User-2!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), "/servicePids");

        thenRequestSucceeds();
        thenResponseContainsPid("TestService");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReturnListOfFilteredServices(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/byInterface",
                ServiceListeningTestConstants.COMPLETE_POST_BODY);

        thenRequestSucceeds();
        thenResponseBodyEqualsJson(ServiceListeningTestConstants.FILTERED_SERVICES_RESPONSE);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReturnErrorMessageWhenRequestBodyIsNull(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/byInterface",
                ServiceListeningTestConstants.NULL_POST_BODY);

        thenResponseCodeIs(Status.BAD_REQUEST.getStatusCode());
        thenResponseBodyEqualsJson(ServiceListeningTestConstants.NULL_BODY_RESPONSE);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReturnErrorMessageWhenRequestBodyIsEmpty(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/byInterface",
                ServiceListeningTestConstants.EMPTY_POST_BODY);

        thenResponseCodeIs(Status.BAD_REQUEST.getStatusCode());
        thenResponseBodyEqualsJson(ServiceListeningTestConstants.EMPTY_BODY_RESPONSE);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReturnErrorMessageWhenRequestBodyHasNullField(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/byInterface",
                ServiceListeningTestConstants.NULL_FIELD_POST_BODY);

        thenResponseCodeIs(Status.BAD_REQUEST.getStatusCode());
        thenResponseBodyEqualsJson(ServiceListeningTestConstants.NULL_FIELD_BODY_RESPONSE);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReturnErrorMessageWhenRequestBodyHasEmptyField(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/byInterface",
                ServiceListeningTestConstants.EMPTY_FIELD_POST_BODY);

        thenResponseCodeIs(Status.BAD_REQUEST.getStatusCode());
        thenResponseBodyEqualsJson(ServiceListeningTestConstants.EMPTY_FIELD_BODY_RESPONSE);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldSupportPropertyMatchFilter(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));
        givenRegisteredService(TestInterface.class, "foo", Collections.singletonMap("foo", "bar"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/byProperty",
                "{\"name\":\"foo\",\"value\":\"bar\"}");

        thenRequestSucceeds();
        thenResponseContainsPid("foo");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldSupportPropertyMatchFilterWithArray(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));
        givenRegisteredService(TestInterface.class, "foo",
                Collections.singletonMap("foo", new String[] { "bar", "baz" }));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/byProperty",
                "{\"name\":\"foo\",\"value\":\"bar\"}");

        thenRequestSucceeds();
        thenResponseContainsPid("foo");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldSupportPropertyPresenceFilter(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        givenRegisteredService(TestInterface.class, "foo", Collections.singletonMap("foo", "bar"));
        givenRegisteredService(TestInterface.class, "bar", Collections.singletonMap("foo", "baz"));
        givenRegisteredService(TestInterface.class, "baz", Collections.singletonMap("fooo", "bar"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/byProperty", "{\"name\":\"foo\"}");

        thenRequestSucceeds();
        thenResponseContainsPid("foo");
        thenResponseContainsPid("bar");
        thenResponseDoesNotContainPid("baz");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldSupportNotFilter(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        givenRegisteredService(TestInterface.class, "foo", Collections.singletonMap("foo", "bar"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/byProperty",
                "{\"not\": {\"name\":\"foo\",\"value\":\"bar\"} }");

        thenRequestSucceeds();
        thenResponseDoesNotContainPid("foo");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldSupportAndFilter(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        givenRegisteredService(TestInterface.class, "foo", Collections.singletonMap("foo", "bar"));
        givenRegisteredService(TestInterface.class, "bar", Collections.singletonMap("foo", "bar"));
        givenRegisteredService(TestInterface.class, "baz", Collections.singletonMap("fooo", "bar"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/byProperty",
                "{\"and\": [ {\"name\":\"foo\",\"value\":\"bar\"}, {\"name\":\"kura.service.pid\",\"value\":\"foo\"} ] }");

        thenRequestSucceeds();
        thenResponseContainsPid("foo");
        thenResponseDoesNotContainPid("bar");
        thenResponseDoesNotContainPid("baz");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldSupportOrFilter(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        givenRegisteredService(TestInterface.class, "foo", Collections.singletonMap("foo", "baz"));
        givenRegisteredService(TestInterface.class, "bar", Collections.singletonMap("foo", "bar"));
        givenRegisteredService(TestInterface.class, "baz", Collections.singletonMap("fooo", "bar"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/byProperty",
                "{\"or\": [ {\"name\":\"fooo\" }, {\"name\":\"foo\",\"value\":\"bar\"} ] }");

        thenRequestSucceeds();
        thenResponseContainsPid("baz");
        thenResponseContainsPid("bar");
        thenResponseDoesNotContainPid("foo");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldSupportServicesSatisfyingReference(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        givenRegisteredService(TestInterface.class, "foo", Collections.singletonMap("foo", "baz"));
        givenRegisteredService(TestInterface.class, "bar", Collections.singletonMap("foo", "bar"));
        givenRegisteredService(OtherTestInterface.class, "baz", Collections.singletonMap("fooo", "bar"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/satisfyingReference",
                "{\"pid\": \"org.eclipse.kura.internal.rest.service.listing.provider.test.TargetFilterTestService\","
                        + " \"referenceName\": \"TestInterface\" }");

        thenRequestSucceeds();
        thenResponseContainsPid("foo");
        thenResponseContainsPid("bar");
        thenResponseDoesNotContainPid("baz");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldSupportListingFactoryPids(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), "/factoryPids");

        thenRequestSucceeds();
        thenResponseContainsPid("org.eclipse.kura.internal.rest.service.listing.provider.test.TestFactory1");
        thenResponseContainsPid("org.eclipse.kura.internal.rest.service.listing.provider.test.TestFactory2");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldSupportListingFactorysPidByInterface(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/factoryPids/byInterface",
                "{\"interfaceNames\":[\"org.eclipse.kura.internal.rest.service.listing.provider.test.TestInterface\"]}");

        thenRequestSucceeds();
        thenResponseContainsPid("org.eclipse.kura.internal.rest.service.listing.provider.test.TestFactory1");
        thenResponseDoesNotContainPid("org.eclipse.kura.internal.rest.service.listing.provider.test.TestFactory2");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldSupportListingFactoryPidsSpecifyingMultipleInterfaces(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/factoryPids/byInterface",
                "{\"interfaceNames\":[\"org.eclipse.kura.configuration.ConfigurableComponent\", \"org.eclipse.kura.internal.rest.service.listing.provider.test.OtherTestInterface\"]}");

        thenRequestSucceeds();
        thenResponseContainsPid("org.eclipse.kura.internal.rest.service.listing.provider.test.TestFactory2");
        thenResponseDoesNotContainPid("org.eclipse.kura.internal.rest.service.listing.provider.test.TestFactory1");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldSupportListingFactoryPidsByProperty(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/factoryPids/byProperty",
                "{\"name\": \"testProperty\", \"value\": \"testValue\"}");

        thenRequestSucceeds();
        thenResponseContainsPid("org.eclipse.kura.internal.rest.service.listing.provider.test.TestFactory1");
        thenResponseDoesNotContainPid("org.eclipse.kura.internal.rest.service.listing.provider.test.TestFactory2");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldSupportListingFactoryPidsByPropertyOfArrayType(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/factoryPids/byProperty",
                "{\"name\": \"testProperty\", \"value\": \"value2\"}");

        thenRequestSucceeds();
        thenResponseContainsPid("org.eclipse.kura.internal.rest.service.listing.provider.test.TestFactory2");
        thenResponseDoesNotContainPid("org.eclipse.kura.internal.rest.service.listing.provider.test.TestFactory1");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldSupportListingFactoryPidsByPropertyAndObjectClass(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/factoryPids/byProperty",
                "{\"and\": [ {\"name\":\"objectClass\", \"value\":\"org.eclipse.kura.internal.rest.service.listing.provider.test.TestInterface\"}, {\"name\":\"testProperty\",\"value\": \"testValue\"} ] }");

        thenRequestSucceeds();
        thenResponseContainsPid("org.eclipse.kura.internal.rest.service.listing.provider.test.TestFactory1");
        thenResponseDoesNotContainPid("org.eclipse.kura.internal.rest.service.listing.provider.test.TestFactory2");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRejectEmptyFilter(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/byProperty", "{}");

        thenResponseCodeIs(400);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRejectFilterWithSpacesInPropertyName(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/byProperty",
                "{\"name\": \" testProperty \", \"value\": \"value2\"}");

        thenResponseCodeIs(400);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRejectFilterWithMultipleTypes(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/byProperty",
                "{\"and\": [], \"name\": \" testProperty \", \"value\": \"value2\"}");

        thenResponseCodeIs(400);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRejectReferenceWithoutPid(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/satisfyingReference",
                "{ \"referenceName\": \"TestInterface\" }");

        thenResponseCodeIs(400);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRejectReferenceWithEmptyPid(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/satisfyingReference",
                "{ \"pid\": \"\", \"referenceName\": \"TestInterface\" }");

        thenResponseCodeIs(400);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRejectReferenceWithoutReferenceName(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/satisfyingReference",
                "{ \"pid\": \"foo\" }");

        thenResponseCodeIs(400);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRejectReferenceWithEmptyReferenceName(TransportType type) {
        useTransport(type, "SVCLIST-V1", "serviceListing/v1");
        givenBasicCredentials(Optional.of("endpoint.admin:Endpoint-Admin-1!"));

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/servicePids/satisfyingReference",
                "{ \"pid\": \"foo\", \"referenceName\": \"\" }");

        thenResponseCodeIs(400);
    }

    private void givenIdentity(String username, Optional<String> password, List<String> roles) {
        assertDoesNotThrow(() -> this.http.identityFixture().create(username, password.orElseThrow(), roles));
    }

    private <T> void givenRegisteredService(Class<T> type, String pid, Map<String, Object> properties) {
        Dictionary<String, Object> actual = new Hashtable<>(properties);
        actual.put("kura.service.pid", pid);
        this.registrations.add(this.registry.registerService(type, mock(type), actual));
    }

    private void thenResponseContainsPid(String pid) {
        JsonArray responseArray = expectJsonResponse().get("pids").asArray();
        assertTrue(responseArray.values().contains(Json.value(pid)), "Missing " + pid + " in " + responseArray);
    }

    private void thenResponseDoesNotContainPid(String pid) {
        JsonArray responseArray = expectJsonResponse().get("pids").asArray();
        assertFalse(responseArray.values().contains(Json.value(pid)), "Unexpected " + pid + " in " + responseArray);
    }
}
