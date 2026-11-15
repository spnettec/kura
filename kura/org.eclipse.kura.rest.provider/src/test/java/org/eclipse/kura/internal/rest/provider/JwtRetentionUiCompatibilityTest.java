/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.internal.rest.provider;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import java.util.Properties;

import javax.xml.parsers.DocumentBuilderFactory;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.w3c.dom.Element;

class JwtRetentionUiCompatibilityTest {

    @ParameterizedTest
    @ValueSource(ints = { 0, 300, 1177 })
    void existingUiConfigurationKeepsItsRetentionValue(int seconds) {
        RestServiceOptions options = new RestServiceOptions(Map.of("auth.jwt.used.refresh.token.retention", seconds));
        assertEquals(Duration.ofSeconds(seconds), options.getJwtRefreshTokenFamilyRetention());
    }

    @Test
    void defaultRetentionRemainsFiveMinutes() {
        assertEquals(Duration.ofSeconds(300), new RestServiceOptions(Map.of()).getJwtRefreshTokenFamilyRetention());
    }

    @Test
    void bothLanguagesResolveEveryMetatypeLabelAndPreserveConfigKeys() throws Exception {
        var factory = DocumentBuilderFactory.newInstance();
        factory.setNamespaceAware(true);
        try (InputStream xml = getClass().getResourceAsStream(
                "/OSGI-INF/metatype/org.eclipse.kura.internal.rest.provider.RestService.xml")) {
            assertNotNull(xml);
            var document = factory.newDocumentBuilder().parse(xml);
            var attributes = document.getElementsByTagNameNS("*", "AD");
            boolean retentionFound = false;
            for (String language : new String[] { "en", "zh" }) {
                Properties strings = new Properties();
                try (InputStream stream = getClass().getResourceAsStream(
                        "/OSGI-INF/l10n/RestService_" + language + ".properties")) {
                    assertNotNull(stream);
                    strings.load(new InputStreamReader(stream, StandardCharsets.UTF_8));
                }
                for (int i = 0; i < attributes.getLength(); i++) {
                    Element attribute = (Element) attributes.item(i);
                    for (String field : new String[] { "name", "description" }) {
                        String key = attribute.getAttribute(field);
                        if (key.startsWith("%")) {
                            assertTrue(strings.containsKey(key.substring(1)), language + " lacks " + key);
                        }
                    }
                    if (attribute.getAttribute("id").equals("auth.jwt.used.refresh.token.retention")) {
                        retentionFound = true;
                        assertEquals("300", attribute.getAttribute("default"));
                        assertEquals("0", attribute.getAttribute("min"));
                    }
                    if (attribute.getAttribute("id").equals("auth.jwt.enabled")) {
                        assertEquals("false", attribute.getAttribute("default"));
                    }
                }
                assertTrue(strings.getProperty("authJwtUsedRefreshTokenRetentionDesc").length() > 30);
            }
            assertTrue(retentionFound, "Existing UI and snapshot key must remain available");
        }
    }
}
