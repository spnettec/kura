/*
 * Copyright (c) 2026 Contributors to the Eclipse Foundation.
 * SPDX-License-Identifier: EPL-2.0
 */
package org.eclipse.kura.core.token.jwt.issuer;

import static org.junit.jupiter.api.Assertions.*;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.interfaces.RSAPrivateKey;
import java.security.interfaces.RSAPublicKey;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.security.token.TokenIssueRequest;
import com.auth0.jwt.JWT;
import com.auth0.jwt.algorithms.Algorithm;

class JwtIssuerTest {
    static KeyPair keyPair;
    static JwtIssuer issuer;
    @BeforeAll static void prepare() throws Exception {
        var generator = KeyPairGenerator.getInstance("RSA");
        generator.initialize(2048);
        keyPair = generator.generateKeyPair();
        issuer = new JwtIssuer(new JwtIssuingServiceOptions(Map.of("issuer", "yofc-test", "maximum.lifetime.seconds", 60)), (RSAPrivateKey) keyPair.getPrivate());
    }
    @Test void signsAndVerifiesClaims() throws Exception {
        var token = issuer.issue(TokenIssueRequest.builder("device1").intendedConsumer("gateway").claim("role", "reader").claim("sequence", 17).build());
        var decoded = JWT.require(Algorithm.RSA256((RSAPublicKey) keyPair.getPublic(), null)).withIssuer("yofc-test").withAudience("gateway").build().verify(token);
        assertEquals("device1", decoded.getSubject());
        assertEquals("reader", decoded.getClaim("role").asString());
        assertEquals(17, decoded.getClaim("sequence").asInt());
    }
    @Test void limitsTokenLifetime() throws Exception {
        var token = issuer.issue(TokenIssueRequest.builder("device1").expiresAt(Instant.now().plusSeconds(3600)).build());
        var decoded = JWT.decode(token);
        assertEquals(60, decoded.getExpiresAtAsInstant().getEpochSecond() - decoded.getIssuedAtAsInstant().getEpochSecond());
    }
    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(strings = {"iss", "sub", "aud", "exp", "nbf", "iat", "jti"})
    void rejectsReservedClaims(String claim) {
        assertThrows(KuraException.class, () -> issuer.issue(TokenIssueRequest.builder("device1").claim(claim, "override").build()));
    }
    @Test void honorsShorterRequestedExpiry() throws Exception {
        var expiry = Instant.now().plusSeconds(20);
        var token = issuer.issue(TokenIssueRequest.builder("device1").expiresAt(expiry).build());
        assertEquals(expiry.getEpochSecond(), JWT.decode(token).getExpiresAtAsInstant().getEpochSecond());
    }
    @Test void rejectsUnsupportedClaimType() {
        assertThrows(KuraException.class, () -> issuer.issue(TokenIssueRequest.builder("device1").claim("bad", new Object()).build()));
    }
    @Test void rejectsNonStringMapKeys() {
        assertThrows(KuraException.class, () -> issuer.issue(TokenIssueRequest.builder("device1").claim("settings", Map.of(123, "value")).build()));
    }
}
