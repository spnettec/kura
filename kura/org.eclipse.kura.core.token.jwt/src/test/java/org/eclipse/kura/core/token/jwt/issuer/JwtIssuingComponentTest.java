/*
 * Copyright (c) 2026 Contributors to the Eclipse Foundation.
 * SPDX-License-Identifier: EPL-2.0
 */
package org.eclipse.kura.core.token.jwt.issuer;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.security.KeyPairGenerator;
import java.security.KeyStore.PrivateKeyEntry;
import java.time.Duration;
import java.util.Map;

import com.auth0.jwt.JWT;
import org.apache.sling.testing.mock.osgi.junit5.OsgiContext;
import org.apache.sling.testing.mock.osgi.junit5.OsgiContextExtension;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.security.keystore.KeystoreService;
import org.eclipse.kura.security.token.TokenIssueRequest;
import org.eclipse.kura.security.token.TokenIssuingService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;

/** Fast component checks load the existing OSGI-INF descriptor, not generated annotations. */
@ExtendWith(OsgiContextExtension.class)
class JwtIssuingComponentTest {
    final OsgiContext context = new OsgiContext();
    final TokenIssueRequest request = TokenIssueRequest.builder("device1").build();

    @Test void activatesFromHandwrittenXmlAndReportsMissingKey() throws Exception {
        var service = context.registerInjectActivateService(new JwtIssuingService(),
                Map.of("maximum.lifetime.seconds", 60, "issuer", "component-test"));
        assertSame(service, context.getService(TokenIssuingService.class));
        assertEquals(Duration.ofSeconds(60), service.getMaximumLifetime().orElseThrow());
        assertThrows(KuraException.class, () -> service.issue(request));
        service.updated(Map.of("maximum.lifetime.seconds", 30));
        assertEquals(Duration.ofSeconds(30), service.getMaximumLifetime().orElseThrow());
        service.deactivate();
        assertTrue(service.getMaximumLifetime().isEmpty());
        assertThrows(KuraException.class, () -> service.issue(request));
    }

    @Test void bindsConfiguredKeystoreAndLosesIssuerOnUnbind() throws Exception {
        var generator = KeyPairGenerator.getInstance("RSA");
        generator.initialize(2048);
        var keys = generator.generateKeyPair();
        var key = mock(PrivateKeyEntry.class);
        when(key.getPrivateKey()).thenReturn(keys.getPrivate());
        var store = mock(KeystoreService.class);
        when(store.getEntry("jwt-signing-key")).thenReturn(key);
        context.registerService(KeystoreService.class, store, Map.of("kura.service.pid", "test.keystore"));
        var service = context.registerInjectActivateService(new JwtIssuingService(), Map.of("issuer", "component-test"));
        assertEquals("device1", JWT.decode(service.issue(request)).getSubject());
        // Direct callbacks test state transitions; the real SCR dynamic transition is covered by osgi-it.
        service.unsetKeystoreService(mock(KeystoreService.class));
        assertNotNull(service.issue(request));
        service.unsetKeystoreService(store);
        assertThrows(KuraException.class, () -> service.issue(request));
        service.setKeystoreService(store, Map.of("kura.service.pid", "test.keystore"));
        assertNotNull(service.issue(request));
        service.deactivate();
        assertThrows(KuraException.class, () -> service.issue(request));
    }
}
