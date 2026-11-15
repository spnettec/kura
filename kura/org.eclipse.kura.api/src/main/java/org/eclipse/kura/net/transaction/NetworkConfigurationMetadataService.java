/* Copyright (c) 2026 YOFC. SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.net.transaction;

import java.util.Map;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.osgi.annotation.versioning.ProviderType;

/** Read-only definitions for a complete confirmed NM configuration. No CM,
 * backend, agent or configuration-update calls are made by this builder.
 * @since 1.1
 */
@ProviderType
public interface NetworkConfigurationMetadataService {
    ComponentConfiguration describeConfirmedConfiguration(Map<String,Object> properties) throws KuraException;
}
