/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.configuration;

import java.util.List;
import org.eclipse.kura.KuraException;

/** Optional read-only recovery evidence. Availability never grants completion or ordinary writes. */
public interface RecoveryVerificationService {
    record Context(String recoveryId, String snapshotSha256) { }
    record Challenge(String recoveryId, String snapshotSha256, String nonce,
            List<String> componentPids, List<String> checkIds, List<String> additionalSelfPids) {
        public Challenge {
            componentPids = List.copyOf(componentPids);
            checkIds = List.copyOf(checkIds);
            additionalSelfPids = List.copyOf(additionalSelfPids);
        }
    }
    record ComponentState(String pid, boolean registered) { }
    record CheckState(String id, boolean passed) { }
    record Report(int schema, String recoveryId, String snapshotSha256, String nonce,
            long processId, int frameworkStartLevel, boolean normalLoad, boolean ordinaryWritesBlocked,
            boolean cmMatched, int managedConfigurationCount, int propertyCount,
            boolean configurationServiceAvailable, List<ComponentState> components, List<CheckState> checks,
            int sourceConfigurationCount, List<String> materializedSelfPids) {
        public Report {
            components = List.copyOf(components);
            checks = List.copyOf(checks);
            materializedSelfPids = List.copyOf(materializedSelfPids);
        }
    }
    Report verify(Challenge challenge) throws KuraException;
}
