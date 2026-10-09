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
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPair;
import java.security.KeyStore;
import java.security.KeyStore.PrivateKeyEntry;
import java.security.KeyStore.TrustedCertificateEntry;
import java.security.KeyStoreException;
import java.security.cert.Certificate;
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
import org.junit.jupiter.api.io.TempDir;
import org.mockito.ArgumentCaptor;
import org.osgi.framework.BundleContext;
import org.osgi.service.component.ComponentContext;

class SslManagerServiceImplTest {

    private static final Map<String, Object> SERVICE_PROPERTIES = Collections.singletonMap("kura.service.pid", "foo");
    private static final char[] STORE_PASSWORD = "test-password".toCharArray();

    @TempDir
    Path temporaryDirectory;

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
    void explicitKeystoreStillLoadsTheSuppliedFile() throws Exception {
        KeyPair pair = TestCA.generateKeyPair();
        X509Certificate certificate = new TestCA(
                CertificateCreationOptions.builder(new X500Name("CN=kura")).build(), pair).getCertificate();
        this.store.setKeyEntry("client", pair.getPrivate(), STORE_PASSWORD, new Certificate[] { certificate });
        Path path = this.temporaryDirectory.resolve("client.p12");
        try (OutputStream output = Files.newOutputStream(path)) {
            this.store.store(output, STORE_PASSWORD);
        }
        clearInvocations(this.keystoreService);
        assertNotNull(this.service.getSSLSocketFactory("TLS", null, path.toString(), path.toString(),
                STORE_PASSWORD, "client"));
        verifyNoInteractions(this.keystoreService);
    }

    @Test
    void boundKeystoreFailureRetainsItsCauseForNamedAlias() throws Exception {
        KuraException failure = new KuraException(KuraErrorCode.INTERNAL_ERROR);
        when(this.keystoreService.getKeyStore()).thenThrow(failure);
        KeyStoreException thrown = assertThrows(KeyStoreException.class, () -> this.service.getSSLContext("client"));
        assertSame(failure, thrown.getCause());
    }

    @Test
    void testPrivateKey() throws Exception {
        KeyPair pair = TestCA.generateKeyPair();
        X509Certificate certificate = new TestCA(
                CertificateCreationOptions.builder(new X500Name("CN=kura-client")).build(), pair).getCertificate();
        Certificate[] chain = { certificate };
        this.service.installPrivateKey("client", pair.getPrivate(), STORE_PASSWORD, chain);
        ArgumentCaptor<PrivateKeyEntry> entry = ArgumentCaptor.forClass(PrivateKeyEntry.class);
        verify(this.keystoreService).setEntry(eq("client"), entry.capture());
        assertSame(pair.getPrivate(), entry.getValue().getPrivateKey());
        assertArrayEquals(chain, entry.getValue().getCertificateChain());
    }

    @Test
    void testCertificates() throws Exception {
        X509Certificate certificate = new TestCA(
                CertificateCreationOptions.builder(new X500Name("CN=kura-trust")).build()).getCertificate();
        doAnswer(invocation -> {
            TrustedCertificateEntry entry = invocation.getArgument(1);
            this.store.setCertificateEntry(invocation.getArgument(0), entry.getTrustedCertificate());
            return null;
        }).when(this.keystoreService).setEntry(anyString(), any(TrustedCertificateEntry.class));
        doAnswer(invocation -> {
            this.store.deleteEntry(invocation.getArgument(0));
            return null;
        }).when(this.keystoreService).deleteEntry(anyString());

        assertEquals(0, this.service.getTrustCertificates().length);
        this.service.installTrustCertificate("trusted", certificate);
        assertArrayEquals(new X509Certificate[] { certificate }, this.service.getTrustCertificates());
        verify(this.keystoreService).setEntry(eq("trusted"), any(TrustedCertificateEntry.class));
        this.service.deleteTrustCertificate("trusted");
        verify(this.keystoreService).deleteEntry("trusted");
        assertEquals(0, this.service.getTrustCertificates().length);
    }

    @Test
    void certificateInstallationPropagatesKeystoreFailure() throws Exception {
        X509Certificate certificate = new TestCA(
                CertificateCreationOptions.builder(new X500Name("CN=kura-trust")).build()).getCertificate();
        KuraException failure = new KuraException(KuraErrorCode.INTERNAL_ERROR);
        doThrow(failure).when(this.keystoreService).setEntry(anyString(), any(TrustedCertificateEntry.class));
        IOException thrown = assertThrows(IOException.class,
                () -> this.service.installTrustCertificate("trusted", certificate));
        assertSame(failure, thrown.getCause());
    }
}
