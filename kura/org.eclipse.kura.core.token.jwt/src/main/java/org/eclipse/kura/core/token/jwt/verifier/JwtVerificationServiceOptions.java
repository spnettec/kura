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
package org.eclipse.kura.core.token.jwt.verifier;

import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

class JwtVerificationServiceOptions {

    private static final String KEY_TRUSTED_ISSUERS = "trusted.issuers";
    private static final String KEY_VERIFICATION_KEY_ALIASES = "verification.key.aliases";
    private static final String KEY_CLOCK_SKEW_SECONDS = "clock.skew.seconds";
    private static final String KEY_REQUIRE_VALID_CERTIFICATE = "require.valid.certificate";

    private static final long DEFAULT_CLOCK_SKEW_SECONDS = 30;
    private static final boolean DEFAULT_REQUIRE_VALID_CERTIFICATE = true;

    private final Set<String> trustedIssuers;
    private final Set<String> verificationKeyAliases;
    private final long clockSkewToleranceSec;
    private final boolean requireValidCertificate;

    public JwtVerificationServiceOptions(final Map<String, Object> properties) {
        this.trustedIssuers = csvToStringSet((String) properties.get(KEY_TRUSTED_ISSUERS));
        this.verificationKeyAliases = csvToStringSet((String) properties.get(KEY_VERIFICATION_KEY_ALIASES));
        this.clockSkewToleranceSec = asLong(properties.get(KEY_CLOCK_SKEW_SECONDS), DEFAULT_CLOCK_SKEW_SECONDS);
        this.requireValidCertificate = asBoolean(properties.get(KEY_REQUIRE_VALID_CERTIFICATE),
                DEFAULT_REQUIRE_VALID_CERTIFICATE);
    }

    Set<String> getTrustedIssuers() {
        return this.trustedIssuers;
    }

    Set<String> getVerificationKeyAliases() {
        return this.verificationKeyAliases;
    }

    long getClockSkewToleranceSec() {
        return this.clockSkewToleranceSec;
    }

    boolean isRequireValidCertificate() {
        return this.requireValidCertificate;
    }

    private static Set<String> csvToStringSet(String csv) {
        if (csv == null || csv.isBlank()) {
            return Collections.emptySet();
        }

        final Set<String> result = new LinkedHashSet<>();
        for (String value : csv.split(",")) {
            if (!value.isBlank()) {
                result.add(value.trim());
            }
        }

        return Collections.unmodifiableSet(result);
    }

    private static long asLong(final Object value, final long defaultValue) {
        return value instanceof Number number ? number.longValue() : defaultValue;
    }

    private static boolean asBoolean(final Object value, final boolean defaultValue) {
        return value instanceof Boolean bool ? bool : defaultValue;
    }

}
