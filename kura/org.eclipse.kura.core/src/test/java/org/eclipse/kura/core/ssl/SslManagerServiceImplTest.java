/*******************************************************************************
 * Copyright (c) 2017, 2026 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 ******************************************************************************/
package org.eclipse.kura.core.ssl;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.io.IOException;
import java.security.KeyStore;
import java.security.KeyStoreException;
import java.security.cert.X509Certificate;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;

import org.bouncycastle.asn1.x500.X500Name;
import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.core.testutil.TestUtil;
import org.eclipse.kura.core.testutil.pki.TestCA;
import org.eclipse.kura.core.testutil.pki.TestCA.CertificateCreationOptions;
import org.eclipse.kura.security.keystore.KeystoreChangedEvent;
import org.eclipse.kura.security.keystore.KeystoreService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.osgi.framework.BundleContext;
import org.osgi.service.component.ComponentContext;

class SslManagerServiceImplTest {

    private static final Map<String, Object> SERVICE_PROPERTIES = Collections.singletonMap("kura.service.pid", "foo");

    private KeyStore store;
    private KeystoreService keystoreService;
    private SslManagerServiceImpl service;
    private Map<String, Object> properties;

    @BeforeEach
    void setupDefaultKeystore() throws Exception {
        this.store = KeyStore.getInstance(KeyStore.getDefaultType());
        this.store.load(null, null);
        this.keystoreService = mock(KeystoreService.class);
        when(this.keystoreService.getKeyStore()).thenReturn(this.store);
        when(this.keystoreService.getKeyManagers(anyString())).thenReturn(Collections.emptyList());

        ComponentContext context = mock(ComponentContext.class);
        when(context.getBundleContext()).thenReturn(mock(BundleContext.class));
        this.properties = new HashMap<>();
        this.properties.put("ssl.default.protocol", "TLS");
        this.properties.put("ssl.hostname.verification", "true");
        this.service = new SslManagerServiceImpl();
        this.service.activate(context, this.properties);
        TestUtil.setFieldValue(this.service, "sslServiceListeners", mock(SslServiceListeners.class));
        this.service.setKeystoreService(this.keystoreService, SERVICE_PROPERTIES);
    }

    @SuppressWarnings("unchecked")
    private Map<ConnectionSslOptions, SSLContext> cachedContexts() throws NoSuchFieldException {
        return (Map<ConnectionSslOptions, SSLContext>) TestUtil.getFieldValue(this.service, "sslContexts");
    }

    private void populateCache() throws Exception {
        SSLSocketFactory factory = this.service.getSSLSocketFactory();
        assertNotNull(factory);
        assertEquals(1, cachedContexts().size());
        assertSame(factory, cachedContexts().values().iterator().next().getSocketFactory());
        assertSame(factory, this.service.getSSLSocketFactory());
    }

    @Test
    void testGetSSLSocketFactory() throws Exception {
        populateCache();
        this.service.updated(this.properties);
        assertTrue(cachedContexts().isEmpty());
    }

    @Test
    void testSSLSocketFactoryCacheCleanedAfterSet() throws Exception {
        populateCache();
        this.service.setKeystoreService(this.keystoreService, SERVICE_PROPERTIES);
        assertTrue(cachedContexts().isEmpty());
    }

    @Test
    void testSSLSocketFactoryCacheCleanedAfterUnset() throws Exception {
        populateCache();
        this.service.unsetKeystoreService(this.keystoreService);
        assertTrue(cachedContexts().isEmpty());
    }

    @Test
    void testSSLSocketFactoryCacheCleanedAfterEvent() throws Exception {
        populateCache();
        this.service.handleEvent(new KeystoreChangedEvent("foo"));
        assertTrue(cachedContexts().isEmpty());
    }

    @Test
    void emptyServiceKeystoreFallsBackToCachedDefaultWhenAliasIsRequested() throws Exception {
        SSLContext defaultContext = this.service.getSSLContext();
        assertSame(defaultContext, this.service.getSSLContext("missing-key"));
        assertEquals(1, cachedContexts().size());
    }

    @Test
    void namedAliasUsesBoundKeystoreWithoutAFilePath() throws Exception {
        X509Certificate certificate = new TestCA(CertificateCreationOptions.builder(new X500Name("CN=kura")).build())
                .getCertificate();
        this.store.setCertificateEntry("trusted", certificate);
        assertNotNull(this.service.getSSLContext("trusted"));
        verify(this.keystoreService, atLeastOnce()).getKeyStore();
        verify(this.keystoreService).getKeyManagers(anyString());
    }

    @Test
    void boundKeystoreFailureRetainsItsCauseForNamedAlias() throws Exception {
        KuraException failure = new KuraException(KuraErrorCode.INTERNAL_ERROR);
        when(this.keystoreService.getKeyStore()).thenThrow(failure);
        KeyStoreException thrown = assertThrows(KeyStoreException.class, () -> this.service.getSSLContext("client"));
        assertSame(failure, thrown.getCause());
    }

    @Test
    void truststoreFailureRetainsItsCause() throws Exception {
        KuraException failure = new KuraException(KuraErrorCode.INTERNAL_ERROR);
        when(this.keystoreService.getKeyStore()).thenThrow(failure);
        IOException thrown = assertThrows(IOException.class, () -> this.service.getSSLContext());
        assertSame(failure, thrown.getCause());
    }

    @Test
    void keyManagerFailureRetainsItsCause() throws Exception {
        KuraException failure = new KuraException(KuraErrorCode.INTERNAL_ERROR);
        when(this.keystoreService.getKeyManagers(anyString())).thenThrow(failure);
        IOException thrown = assertThrows(IOException.class, () -> this.service.getSSLContext());
        assertSame(failure, thrown.getCause());
    }
}
