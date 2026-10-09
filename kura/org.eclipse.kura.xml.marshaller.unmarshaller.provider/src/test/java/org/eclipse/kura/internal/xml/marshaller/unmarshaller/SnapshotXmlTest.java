package org.eclipse.kura.internal.xml.marshaller.unmarshaller;

import static org.junit.jupiter.api.Assertions.*;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import javax.xml.parsers.DocumentBuilderFactory;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.configuration.XmlComponentConfigurations;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.w3c.dom.Node;

class SnapshotXmlTest {
    private static XmlComponentConfigurations configuration(Map<String, Object> values) {
        var result = new XmlComponentConfigurations();
        result.setConfigurations(List.of(new ComponentConfigurationImpl("test.pid", null, values)));
        return result;
    }

    @ParameterizedTest
    @ValueSource(strings = {"if (a < b && b > 0) { return \"中文\"; }", "<device value='a&b'/>", "plain value"})
    void streamAndDomPreserveConfigurationValues(String value) throws Exception {
        var mapper = new XmlJavaComponentConfigurationsMapper();
        var output = new ByteArrayOutputStream();
        mapper.marshal(output, configuration(Map.of("initCode", value)));
        String xml = output.toString(StandardCharsets.UTF_8);
        if (value.contains("<") || value.contains("&")) {
            assertTrue(xml.contains("<![CDATA["), xml);
        }
        var builder = DocumentBuilderFactory.newInstance().newDocumentBuilder();
        var document = builder.parse(new ByteArrayInputStream(output.toByteArray()));
        XmlComponentConfigurations decoded = mapper.unmarshal(document);
        assertEquals("test.pid", decoded.getConfigurations().getFirst().getPid());
        assertEquals(value, decoded.getConfigurations().getFirst().getConfigurationProperties().get("initCode"));

        var dom = builder.newDocument();
        mapper.marshal(dom, configuration(Map.of("initCode", value)));
        if (value.contains("<") || value.contains("&")) {
            assertEquals(Node.CDATA_SECTION_NODE,
                    dom.getElementsByTagName("esf:value").item(0).getFirstChild().getNodeType());
        }
        XmlComponentConfigurations fromDom = mapper.unmarshal(dom);
        assertEquals(value, fromDom.getConfigurations().getFirst().getConfigurationProperties().get("initCode"));
    }

    @Test
    void roundTripsScalarAndArrayTypes() throws Exception {
        var mapper = new XmlJavaComponentConfigurationsMapper();
        var document = DocumentBuilderFactory.newInstance().newDocumentBuilder().newDocument();
        mapper.marshal(document, configuration(Map.of("count", 42, "enabled", true,
                "names", new String[] {"alpha", "中文"}, "values", new Long[] {1L, 2L})));
        XmlComponentConfigurations decoded = mapper.unmarshal(document);
        var values = decoded.getConfigurations().getFirst().getConfigurationProperties();
        assertEquals(42, values.get("count"));
        assertEquals(true, values.get("enabled"));
        assertArrayEquals(new String[] {"alpha", "中文"}, (String[]) values.get("names"));
        assertArrayEquals(new Long[] {1L, 2L}, (Long[]) values.get("values"));
    }
}
