/*******************************************************************************
 * Copyright (c) 2023, 2026 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 *******************************************************************************/
package org.eclipse.kura.endpoint;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.any;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.security.KeyPair;
import java.security.KeyStore.PrivateKeyEntry;
import java.security.PrivateKey;
import java.security.cert.Certificate;
import java.security.cert.X509Certificate;
import java.util.*;
import java.util.concurrent.*;
import org.bouncycastle.asn1.x500.X500Name;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.core.keystore.FilesystemKeystoreServiceImpl;
import org.eclipse.kura.core.testutil.TestUtil;
import org.eclipse.kura.core.testutil.pki.TestCA;
import org.eclipse.kura.core.testutil.pki.TestCA.CertificateCreationOptions;
import org.eclipse.kura.core.testutil.requesthandler.TransportType;
import org.eclipse.kura.core.testutil.requesthandler.Transport.MethodSpec;
import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.marshalling.Unmarshaller;
import org.eclipse.kura.internal.json.marshaller.unmarshaller.JsonMarshallUnmarshallImpl;
import org.eclipse.kura.internal.rest.keystore.provider.KeystoreRestServiceV2;
import org.eclipse.kura.internal.rest.keystore.request.handler.KeystoreServiceRequestHandlerV2;
import org.eclipse.kura.security.keystore.KeystoreService;
import org.eclipse.osgi.launch.EquinoxFactory;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.osgi.framework.*;
import org.osgi.framework.launch.Framework;
import org.osgi.service.component.ComponentContext;
import org.osgi.service.event.EventAdmin;
import com.eclipsesource.json.Json;
import com.eclipsesource.json.JsonArray;
import com.eclipsesource.json.JsonObject;

class KeystoreEndpointsV2IT extends EndpointTestBase {
    @TempDir Path directory;
    private Framework framework;
    private ServiceRegistration<Unmarshaller> codecRegistration;
    private BundleContext registry;
    private ComponentContext context;
    private KeystoreRestServiceV2 rest;
    private KeystoreServiceRequestHandlerV2 mqtt;
    private String privateKeyRespurceURI;
    private final Map<String, KeystoreService> createdKeystoreServices = new HashMap<>();
    private final List<ServiceRegistration<KeystoreService>> registrations = new ArrayList<>();
    private KeyPair leafKeyPair;
    private String leafKeyPem;
    private final List<String> certificateChainPem = new ArrayList<>();
    private PrivateKey leafKey;
    private final List<X509Certificate> certificateChain = new ArrayList<>();
    private TestCA testCA;

    @BeforeEach
    void registerEndpoints() throws Exception {
        this.createdKeystoreServices.clear();
        this.registrations.clear();
        this.certificateChain.clear();
        this.certificateChainPem.clear();
        this.rest = null;
        this.mqtt = null;
        this.framework = new EquinoxFactory().newFramework(Map.of(Constants.FRAMEWORK_STORAGE,
                this.directory.resolve("osgi").toString()));
        this.framework.start();
        this.registry = this.framework.getBundleContext();
        this.codecRegistration = this.registry.registerService(Unmarshaller.class, new JsonMarshallUnmarshallImpl(),
                new Hashtable<>(Map.of("kura.service.pid", "org.eclipse.kura.json.marshaller.unmarshaller.provider")));
        this.context = mock(ComponentContext.class);
        when(this.context.getBundleContext()).thenReturn(this.registry);
        this.rest = new KeystoreRestServiceV2();
        this.rest.activate(this.context);
        this.mqtt = new KeystoreServiceRequestHandlerV2();
        this.mqtt.activate(this.context);
        this.mqtt.setRequestHandlerRegistry(this.cloud);
        this.http.resource(this.rest);
    }

    private void useKeystoreTransport(TransportType type) {
        useTransport(type, "KEYS-V2", "keystores/v2");
        this.privateKeyRespurceURI = type == TransportType.REST
                ? "/entries/privatekey" : "/keystores/entries/privatekey";
    }

    private void givenKeystoreService(String pid) {
        assertDoesNotThrow(() -> {
            FilesystemKeystoreServiceImpl service = new FilesystemKeystoreServiceImpl();
            this.createdKeystoreServices.put(pid, service);
            CryptoService crypto = mock(CryptoService.class);
            when(crypto.decryptAes(any(char[].class))).thenAnswer(call -> call.getArgument(0));
            when(crypto.encryptAes(any(char[].class))).thenAnswer(call -> call.getArgument(0));
            service.setCryptoService(crypto);
            service.setEventAdmin(mock(EventAdmin.class));
            service.activate(this.context, Map.of("kura.service.pid", pid,
                    "keystore.path", this.directory.resolve(pid + ".p12").toString(),
                    "keystore.password", "test-password", "randomize.password", false,
                    "crl.management.enabled", false));
            this.registrations.add(this.registry.registerService(KeystoreService.class, service,
                    new Hashtable<>(Map.of("kura.service.pid", pid))));
        });
    }

    @AfterEach
    void unregisterEndpoints() throws Exception {
        try {
            try {
                if (this.rest != null) { this.rest.deactivate(this.context); }
            } finally {
                if (this.mqtt != null) {
                    this.mqtt.unsetRequestHandlerRegistry(this.cloud);
                    this.mqtt.deactivate(this.context);
                }
            }
            assertNull(this.codecRegistration.getReference().getUsingBundles(), "JSON service uses must be balanced");
            for (ServiceRegistration<KeystoreService> registration : this.registrations) {
                assertNull(registration.getReference().getUsingBundles(), "Endpoint trackers must release their service uses");
            }
        } finally {
            try {
                this.registrations.forEach(ServiceRegistration::unregister);
                if (this.codecRegistration != null) { this.codecRegistration.unregister(); }
                for (KeystoreService service : this.createdKeystoreServices.values()) {
                    ((FilesystemKeystoreServiceImpl) service).deactivate();
                    ExecutorService updater = (ExecutorService) TestUtil.getFieldValue(service, "selfUpdaterExecutor");
                    assertTrue(updater.awaitTermination(5, TimeUnit.SECONDS), "Password updater did not stop");
                }
            } finally {
                if (this.framework != null) {
                    this.framework.stop();
                    assertEquals(FrameworkEvent.STOPPED, this.framework.waitForStop(5000).getType());
                }
            }
        }
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldUploadSimplePrivateKeyEntry(TransportType type) {
        useKeystoreTransport(type);
        givenKeystoreService("bar");
        givenKeyPair("leaf");

        whenKeyPairIsUploaded("bar", "testalias", true);
        thenRequestSucceeds();
        thenKeystoreEntryEqualsCurrentKeyPair("bar", "testalias");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldUploadPrivateKeyEntryWithMultipleCertificatesInChain(TransportType type) {
        useKeystoreTransport(type);
        givenKeystoreService("foo");
        givenKeyPair("ca", "leaf");

        whenKeyPairIsUploaded("foo", "testalias", true);
        thenRequestSucceeds();
        thenKeystoreEntryEqualsCurrentKeyPair("foo", "testalias");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldUpdateSimplePrivateKeyEntry(TransportType type) {
        useKeystoreTransport(type);
        givenKeystoreService("bar");
        givenKeyPairInKeystore("bar", "testalias", "leaf");
        givenNewLeafCert("otherleaf");

        whenKeyPairIsUploaded("bar", "testalias", false);
        thenRequestSucceeds();
        thenKeystoreEntryEqualsCurrentKeyPair("bar", "testalias");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldUpdatePrivateKeyEntryWithMultipleCertificatesInChain(TransportType type) {
        useKeystoreTransport(type);
        givenKeystoreService("foo");
        givenKeyPairInKeystore("foo", "testalias", "ca", "leaf");
        givenNewLeafCert("otherleaf");

        whenKeyPairIsUploaded("foo", "testalias", false);
        thenRequestSucceeds();
        thenKeystoreEntryEqualsCurrentKeyPair("foo", "testalias");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRejectEmptyRequestObject(TransportType type) {
        useKeystoreTransport(type);

        whenRequestIsPerformed(new MethodSpec("POST"), privateKeyRespurceURI, "{}");
        thenResponseCodeIs(400);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRejectRequestObjectWithoutPid(TransportType type) {
        useKeystoreTransport(type);

        whenRequestIsPerformed(new MethodSpec("POST"), privateKeyRespurceURI,
                "{\"alias\":\"foo\",\"privateKey\":\"bar\",\"certificateChain\":[\"foo\"]}");
        thenResponseCodeIs(400);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRejectRequestObjectWithoutAlias(TransportType type) {
        useKeystoreTransport(type);

        whenRequestIsPerformed(new MethodSpec("POST"), privateKeyRespurceURI,
                "{\"keystoreServicePid\":\"foo\",\"privateKey\":\"bar\",\"certificateChain\":[\"foo\"]}");
        thenResponseCodeIs(400);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRejectRequestObjectWithoutCertificateChain(TransportType type) {
        useKeystoreTransport(type);

        whenRequestIsPerformed(new MethodSpec("POST"), privateKeyRespurceURI,
                "{\"keystoreServicePid\":\"foo\",\"alias\":\"bar\",\"privateKey\":\"bar\"}");
        thenResponseCodeIs(400);
    }

    private void givenKeyPair(final String leafCN) {
        givenKeyPair("foo", leafCN, false);
    }

    private void givenKeyPairInKeystore(final String keystorePid, final String alias, final String leafCN) {
        givenKeyPair(leafCN);

        storeCurrentKeyPair(keystorePid, alias);
    }

    private void givenKeyPair(final String caCN, final String leafCN) {
        givenKeyPair(caCN, leafCN, true);
    }

    private void givenKeyPairInKeystore(final String keystorePid, final String alias, final String caCN,
            final String leafCN) {
        givenKeyPair(caCN, leafCN);

        storeCurrentKeyPair(keystorePid, alias);
    }

    private void givenKeyPair(final String caCN, final String leafCN, final boolean includeCA) {
        try {
            this.testCA = new TestCA(
                    CertificateCreationOptions.builder(new X500Name("cn=" + caCN + ", dc=bar.com")).build());

            this.leafKeyPair = TestCA.generateKeyPair();

            this.leafKey = this.leafKeyPair.getPrivate();
            this.leafKeyPem = privateKeyToPEMString(this.leafKeyPair.getPrivate());

            final X509Certificate leafCert = testCA.createAndSignCertificate(
                    CertificateCreationOptions.builder(new X500Name("cn=" + leafCN + ", dc=bar.com")).build(),
                    this.leafKeyPair);

            this.certificateChain.clear();
            this.certificateChainPem.clear();
            this.certificateChain.add(leafCert);
            this.certificateChainPem.add(certificateToPEMString(leafCert));

            if (includeCA) {
                this.certificateChain.add(testCA.getCertificate());
                this.certificateChainPem.add(certificateToPEMString(testCA.getCertificate()));
            }

        } catch (Exception e) {
            fail("cannot create test certificate chain", e);
        }
    }

    private void givenNewLeafCert(final String leafCN) {
        try {
            final X509Certificate leafCert = this.testCA.createAndSignCertificate(
                    CertificateCreationOptions.builder(new X500Name("cn=" + leafCN + ", dc=bar.com")).build(),
                    this.leafKeyPair);

            this.certificateChain.set(0, leafCert);
            this.certificateChainPem.set(0, certificateToPEMString(leafCert));
        } catch (Exception e) {
            fail("cannot create new certificate", e);
        }
    }

    private void storeCurrentKeyPair(final String keystorePid, final String alias) {
        try {
            this.createdKeystoreServices.get(keystorePid).setEntry(alias,
                    new PrivateKeyEntry(this.leafKey, this.certificateChain.toArray(new X509Certificate[0])));
        } catch (final Exception e) {
            fail("cannot store certificate chain", e);
        }
    }

    private void whenKeyPairIsUploaded(final String keystorePid, final String alias,
            final boolean includePrivateKey) {
        final JsonObject object = Json.object();
        if (includePrivateKey) {
            object.add("privateKey", this.leafKeyPem);
        }

        final JsonArray chain = Json.array();
        for (final String cert : certificateChainPem) {
            chain.add(cert);
        }

        object.add("certificateChain", chain);
        object.add("keystoreServicePid", keystorePid);
        object.add("alias", alias);

        whenRequestIsPerformed(new MethodSpec("POST"), privateKeyRespurceURI,
                object.toString());
    }

    private void thenKeystoreEntryEqualsCurrentKeyPair(final String pid, final String alias) {
        try {
            final PrivateKeyEntry privateKeyEntry = (PrivateKeyEntry) this.createdKeystoreServices.get(pid)
                    .getEntry(alias);

            assertEquals(this.leafKeyPem, privateKeyToPEMString(privateKeyEntry.getPrivateKey()));

            final List<String> entryCertificatesAsPem = new ArrayList<>();

            for (final Certificate cert : privateKeyEntry.getCertificateChain()) {
                entryCertificatesAsPem.add(certificateToPEMString((X509Certificate) cert));
            }

            assertEquals(this.certificateChainPem, entryCertificatesAsPem);
        } catch (KuraException | IOException e) {
            fail("Unable to retrieve keystore entry", e);
        }
    }

    private String certificateToPEMString(final X509Certificate cert) throws IOException {
        try (final ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            TestCA.encodeToPEM(cert, out);
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private String privateKeyToPEMString(final PrivateKey key) throws IOException {
        try (final ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            TestCA.encodeToPEM(key, out);
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }
}
