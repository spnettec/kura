/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ConfigurationOperationReceiptService;
import org.eclipse.kura.system.SystemService;

import java.nio.file.Path;

/** No ConfigurationService, CM, Crypto, agent, snapshot or business-service dependency. */
public final class ConfigurationOperationReceiptServiceImpl
        implements ConfigurationOperationReceiptService {
    private SystemService systemService;

    public void setSystemService(SystemService systemService) {
        this.systemService = systemService;
    }

    private Path directory() throws KuraException {
        try {
            String data = this.systemService.getKuraDataDirectory();
            if (data == null) throw new IllegalArgumentException();
            return Path.of(data).resolve("configuration-dispatch-journal-v1");
        } catch (RuntimeException unavailable) {
            throw new KuraException(
                    KuraErrorCode.CONFIGURATION_ERROR,
                    "Configuration operation receipts unavailable");
        }
    }

    @Override
    public Receipt getOperationReceipt(String operationId) throws KuraException {
        return ConfigurationOperationStore.read(directory(), operationId);
    }

    @Override
    public Receipt cancelUnreservedOperation(String operationId) throws KuraException {
        return ConfigurationOperationStore.cancel(directory(), operationId);
    }
}
