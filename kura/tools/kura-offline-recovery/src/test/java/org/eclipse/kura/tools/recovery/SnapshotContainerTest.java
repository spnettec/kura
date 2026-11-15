/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import static org.junit.jupiter.api.Assertions.*;

import java.io.ByteArrayOutputStream;
import java.lang.reflect.Array;
import java.util.*;
import java.util.stream.Stream;
import javax.xml.parsers.DocumentBuilderFactory;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.configuration.XmlComponentConfigurations;
import org.eclipse.kura.core.crypto.CryptoServiceImpl;
import org.eclipse.kura.internal.xml.marshaller.unmarshaller.XmlJavaComponentConfigurationsMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.Arguments;

class SnapshotContainerTest {
    final CryptoServiceImpl crypto = CryptoServiceImpl.forSnapshotRecovery(null, true);

    static Stream<Arguments> containers() {
        return Stream.of(new boolean[]{true, false}, new byte[]{-2, 3}, new short[]{-4, 5},
                new int[]{Integer.MIN_VALUE, Integer.MAX_VALUE}, new long[]{Long.MIN_VALUE, Long.MAX_VALUE},
                new float[]{-0.0f, 1.25f}, new double[]{-0.0d, 2.5d}, new char[]{'中', 'x'},
                new boolean[0], new byte[0], new short[0], new int[0], new long[0], new float[0],
                new double[0], new char[0], new String[0], new Integer[0],
                new Vector<>(List.of("<route>&", "second", "<route>&")), new Vector<>(),
                new ArrayList<>(List.of(1, 2, 1)), new ArrayList<>()).map(value -> Arguments.of(value));
    }

    XmlComponentConfigurations configuration(Object value) {
        var configurations = new XmlComponentConfigurations();
        configurations.setConfigurations(List.of(new ComponentConfigurationImpl("containers", null,
                Map.of("kura.service.pid", "containers", "value", value))));
        return configurations;
    }

    @ParameterizedTest @MethodSource("containers")
    void streamAndDomPersistContainerKindOrderAndEmptyValues(Object value) throws Exception {
        var mapper = new XmlJavaComponentConfigurationsMapper(crypto);
        var bytes = new ByteArrayOutputStream();
        mapper.marshal(bytes, configuration(value));
        Object decoded = SnapshotTool.decode(bytes.toByteArray(), crypto, "authenticated")
                .configurations().getFirst().getConfigurationProperties().get("value");
        equivalent(value, decoded);
        var reader = javax.xml.stream.XMLInputFactory.newDefaultFactory()
                .createXMLStreamReader(new java.io.ByteArrayInputStream(bytes.toByteArray()));
        try {
            while (reader.hasNext()) {
                if (reader.isStartElement() && reader.getLocalName().equals("configuration")) { break; }
                reader.next();
            }
            equivalent(value, mapper.paraConfiguration(reader).getConfigurationProperties().get("value"));
        } finally { reader.close(); }
        var document = DocumentBuilderFactory.newDefaultInstance().newDocumentBuilder().newDocument();
        mapper.marshal(document, configuration(value));
        XmlComponentConfigurations fromDom = mapper.unmarshal(document);
        equivalent(value, fromDom.getConfigurations().getFirst().getConfigurationProperties().get("value"));
    }

    @Test void unknownAndContradictoryContainerMarkersAreRejectedBeforeRecovery() throws Exception {
        for (String attributes : List.of("container=\"OTHER\" array=\"true\"", "container=\"\" array=\"true\"",
                "container=\"VECTOR\"", "container=\"PRIMITIVE_ARRAY\" array=\"true\"")) {
            byte[] xml = ("<esf:configurations xmlns:esf=\"http://eurotech.com/esf/2.0\">"
                    + "<esf:configuration pid=\"p\"><esf:properties><esf:property name=\"v\" type=\"String\" "
                    + attributes + "><esf:value>x</esf:value></esf:property></esf:properties>"
                    + "</esf:configuration></esf:configurations>").getBytes(java.nio.charset.StandardCharsets.UTF_8);
            assertThrows(IllegalArgumentException.class, () -> SnapshotTool.decode(xml, crypto, "authenticated"));
        }
    }

    static void equivalent(Object expected, Object actual) {
        assertNotNull(actual);
        assertEquals(expected.getClass(), actual.getClass());
        if (expected.getClass().isArray()) {
            assertEquals(Array.getLength(expected), Array.getLength(actual));
            for (int i=0; i<Array.getLength(expected); i++) { assertEquals(Array.get(expected,i), Array.get(actual,i)); }
        } else { assertEquals(expected, actual); }
    }

    @Test void unsupportedNestedMixedAndNullElementsFailBeforePublishingAnIncompleteSnapshot() {
        for (Object value : List.of(new Object(), new Object[]{"x"}, List.of("x", 1),
                List.of(List.of("nested")), Arrays.asList("x", null), new String[]{null})) {
            assertThrows(IllegalArgumentException.class, () -> new XmlJavaComponentConfigurationsMapper(crypto)
                    .marshal(new ByteArrayOutputStream(), configuration(value)));
        }
    }
}
