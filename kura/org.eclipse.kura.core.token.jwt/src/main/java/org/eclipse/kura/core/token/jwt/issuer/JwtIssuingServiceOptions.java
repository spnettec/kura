/*******************************************************************************
 * Copyright (c) 2026 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.core.token.jwt.issuer;

import java.time.Duration;
import java.util.Map;
import java.util.Optional;

class JwtIssuingServiceOptions {

    private static final String KEY_SIGNING_KEY_ALIAS = "signing.key.alias";
    private static final String KEY_ISSUER = "issuer";
    private static final String KEY_MAXIMUM_LIFETIME_SECONDS = "maximum.lifetime.seconds";

    private static final String DEFAULT_SIGNING_KEY_ALIAS = "jwt-signing-key";
    private static final String DEFAULT_ISSUER = "kura";
    private static final int DEFAULT_MAXIMUM_LIFETIME_SECONDS = 3600;

    private final String signingKeyAlias;
    private final String issuer;
    private final Optional<Duration> maximumLifetime;

    JwtIssuingServiceOptions(final Map<String, Object> properties) {
        this.signingKeyAlias = (String) properties.getOrDefault(KEY_SIGNING_KEY_ALIAS, DEFAULT_SIGNING_KEY_ALIAS);
        this.issuer = (String) properties.getOrDefault(KEY_ISSUER, DEFAULT_ISSUER);

        final int maximumLifetimeSeconds = asInt(properties.get(KEY_MAXIMUM_LIFETIME_SECONDS),
                DEFAULT_MAXIMUM_LIFETIME_SECONDS);

        if (maximumLifetimeSeconds > 0) {
            this.maximumLifetime = Optional.of(Duration.ofSeconds(maximumLifetimeSeconds));
        } else {
            this.maximumLifetime = Optional.empty();
        }
    }

    String getSigningKeyAlias() {
        return this.signingKeyAlias;
    }

    String getIssuer() {
        return this.issuer;
    }

    Optional<Duration> getMaximumLifetime() {
        return this.maximumLifetime;
    }

    private static int asInt(final Object value, final int defaultValue) {
        return value instanceof Number number ? number.intValue() : defaultValue;
    }

}
