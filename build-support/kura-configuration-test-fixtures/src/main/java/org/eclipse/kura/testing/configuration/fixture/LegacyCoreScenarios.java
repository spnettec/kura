/*******************************************************************************
 * Copyright (c) 2011, 2026 Eurotech and/or its affiliates and others
 * SPDX-License-Identifier: EPL-2.0
 * Contributors: Eurotech, Red Hat Inc, Contributors to the Eclipse Foundation
 ******************************************************************************/
package org.eclipse.kura.testing.configuration.fixture;

import static org.eclipse.kura.cloudconnection.request.RequestHandlerMessageConstants.ARGS_KEY;
import static org.junit.jupiter.api.Assertions.*;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.BooleanSupplier;

import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.KuraPartialSuccessException;
import org.eclipse.kura.cloudconnection.message.KuraMessage;
import org.eclipse.kura.cloudconnection.request.RequestHandler;
import org.eclipse.kura.cloudconnection.request.RequestHandlerContext;
import org.eclipse.kura.cloudconnection.request.RequestHandlerRegistry;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.configuration.XmlComponentConfigurations;
import org.eclipse.kura.marshalling.Marshaller;
import org.eclipse.kura.marshalling.Unmarshaller;
import org.eclipse.kura.message.KuraPayload;
import org.eclipse.kura.message.KuraResponsePayload;
import org.eclipse.kura.system.SystemService;
import org.osgi.framework.BundleContext;
import org.osgi.framework.FrameworkUtil;
import org.osgi.framework.ServiceReference;
import org.osgi.framework.ServiceRegistration;

/** Legacy protocol scenarios executed inside Equinox, against actual SCR services. */
public class LegacyCoreScenarios implements AutoCloseable {
    private static final String PID = "org.eclipse.kura.core.test.IConfigurationServiceTest";
    private static final String XML_PID = "org.eclipse.kura.xml.marshaller.unmarshaller.provider";
    private final BundleContext context;
    private final List<ServiceReference<?>> references = new ArrayList<>();
    private final Map<String, RequestHandler> handlers = new ConcurrentHashMap<>();
    private final ServiceRegistration<RequestHandlerRegistry> registry;
    private final ConfigurationService configuration;
    private final LegacyConfigurationComponent component;

    public LegacyCoreScenarios(BundleContext context) throws Exception {
        this.context = context;
        this.registry = context.registerService(RequestHandlerRegistry.class, new RequestHandlerRegistry() {
            @Override
            public void registerRequestHandler(String id, RequestHandler handler) {
                handlers.put(id, handler);
            }

            @Override
            public void unregister(String id) {
                handlers.remove(id);
            }
        }, null);
        try {
            this.configuration = service(ConfigurationService.class, null);
            this.component = service(LegacyConfigurationComponent.class, null);
            await(() -> !this.component.getProperties().isEmpty(), "SCR configuration defaults");
        } catch (Exception | Error failure) {
            this.registry.unregister();
            this.references.forEach(this.context::ungetService);
            throw failure;
        }
    }

    public void testServiceExists() {
        assertNotNull(this.configuration);
        assertEquals("org.eclipse.kura.core.configuration",
                FrameworkUtil.getBundle(this.configuration.getClass()).getSymbolicName());
    }

    public void testLocalConfiguration() throws Exception {
        assertDefaults(this.component.getProperties());
        long snapshot = this.configuration.snapshot();
        Map<String, Object> changed = new HashMap<>(this.component.getProperties());
        changed.putAll(Map.of("prop.string", "string_prop", "prop.long", 9999L, "prop.double", 99.99D,
                "prop.float", 99.99F, "prop.integer", 99999, "prop.character", '9', "prop.boolean", false,
                "prop.short", (short) 9, "prop.byte", (byte) 9));
        this.configuration.updateConfiguration(PID, changed);
        await(() -> "string_prop".equals(this.component.getProperties().get("prop.string")), "SCR update callback");
        assertProperties(changed, this.component.getProperties());

        Map<String, Object> invalidType = new HashMap<>(changed);
        invalidType.put("prop.long", "AAAA");
        assertRejected(invalidType, KuraErrorCode.CONFIGURATION_ATTRIBUTE_INVALID);
        Map<String, Object> missingRequired = new HashMap<>(changed);
        missingRequired.remove("prop.string");
        // Current updates merge with running properties: omission retains the required value.
        this.configuration.updateConfiguration(PID, missingRequired);
        assertEquals("string_prop", this.configuration.getComponentConfiguration(PID)
                .getConfigurationProperties().get("prop.string"));
        missingRequired.put("prop.string", null);
        assertRejected(missingRequired, KuraErrorCode.CONFIGURATION_REQUIRED_ATTRIBUTE_MISSING);
        assertProperties(changed, this.component.getProperties());

        this.configuration.rollback(snapshot);
        await(() -> "prop.string.value".equals(this.component.getProperties().get("prop.string")), "SCR rollback callback");
        assertDefaults(this.component.getProperties());
    }

    public void testRemoteConfiguration() throws Exception {
        // The transport boundary is RequestHandlerRegistry; no MQTT connection is implied.
        assertDefaults(this.component.getProperties());
        assertDefaults(readConfiguration().getConfigurationProperties());
        long snapshot = snapshotIds(call("CONF-V1", "EXEC", List.of("snapshot"), null)).get(0);

        ComponentConfigurationImpl changed = new ComponentConfigurationImpl();
        changed.setPid(PID);
        changed.setProperties(Map.of("prop.string", "modified_value"));
        XmlComponentConfigurations request = new XmlComponentConfigurations();
        request.setConfigurations(List.of(changed));
        String xml = service(Marshaller.class, "(kura.service.pid=" + XML_PID + ")").marshal(request);
        assertNotNull(xml);
        call("CONF-V1", "PUT", List.of("configurations", PID), xml.getBytes(StandardCharsets.UTF_8));
        await(() -> "modified_value".equals(this.component.getProperties().get("prop.string")), "CONF-V1 async PUT");
        assertEquals("modified_value", readConfiguration().getConfigurationProperties().get("prop.string"));

        call("CONF-V1", "EXEC", List.of("rollback", Long.toString(snapshot)), null);
        await(() -> "prop.string.value".equals(this.component.getProperties().get("prop.string")), "CONF-V1 async rollback");
        assertDefaults(this.component.getProperties());
        assertDefaults(readConfiguration().getConfigurationProperties());
    }

    public void testSnapshotsMaxCount() throws Exception {
        int maximum = service(SystemService.class, null).getKuraSnapshotsCount();
        assertTrue(maximum > 0);
        for (int index = 0; index < maximum * 2; index++) {
            this.configuration.snapshot();
        }
        assertEquals(maximum, this.configuration.getSnapshots().size());
    }

    private void assertRejected(Map<String, Object> properties, KuraErrorCode code) {
        KuraPartialSuccessException failure = assertThrows(KuraPartialSuccessException.class,
                () -> this.configuration.updateConfiguration(PID, properties));
        assertEquals(KuraErrorCode.PARTIAL_SUCCESS, failure.getCode());
        assertEquals(1, failure.getCauses().size());
        assertEquals(code, assertInstanceOf(KuraException.class, failure.getCauses().get(0)).getCode());
    }

    private ComponentConfiguration readConfiguration() throws Exception {
        byte[] body = call("CONF-V1", "GET", List.of("configurations", PID), null);
        XmlComponentConfigurations result = service(Unmarshaller.class, "(kura.service.pid=" + XML_PID + ")")
                .unmarshal(new String(body, StandardCharsets.UTF_8), XmlComponentConfigurations.class);
        assertNotNull(result);
        assertEquals(1, result.getConfigurations().size());
        assertEquals(PID, result.getConfigurations().get(0).getPid());
        return result.getConfigurations().get(0);
    }

    protected byte[] call(String application, String method, List<String> resources, byte[] body) throws Exception {
        await(() -> this.handlers.containsKey(application), "SCR handler registration: " + application);
        RequestHandler handler = this.handlers.get(application);
        assertEquals(application.equals("CONF-V1") ? "org.eclipse.kura.core.configuration" : "org.eclipse.kura.core.inventory",
                FrameworkUtil.getBundle(handler.getClass()).getSymbolicName());
        KuraPayload payload = new KuraPayload();
        payload.setBody(body);
        KuraMessage request = new KuraMessage(payload, Map.of(ARGS_KEY.value(), resources));
        RequestHandlerContext requestContext = new RequestHandlerContext(null, Map.of());
        KuraMessage response = switch (method) {
            case "GET" -> handler.doGet(requestContext, request);
            case "PUT" -> handler.doPut(requestContext, request);
            case "EXEC" -> handler.doExec(requestContext, request);
            default -> throw new IllegalArgumentException(method);
        };
        assertNotNull(response);
        KuraResponsePayload responsePayload = assertInstanceOf(KuraResponsePayload.class, response.getPayload());
        assertEquals(KuraResponsePayload.RESPONSE_CODE_OK, responsePayload.getResponseCode());
        return responsePayload.getBody();
    }

    private static List<Long> snapshotIds(byte[] body) throws Exception {
        assertNotNull(body);
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setNamespaceAware(true);
        factory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
        factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");
        factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "");
        var document = factory.newDocumentBuilder().parse(new ByteArrayInputStream(body));
        assertEquals("snapshot-ids", document.getDocumentElement().getLocalName());
        var ids = document.getElementsByTagNameNS("http://eurotech.com/esf/2.0", "snapshotIds");
        assertEquals(1, ids.getLength());
        return List.of(Long.parseLong(ids.item(0).getTextContent()));
    }

    private static void assertDefaults(Map<String, Object> actual) {
        assertProperties(Map.of("prop.string", "prop.string.value", "prop.long", 1351589588L,
                "prop.double", 13515895.9999988D, "prop.float", 3.14F, "prop.integer", 314,
                "prop.character", 'c', "prop.boolean", true, "prop.short", (short) 255, "prop.byte", (byte) 7), actual);
        assertProperties(Map.of("prop.string.array", new String[] { "value1", "value2", "value3" },
                "prop.long.array", new Long[] { 1351589588L, 1351589589L, 1351589590L },
                "prop.double.array", new Double[] { 13515895.88, 13515895.89, 13515895.90 },
                "prop.float.array", new Float[] { 3.14F, 3.15F, 3.16F },
                "prop.integer.array", new Integer[] { 314, 315, 316 },
                "prop.character.array", new Character[] { 'c', 'd', 'e' },
                "prop.boolean.array", new Boolean[] { true, false, true },
                "prop.short.array", new Short[] { 253, 254, 255 },
                "prop.byte.array", new Byte[] { 7, 8, 9 }), actual);
    }

    private static void assertProperties(Map<String, Object> expected, Map<String, Object> actual) {
        expected.forEach((key, value) -> {
            if (value instanceof Object[] array) {
                assertArrayEquals(array, assertInstanceOf(Object[].class, actual.get(key)), key);
            } else {
                assertEquals(value, actual.get(key), key);
            }
        });
    }

    protected <T> T service(Class<T> contract, String filter) throws Exception {
        long deadline = System.nanoTime() + Duration.ofSeconds(8).toNanos();
        do {
            for (ServiceReference<T> reference : this.context.getServiceReferences(contract, filter)) {
                T result = this.context.getService(reference);
                if (result != null) {
                    this.references.add(reference);
                    return result;
                }
            }
            Thread.sleep(25);
        } while (System.nanoTime() < deadline);
        throw new AssertionError("Missing SCR service " + contract.getName() + " " + filter);
    }

    private static void await(BooleanSupplier condition, String description) throws InterruptedException {
        long deadline = System.nanoTime() + Duration.ofSeconds(8).toNanos();
        while (!condition.getAsBoolean() && System.nanoTime() < deadline) {
            Thread.sleep(25);
        }
        assertTrue(condition.getAsBoolean(), description);
    }

    @Override
    public void close() throws Exception {
        this.registry.unregister();
        this.references.forEach(this.context::ungetService);
    }
}
