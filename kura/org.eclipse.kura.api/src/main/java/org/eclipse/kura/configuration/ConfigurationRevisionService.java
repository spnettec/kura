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

    /**
     * Private DS descriptor property naming optional dynamic 0..n references that
     * only observe a service lifecycle and safely unbind when it is removed.
     * Values must be declared in the component description, never supplied by CM.
     * This does not exempt persisted PID/target dependencies, explicit runtime
     * target filters, required/static references, or undeclared business users.
     */
    String DELETION_OBSERVER_REFERENCES = ".kura.configuration.deletion.observers";


    /** A revision and configuration captured by the same provider read. */
    interface ReadView {
        ComponentConfiguration configuration();
        String revision();
    }

    record Read(ComponentConfiguration configuration, String revision) implements ReadView {
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
     * Provides the same paired read to callers whose compiler baseline predates
     * java.lang.Record (including the Java 11 GWT server build).
     * @since 1.5.0
     */
    default ReadView readRevisionView(String pid) throws KuraException {
        return readRevision(pid);
    }

    /**
     * Captures all requested paired views under the same provider update monitor.
     * No partial result is returned if any view is unavailable. This serializes
     * provider operations, not direct ConfigurationAdmin or component-owned writers.
     * Returned property containers are detached from the provider's mutable views.
     *
     * @since 1.5.0
     */
    default Map<String, ReadView> readRevisionViews(java.util.Set<String> pids) throws KuraException {
        throw new Rejected(Reason.UNSUPPORTED);
    }

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

    /**
     * Conditionally submits local configuration-editor updates using the ordinary
     * ConfigurationService validation and snapshot policy. Every displayed revision
     * is checked under the provider's update monitor before the first submission.
     * This does not grant remote write authorization or replace the constrained
     * property contract of {@link #updateRevision(String, String, Map)}.
     * A batch is not an atomic transaction across component callbacks. Any failure
     * after submission may have changed one or more components; do not replay it.
     * Implementations predating this operation reject it without a legacy fallback.
     *
     * @since 1.5.0
     */
    default void updateConfigurationsIfUnchanged(java.util.List<ComponentConfiguration> configurations,
            Map<String, String> expectedRevisions) throws KuraException {
        throw new Rejected(Reason.UNSUPPORTED);
    }

    /** A local factory creation in a conditional configuration plan. */
    final class Creation {
        private final String factoryPid;
        private final String pid;
        private final Map<String, Object> properties;

        public Creation(String factoryPid, String pid, Map<String, Object> properties) {
            this.factoryPid = factoryPid;
            this.pid = pid;
            this.properties = properties == null ? null : new java.util.HashMap<>(properties);
        }

        public String factoryPid() { return this.factoryPid; }
        public String pid() { return this.pid; }
        public Map<String, Object> properties() {
            return this.properties == null ? null : new java.util.HashMap<>(this.properties);
        }
        @Override public String toString() { return "ConfigurationRevisionService.Creation[redacted]"; }
    }

    /**
     * Applies a local editor's complete configuration plan. All supplied revisions
     * (including read-only guards) and new-PID absence conditions are checked before
     * any deletion, creation or update. Every existing mutation target must have a
     * revision; a creation must be absent, or replace a declared factory deletion.
     * Ordinary validation and snapshot policy apply. This does not authorize remote
     * lifecycle operations, lock direct ConfigurationAdmin writers, or provide
     * rollback atomicity. A non-Rejected failure can follow partial execution and
     * must never be replayed automatically. Implementations without plan support
     * reject before execution, without falling back to legacy lifecycle methods.
     *
     * @since 1.5.0
     */
    default void applyConfigurationPlanIfUnchanged(java.util.List<ComponentConfiguration> updates,
            java.util.List<Creation> creations, java.util.Set<String> deletions,
            Map<String, String> expectedRevisions) throws KuraException {
        throw new Rejected(Reason.UNSUPPORTED);
    }

    /**
     * One-shot, durably identified plan. The caller creates and retains a
     * canonical op-UUID before submitting. Every reuse of that ID is rejected,
     * including a reuse with identical arguments; query
     * ConfigurationOperationReceiptService instead of replaying a request.
     * Receipts contain mutation scope/identity but no configuration values,
     * passwords or property-value fingerprints. A recorded Core commit proves
     * writer/snapshot completion, not asynchronous provider/business success.
     * @since 1.8.0
     */
    default void applyConfigurationPlanIfUnchanged(String operationId,
            java.util.List<ComponentConfiguration> updates, java.util.List<Creation> creations,
            java.util.Set<String> deletions, Map<String,String> expectedRevisions) throws KuraException {
        throw new Rejected(Reason.UNSUPPORTED);
    }

    /**
     * Native ownership and dependency closure required before deleting a local stack.
     * Expected factory PIDs must cover exactly the deletion set. All persisted
     * *.target filters, the supplied exact-PID property names, and current SCR
     * bindings are checked under Core's ordinary write monitor. This does not lock
     * direct ConfigurationAdmin or independently mutating component/service writers.
     */
    final class DeletionGuard {
        private final Map<String, String> factoryPids;
        private final java.util.Set<String> pidReferenceProperties;

        public DeletionGuard(Map<String, String> factoryPids, java.util.Set<String> pidReferenceProperties) {
            this.factoryPids = factoryPids == null ? null : new java.util.HashMap<>(factoryPids);
            this.pidReferenceProperties = pidReferenceProperties == null ? null
                    : new java.util.HashSet<>(pidReferenceProperties);
        }
        public Map<String, String> factoryPids() {
            return this.factoryPids == null ? null : new java.util.HashMap<>(this.factoryPids);
        }
        public java.util.Set<String> pidReferenceProperties() {
            return this.pidReferenceProperties == null ? null : new java.util.HashSet<>(this.pidReferenceProperties);
        }
        @Override public String toString() { return "ConfigurationRevisionService.DeletionGuard[redacted]"; }
    }

    /**
     * Applies a plan only if its native deletion ownership/dependency closure also
     * holds before the first write. Implementations without this stronger contract
     * reject; delegating to the unguarded overload is forbidden. Any non-Rejected
     * failure may follow partial dispatch and must not be replayed automatically.
     */
    default void applyConfigurationPlanIfUnchanged(java.util.List<ComponentConfiguration> updates,
            java.util.List<Creation> creations, java.util.Set<String> deletions,
            Map<String, String> expectedRevisions, DeletionGuard deletionGuard) throws KuraException {
        throw new Rejected(Reason.UNSUPPORTED);
    }

    /** Identified plan with the same mandatory native deletion closure; no fallback. @since 1.8.0 */
    default void applyConfigurationPlanIfUnchanged(String operationId,
            java.util.List<ComponentConfiguration> updates, java.util.List<Creation> creations,
            java.util.Set<String> deletions, Map<String,String> expectedRevisions,
            DeletionGuard deletionGuard) throws KuraException {
        throw new Rejected(Reason.UNSUPPORTED);
    }

}
