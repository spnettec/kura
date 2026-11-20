/*******************************************************************************
 * Copyright (c) 2026 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.core.keystore;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import org.eclipse.kura.core.keystore.crl.CRLManagerOptions;
import org.eclipse.kura.system.SystemService;
import org.junit.jupiter.api.Test;
import org.osgi.service.event.EventAdmin;

class PKCS11KeystoreServiceImplTest {

    @Test
    void resolvesTheDefaultCrlPathDuringActivation() {
        RecordingService service = new RecordingService();
        SystemService systemService = mock(SystemService.class);
        when(systemService.getKuraUserConfigDirectory()).thenReturn("/user-config");
        service.setSystemService(systemService);

        service.activate(null, Map.of("kura.service.pid", "TestToken", "crl.management.enabled", true));

        assertEquals(List.of("/user-config/security/pkcs11.TestToken.crl"), service.crlPaths);
    }

    @Test
    void reloadsCrlStateOnceWhenTheProviderSlotChanges() {
        RecordingService service = new RecordingService();
        EventAdmin eventAdmin = mock(EventAdmin.class);
        service.setEventAdmin(eventAdmin);
        var properties = Map.<String, Object>of("kura.service.pid", "TestToken", "slot", 1,
                "crl.management.enabled", true, "crl.store.path", "/user-config/custom.crl");

        service.activate(null, properties);
        service.updated(properties);
        service.updated(Map.of("kura.service.pid", "TestToken", "slot", 2,
                "crl.management.enabled", true, "crl.store.path", "/user-config/custom.crl"));

        assertEquals(List.of("/user-config/custom.crl", "/user-config/custom.crl"), service.crlPaths);
        verify(eventAdmin).postEvent(any());
    }

    private static class RecordingService extends PKCS11KeystoreServiceImpl {

        private final List<String> crlPaths = new ArrayList<>();

        @Override
        protected void updateCRLManager(CRLManagerOptions options) {
            this.crlPaths.add(getCrlStorePath());
        }
    }
}
