/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.ssl;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.KeyPair;
import java.security.KeyStore;
import java.security.cert.Certificate;
import java.security.cert.X509Certificate;
import java.time.Duration;
import java.util.Arrays;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

import javax.net.ssl.KeyManagerFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLParameters;
import javax.net.ssl.SSLServerSocket;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.TrustManagerFactory;

import com.sun.net.httpserver.HttpsConfigurator;
import com.sun.net.httpserver.HttpsParameters;
import com.sun.net.httpserver.HttpsServer;

import org.bouncycastle.asn1.x500.X500Name;
import org.eclipse.kura.core.testutil.TestUtil;
import org.eclipse.kura.core.testutil.pki.TestCA;
import org.eclipse.kura.core.testutil.pki.TestCA.CertificateCreationOptions;
import org.eclipse.kura.security.keystore.KeystoreService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.osgi.framework.BundleContext;
import org.osgi.service.component.ComponentContext;

/** Local, ephemeral credentials and real JSSE handshakes; no deployment or external CA. */
@Timeout(30)
class ManagedCredentialTlsTest {
    private static final char[] PASSWORD = "ephemeral-test-password".toCharArray();

    @ParameterizedTest
    @CsvSource({ "client-b,TLSv1.2", "client-b,TLSv1.3", "CLIENT-B,TLSv1.2", "CLIENT-B,TLSv1.3" })
    void socketClientUsesOnlyRequestedManagedCredential(String alias, String protocol) throws Exception {
        Fixture fixture = new Fixture();
        SSLContext client = fixture.managed(fixture.clients, alias, protocol);
        try (SSLServerSocket server = fixture.socketServer()) {
            CompletableFuture<X509Certificate> peer = fixture.accept(server, false);
            try (SSLSocket socket = (SSLSocket) client.getSocketFactory().createSocket("localhost", server.getLocalPort())) {
                socket.setSoTimeout(10000);
                socket.startHandshake();
                socket.getOutputStream().write(1);
                assertEquals(fixture.clientB, peer.get(10, TimeUnit.SECONDS));
                assertEquals(fixture.serverA, socket.getSession().getPeerCertificates()[0]);
            }
        }
    }

    @ParameterizedTest
    @CsvSource({ "client-b,TLSv1.2", "client-b,TLSv1.3", "CLIENT-B,TLSv1.2", "CLIENT-B,TLSv1.3" })
    void engineClientUsesOnlyRequestedManagedCredential(String alias, String protocol) throws Exception {
        Fixture fixture = new Fixture();
        SSLContext clientContext = fixture.managed(fixture.clients, alias, protocol);
        try (SSLServerSocket server = fixture.socketServer();
                HttpClient client = HttpClient.newBuilder().sslContext(clientContext)
                        .connectTimeout(Duration.ofSeconds(10)).version(HttpClient.Version.HTTP_1_1).build()) {
            CompletableFuture<X509Certificate> peer = fixture.accept(server, true);
            HttpRequest request = HttpRequest.newBuilder(URI.create("https://localhost:" + server.getLocalPort() + "/"))
                    .timeout(Duration.ofSeconds(10)).build();
            assertEquals(200, client.send(request, HttpResponse.BodyHandlers.discarding()).statusCode());
            assertEquals(fixture.clientB, peer.get(10, TimeUnit.SECONDS));
        }
    }

    @ParameterizedTest
    @CsvSource({ "server-b,TLSv1.2", "server-b,TLSv1.3", "SERVER-B,TLSv1.2", "SERVER-B,TLSv1.3" })
    void engineServerUsesOnlyRequestedManagedCredential(String alias, String protocol) throws Exception {
        Fixture fixture = new Fixture();
        SSLContext serverContext = fixture.managed(fixture.servers, alias, protocol);
        HttpsServer server = HttpsServer.create(new InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0);
        CompletableFuture<X509Certificate> peer = new CompletableFuture<>();
        server.setHttpsConfigurator(new HttpsConfigurator(serverContext) {
            @Override
            public void configure(HttpsParameters parameters) {
                SSLParameters ssl = serverContext.getDefaultSSLParameters();
                // The outbound hostname policy does not identify an inbound client by its DNS name.
                ssl.setEndpointIdentificationAlgorithm(null);
                ssl.setNeedClientAuth(true);
                parameters.setSSLParameters(ssl);
            }
        });
        server.createContext("/", exchange -> {
            try {
                peer.complete((X509Certificate) ((com.sun.net.httpserver.HttpsExchange) exchange)
                        .getSSLSession().getPeerCertificates()[0]);
                exchange.sendResponseHeaders(200, -1);
            } catch (Throwable failure) {
                peer.completeExceptionally(failure);
            } finally {
                exchange.close();
            }
        });
        server.start();
        try (SSLSocket socket = (SSLSocket) fixture.plain(fixture.clients).getSocketFactory()
                .createSocket("localhost", server.getAddress().getPort())) {
            socket.setSoTimeout(10000);
            socket.startHandshake();
            assertEquals(fixture.serverB, socket.getSession().getPeerCertificates()[0]);
            socket.getOutputStream().write("GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
                    .getBytes(StandardCharsets.US_ASCII));
            assertTrue(new BufferedReader(new InputStreamReader(socket.getInputStream(), StandardCharsets.US_ASCII))
                    .readLine().contains("200"));
            assertNotNull(peer.get(10, TimeUnit.SECONDS));
        } finally {
            server.stop(0);
        }
    }

    @Test
    void missingManagedAliasCannotFallBackToAnotherClientCredential() throws Exception {
        Fixture fixture = new Fixture();
        SSLContext client = fixture.managed(fixture.clients, "missing-client", "TLSv1.2");
        try (SSLServerSocket server = fixture.socketServer()) {
            CompletableFuture<X509Certificate> peer = fixture.accept(server, false);
            try (SSLSocket socket = (SSLSocket) client.getSocketFactory().createSocket("localhost", server.getLocalPort())) {
                socket.setSoTimeout(10000);
                assertThrows(java.io.IOException.class, socket::startHandshake);
                var rejection = assertThrows(java.util.concurrent.ExecutionException.class,
                        () -> peer.get(10, TimeUnit.SECONDS));
                assertInstanceOf(javax.net.ssl.SSLHandshakeException.class, rejection.getCause());
                assertTrue(rejection.getCause().getMessage().contains("Empty client certificate chain"));
            }
        }
    }

    private static final class Fixture {
        private final TestCA ca = new TestCA(CertificateCreationOptions.builder(new X500Name("CN=ephemeral-ca")).build());
        private final KeyStore clients = store();
        private final KeyStore servers = store();
        private final X509Certificate clientB;
        private final X509Certificate serverA;
        private final X509Certificate serverB;

        Fixture() throws Exception {
            add(this.clients, "client-a", "client-a");
            this.clientB = add(this.clients, "client-b", "client-b");
            this.serverA = add(this.servers, "server-a", "localhost");
            this.serverB = add(this.servers, "server-b", "localhost");
        }

        private KeyStore store() throws Exception {
            KeyStore store = KeyStore.getInstance("PKCS12");
            store.load(null, null);
            store.setCertificateEntry("issuer", this.ca.getCertificate());
            return store;
        }

        private X509Certificate add(KeyStore store, String alias, String commonName) throws Exception {
            KeyPair pair = TestCA.generateKeyPair();
            X509Certificate certificate = this.ca.createAndSignCertificate(
                    CertificateCreationOptions.builder(new X500Name("CN=" + commonName)).build(), pair);
            store.setKeyEntry(alias, pair.getPrivate(), PASSWORD, new Certificate[] { certificate, this.ca.getCertificate() });
            return certificate;
        }

        private KeyManagerFactory managers(KeyStore store) throws Exception {
            KeyManagerFactory factory = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
            factory.init(store, PASSWORD);
            return factory;
        }

        SSLContext managed(KeyStore store, String alias, String protocol) throws Exception {
            KeystoreService keystore = mock(KeystoreService.class);
            when(keystore.getKeyStore()).thenReturn(store);
            when(keystore.getKeyManagers(anyString())).thenReturn(Arrays.asList(managers(store).getKeyManagers()));
            ComponentContext component = mock(ComponentContext.class);
            when(component.getBundleContext()).thenReturn(mock(BundleContext.class));
            SslManagerServiceImpl service = new SslManagerServiceImpl();
            service.activate(component, Map.of("ssl.default.protocol", protocol, "ssl.hostname.verification", "true"));
            TestUtil.setFieldValue(service, "sslServiceListeners", mock(SslServiceListeners.class));
            service.setKeystoreService(keystore, Map.of("kura.service.pid", "ephemeral-managed-store"));
            return service.getSSLContext(alias);
        }

        SSLContext plain(KeyStore store) throws Exception {
            TrustManagerFactory trust = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
            trust.init(store);
            SSLContext context = SSLContext.getInstance("TLS");
            context.init(managers(store).getKeyManagers(), trust.getTrustManagers(), null);
            return context;
        }

        SSLServerSocket socketServer() throws Exception {
            KeyStore oneServer = store();
            oneServer.setEntry("server-a", this.servers.getEntry("server-a", new KeyStore.PasswordProtection(PASSWORD)),
                    new KeyStore.PasswordProtection(PASSWORD));
            SSLServerSocket server = (SSLServerSocket) plain(oneServer).getServerSocketFactory()
                    .createServerSocket(0, 4, InetAddress.getLoopbackAddress());
            server.setSoTimeout(10000);
            server.setNeedClientAuth(true);
            return server;
        }

        CompletableFuture<X509Certificate> accept(SSLServerSocket server, boolean http) {
            CompletableFuture<X509Certificate> peer = new CompletableFuture<>();
            Thread.ofPlatform().daemon().start(() -> {
                try (SSLSocket socket = (SSLSocket) server.accept()) {
                    socket.setSoTimeout(10000);
                    socket.startHandshake();
                    X509Certificate certificate = (X509Certificate) socket.getSession().getPeerCertificates()[0];
                    if (http) {
                        BufferedReader input = new BufferedReader(new InputStreamReader(socket.getInputStream(), StandardCharsets.US_ASCII));
                        String line;
                        while ((line = input.readLine()) != null && !line.isEmpty()) { }
                        socket.getOutputStream().write("HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                                .getBytes(StandardCharsets.US_ASCII));
                    } else {
                        socket.getInputStream().read();
                    }
                    peer.complete(certificate);
                } catch (Throwable failure) {
                    peer.completeExceptionally(failure);
                }
            });
            return peer;
        }
    }
}
