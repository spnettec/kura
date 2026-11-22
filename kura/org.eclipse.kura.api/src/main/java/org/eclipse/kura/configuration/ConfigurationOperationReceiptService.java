/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.configuration;

import org.eclipse.kura.KuraException;
import org.osgi.annotation.versioning.ProviderType;

import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * Durable, value-free receipts for explicitly identified configuration plans. This service is
 * independent of ConfigurationService activation and never loads snapshots, obtains business
 * services or retries a configuration write. It does not supply remote authorization; callers must
 * enforce their own ACL.
 *
 * @since 1.8.0
 */
@ProviderType
public interface ConfigurationOperationReceiptService {
    enum State {
        /** No durable reservation is visible. This never authorizes a retry. */
        NOT_FOUND,
        /** Reserved; preflight may be running or interrupted. Do not resend. */
        RESERVED,
        /** An explicit pre-dispatch rejection was recorded. */
        REJECTED,
        /** The Core writer and its snapshot completed, not business health. */
        CORE_COMMITTED,
        /** A dispatch may have occurred, or receipt evidence is incomplete. */
        UNKNOWN,
        /** A later explicit recovery released the intent; original result is unknown. */
        RECOVERED,
        /** A not-yet-reserved ID was sealed against any later submission. */
        CANCELLED
    }

    /** Java 11 callers can use this DTO without depending on java.lang.Record. */
    final class Receipt {
        private final String operationId;
        private final State state;
        private final Map<String, String> createdFactories;
        private final Set<String> updatedPids;
        private final Set<String> deletedPids;
        private final Set<String> scope;
        private final String rejection;

        public Receipt(
                String operationId,
                State state,
                Map<String, String> createdFactories,
                Set<String> updatedPids,
                Set<String> deletedPids,
                Set<String> scope,
                String rejection) {
            this.operationId = Objects.requireNonNull(operationId);
            this.state = Objects.requireNonNull(state);
            this.createdFactories = Collections.unmodifiableMap(new HashMap<>(createdFactories));
            this.updatedPids = Collections.unmodifiableSet(new HashSet<>(updatedPids));
            this.deletedPids = Collections.unmodifiableSet(new HashSet<>(deletedPids));
            this.scope = Collections.unmodifiableSet(new HashSet<>(scope));
            this.rejection = rejection;
        }

        public String operationId() {
            return this.operationId;
        }

        public State state() {
            return this.state;
        }

        public Map<String, String> createdFactories() {
            return this.createdFactories;
        }

        public Set<String> updatedPids() {
            return this.updatedPids;
        }

        public Set<String> deletedPids() {
            return this.deletedPids;
        }

        public Set<String> scope() {
            return this.scope;
        }

        public String rejection() {
            return this.rejection;
        }

        public boolean businessHealthVerified() {
            return false;
        }

        @Override
        public String toString() {
            return "ConfigurationOperationReceipt[" + this.state + "]";
        }
    }

    /**
     * Reads the original op-UUID receipt. Even NOT_FOUND/RESERVED/UNKNOWN must never cause
     * automatic resubmission. CORE_COMMITTED is not provider health.
     */
    Receipt getOperationReceipt(String operationId) throws KuraException;

    /**
     * Reserves an entirely unrecorded ID as CANCELLED, without a CM mutation. This only prevents a
     * late submission; it cannot cancel a reserved, dispatched or unknown operation. A racing
     * reservation wins or loses atomically. A new business action still requires a new explicit
     * request and a fresh configuration view, never replay of a stored payload.
     */
    Receipt cancelUnreservedOperation(String operationId) throws KuraException;
}
