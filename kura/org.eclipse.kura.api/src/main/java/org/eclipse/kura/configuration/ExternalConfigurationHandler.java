/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.configuration;

import java.util.Map;

import org.eclipse.kura.KuraException;
import org.osgi.annotation.versioning.ConsumerType;

/**
 * Owns explicit configuration changes for a PID whose authoritative state is
 * maintained outside ConfigAdmin. Register this service in addition to the
 * component's {@link SelfConfiguringComponent} service.
 * The installation must reserve its PID in the comma-separated JVM property
 * {@code kura.configuration.external.pids} before ConfigurationService starts.
 * Reservations do not change during that service instance's lifetime.
 *
 * The ConfigurationService never sends these changes to ConfigAdmin and only
 * stores the handler's confirmed state in new snapshots. An accepted change may
 * still require a separate confirmation; callers must query the owner's
 * transaction service to determine its outcome. Startup snapshot loading and
 * ConfigAdmin callbacks must not be interpreted as explicit change requests.
 *
 * Implementations must not call ConfigurationService from these methods. They
 * must reject changes while unsynchronized, validate revisions and unsupported
 * fields, and coordinate all writes through their authoritative service.
 *
 * @since 1.3
 */
@ConsumerType
public interface ExternalConfigurationHandler {

    enum ChangeSource {
        CONFIGURATION_UPDATE,
        SNAPSHOT_ROLLBACK
    }

    /** @return the single, stable, non-factory PID owned by this service */
    String getPid();

    /**
     * Returns confirmed state, never an unconfirmed candidate or an old Kura
     * snapshot. Throws if authoritative state cannot be obtained.
     */
    ComponentConfiguration getConfirmedConfiguration() throws KuraException;

    /**
     * Validates the original request before any part of a batch is changed.
     * This method must have no side effects. Updates may contain partial fields;
     * snapshot rollback receives the historical target, not a current revision
     * token. The owner defines and documents its concurrency policy for each.
     */
    void validateConfiguration(Map<String, Object> properties, ChangeSource source) throws KuraException;

    /**
     * Accepts an explicit change. Updates contain confirmed fields merged with
     * the request; snapshot rollback contains the historical target. Validation
     * must be repeated as necessary to detect changes since preflight. Throws
     * when the change is rejected; an indeterminate outcome must remain
     * discoverable through the owner's transaction service.
     */
    void applyConfiguration(Map<String, Object> properties, ChangeSource source) throws KuraException;
}
