/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.configuration;

import java.util.Map;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.osgi.annotation.versioning.ProviderType;

/**
 * Optimistic updates serialized with this provider's ConfigurationService operations.
 * Revisions are opaque, cover secrets as well as visible properties, and expire when
 * the provider restarts. They are neither credentials nor portable content hashes.
 * Direct ConfigurationAdmin writers do not participate in the provider's monitor;
 * its change count is checked at admission, but this API cannot lock such writers.
 */
@ProviderType
public interface ConfigurationRevisionService {

    record Read(ComponentConfiguration configuration, String revision) {
        @Override public String toString() { return "ConfigurationRevisionService.Read[redacted]"; }
    }

    enum Reason { INVALID_ARGUMENT, NOT_FOUND, CONFLICT, UNSUPPORTED }

    /** A rejection before calling the configuration write operation. */
    final class Rejected extends KuraException {
        private static final long serialVersionUID = 1L;
        private final Reason reason;

        public Rejected(Reason reason) {
            super(KuraErrorCode.CONFIGURATION_UPDATE, reason.name());
            this.reason = reason;
        }

        public Reason getReason() { return this.reason; }
    }

    Read readRevision(String pid) throws KuraException;

    /**
     * Classifies the configuration view used by {@link #readRevision(String)}.
     * {@code SELF_CONFIGURING} means the component owns that view. This does not
     * authorize a remote update and does not lock direct ConfigurationAdmin writers.
     *
     * @since 1.5.0
     */
    Applicability applicability(String pid) throws KuraException;

    /** @since 1.5.0 */
    enum ComponentKind { CONFIGURABLE, SELF_CONFIGURING }

    /**
     * @since 1.5.0
     */
    record Applicability(ComponentKind kind, boolean componentOwnsView) {
        public Applicability {
            if (kind == null || componentOwnsView != (kind == ComponentKind.SELF_CONFIGURING)) {
                throw new IllegalArgumentException("inconsistent configuration applicability");
            }
        }

        @Override public String toString() { return "ConfigurationRevisionService.Applicability[" + kind + "]"; }
    }

    /**
     * Sets only the supplied properties and preserves omitted values, including
     * passwords. Nulls, property deletion and factory creation are not implied.
     * On acceptance the ordinary ConfigurationService update and snapshot policy
     * applies. Return means configuration submission, not component health or
     * asynchronous application confirmation. Any non-Rejected failure may have
     * occurred after a write; callers must not automatically replay it.
     * The provider withholds further revisions for that PID after an uncertain
     * submission until an explicit successful legacy update/rollback or restart.
     * This in-memory guard is not durable business outcome reconciliation.
     */
    void updateRevision(String pid, String expectedRevision, Map<String, Object> properties) throws KuraException;
}
