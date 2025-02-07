/*******************************************************************************
 * Copyright (c) 2018, 2021 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.core.ssl;

import static java.util.Objects.isNull;

public class SslManagerServiceOptions {

    public enum RevocationCheckMode {
        PREFER_OCSP,
        PREFER_CRL,
        CRL_ONLY
    }

    private final SslManagerServiceOCD properties;

    private final String sslProtocol;
    private final String sslCiphers;
    private final boolean sslHNVerification;
    private final boolean sslRevocationCheckEnabled;
    private final RevocationCheckMode sslRevocationMode;
    private final boolean sslRevocationSoftFail;

    public SslManagerServiceOptions(SslManagerServiceOCD properties) {
        if (isNull(properties)) {
            throw new IllegalArgumentException("SSL Options cannot be null!");
        }
        this.properties = properties;
        this.sslProtocol = properties.ssl_default_protocol();
        this.sslCiphers = properties.ssl_default_cipherSuites();
        this.sslHNVerification = properties.ssl_hostname_verification();
        this.sslRevocationCheckEnabled = properties.ssl_revocation_check_enabled();
        this.sslRevocationMode = RevocationCheckMode.valueOf(properties.ssl_revocation_mode());
        this.sslRevocationSoftFail = properties.ssl_revocation_soft_fail();
    }

    public SslManagerServiceOCD getConfigurationProperties() {
        return this.properties;
    }

    /**
     * Returns the ssl.default.protocol.
     *
     * @return
     */
    public String getSslProtocol() {
        return this.sslProtocol;
    }

    /**
     * Returns the ssl.default.trustStore.
     *
     * @return
     */
    public String getSslCiphers() {
        return this.sslCiphers;
    }

    /**
     * Returns the ssl.hostname.verification
     *
     * @return
     */
    public Boolean isSslHostnameVerification() {
        return this.sslHNVerification;
    }

    public boolean isSslRevocationCheckEnabled() {
        return sslRevocationCheckEnabled;
    }

    public RevocationCheckMode getRevocationCheckMode() {
        return sslRevocationMode;
    }

    public boolean isSslRevocationSoftFail() {
        return sslRevocationSoftFail;
    }

    @Override
    public int hashCode() {
        final int prime = 31;
        int result = 1;
        result = prime * result + (this.properties == null ? 0 : this.properties.hashCode());
        return result;
    }

    @Override
    public boolean equals(Object obj) {
        if (this == obj) {
            return true;
        }
        if (obj == null) {
            return false;
        }
        if (!(obj instanceof SslManagerServiceOptions)) {
            return false;
        }
        SslManagerServiceOptions other = (SslManagerServiceOptions) obj;
        if (this.properties == null) {
            if (other.properties != null) {
                return false;
            }
        } else if (!this.properties.equals(other.properties)) {
            return false;
        }
        return true;
    }
}
