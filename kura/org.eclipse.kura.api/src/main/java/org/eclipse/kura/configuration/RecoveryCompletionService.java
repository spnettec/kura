/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.configuration;

import org.eclipse.kura.KuraException;

/** Optional administrator-authorized write release, distinct from read-only health evidence. */
public interface RecoveryCompletionService {
    record Bounds(int sourceCount, int managedCount, int propertyCount, java.util.List<String> materializedSelfPids) {
        public Bounds { materializedSelfPids = java.util.List.copyOf(materializedSelfPids); }
    }
    record Request(RecoveryVerificationService.Challenge challenge, String completionId,
            String decisionSha256, String healthReceiptSha256, String policySha256, long notAfterUnixMillis, Bounds bounds) { }
    record Report(int schema, String completionId, String recoveryId, String snapshotSha256,
            String decisionSha256, String receiptSha256, long processId, boolean writeReleaseCommitted,
            boolean kuraRecoveryVerified, RecoveryVerificationService.Report preReleaseHealth) { }
    Report complete(Request request) throws KuraException;
}
