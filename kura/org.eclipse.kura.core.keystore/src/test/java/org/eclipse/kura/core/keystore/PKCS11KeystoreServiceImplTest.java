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
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.core.keystore.crl.CRLManagerOptions;
import org.eclipse.kura.crypto.CryptoService;
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

    @Test
    void blocksARejectedPinUntilAuthenticationChanges() throws Exception {
        RecordingService service = mockProvider(PKCS11PinCheck.Result.REJECTED);

        assertCode(KuraErrorCode.SECURITY_EXCEPTION, service);
        service.updated(properties("original", "/user-config/new.crl"));
        assertCode(KuraErrorCode.SECURITY_EXCEPTION, service);
        assertEquals(1, service.pinChecks);

        service.updated(properties("replacement", "/user-config/new.crl"));
        assertCode(KuraErrorCode.SECURITY_EXCEPTION, service);
        assertEquals(2, service.pinChecks);
    }

    @Test
    void blocksAnInterruptedPinCheckWithoutSendingAnotherOne() throws Exception {
        RecordingService service = mockProvider(PKCS11PinCheck.Result.UNCERTAIN);

        assertCode(KuraErrorCode.SECURITY_EXCEPTION, service);
        assertCode(KuraErrorCode.SECURITY_EXCEPTION, service);
        assertEquals(1, service.pinChecks);
    }

    @Test
    void canTryAgainAfterAnUnavailableVerifierBeforeLogin() throws Exception {
        RecordingService service = mockProvider(PKCS11PinCheck.Result.UNAVAILABLE);

        assertCode(KuraErrorCode.SERVICE_UNAVAILABLE, service);
        assertCode(KuraErrorCode.SERVICE_UNAVAILABLE, service);
        assertEquals(2, service.pinChecks);
    }

    @Test
    void classifiesFailureBeforeAnyLoginInTheActualWorker() {
        assertEquals(PKCS11PinCheck.Result.UNAVAILABLE,
                PKCS11PinCheck.verify("name = TestWorker\nlibrary = /nonexistent/pkcs11-module.so\n",
                        new char[] {'1', '2', '3', '4'}));
    }

    private static void assertCode(KuraErrorCode code, RecordingService service) {
        assertEquals(code, assertThrows(KuraException.class, service::getKeyStore).getCode());
    }

    private static RecordingService mockProvider(PKCS11PinCheck.Result outcome) throws KuraException {
        RecordingService service = new RecordingService();
        CryptoService crypto = mock(CryptoService.class);
        when(crypto.decryptAes(any(char[].class))).thenAnswer(invocation -> invocation.getArgument(0));
        service.setCryptoService(crypto);
        service.setEventAdmin(mock(EventAdmin.class));
        service.pinCheckResult = outcome;
        service.activate(null, properties("original", "/user-config/test.crl"));
        return service;
    }

    private static Map<String, Object> properties(String pin, String crlPath) {
        return Map.of("kura.service.pid", "TestToken", "slot", 1, "pin", pin, "library.path", "/test/pkcs11.so",
                "crl.management.enabled", true, "crl.store.path", crlPath);
    }

    private static class RecordingService extends PKCS11KeystoreServiceImpl {

        private final List<String> crlPaths = new ArrayList<>();
        private int pinChecks;
        private PKCS11PinCheck.Result pinCheckResult;

        @Override
        PKCS11PinCheck.Result checkPin(String config, char[] pin) {
            this.pinChecks++;
            return this.pinCheckResult;
        }

        @Override
        protected void updateCRLManager(CRLManagerOptions options) {
            this.crlPaths.add(getCrlStorePath());
        }
    }
}
