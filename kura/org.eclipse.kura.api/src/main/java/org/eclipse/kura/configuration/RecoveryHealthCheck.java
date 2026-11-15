/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.configuration;

/** Deployment-specific, bounded read-only business check; no management action or gate release. */
public interface RecoveryHealthCheck {
    String ID_PROPERTY = "kura.recovery.health.id";
    boolean verify(RecoveryVerificationService.Context context) throws Exception;
}
