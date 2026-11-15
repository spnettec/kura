/* Copyright (c) 2026 YOFC. SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.management;

import java.util.Map;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.KuraErrorCode;
import org.osgi.annotation.versioning.ProviderType;

/** Optional local-agent management. Consumers must not wait for this service at startup.
 * Public status contains only scalar strings: enabled, bound, canControl, recoveryRequired,
 * revision, connectionState, activeRequests, and optional endpoint/gatewayId/bindingGeneration.
 * No key, token, file path or arbitrary agent method is exposed. @since 1.0.0
 */
@ProviderType
public interface RemoteManagementService {
    Map<String, String> getStatus() throws KuraException;
    /** One request, never automatically retried. UNKNOWN does not mean cancellation;
     * explicitly read status before allowing another confirmed switch. */
    Map<String, String> setEnabled(String expectedRevision, boolean enabled) throws KuraException;

    /** Optional, public receipt/status only. Older providers remain compatible. */
    default Map<String,String> getEnrollmentStatus() throws KuraException {
        throw new Failure(Reason.UNSUPPORTED);
    }
    /** First enrollment only; never replaces an existing binding. No paths or key bytes.
     * operator comes from the authenticated local application, not a browser field.
     * UNKNOWN requires explicit receipt/status reconciliation; never retry automatically. */
    default Map<String,String> bindIdentity(String expectedRevision,String requestId,
            String expectedStageSha256,String operator) throws KuraException {
        throw new Failure(Reason.UNSUPPORTED);
    }

    enum Reason { INVALID_ARGUMENT, FORBIDDEN, CONFLICT, UNAVAILABLE, UNSUPPORTED, PROTOCOL_MISMATCH, UNKNOWN }
    final class Failure extends KuraException {
        private static final long serialVersionUID = 1L;
        private final Reason reason;
        public Failure(Reason reason) { super(KuraErrorCode.CONFIGURATION_ERROR, reason.name()); this.reason = reason; }
        public Reason getReason() { return this.reason; }
    }
}
