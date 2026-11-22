/*******************************************************************************
 * Copyright (c) 2011, 2025 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.core.ssl;

import javax.net.ssl.SSLEngine;
import javax.net.ssl.X509ExtendedKeyManager;
import static java.util.Objects.isNull;

import java.io.IOException;
import java.net.Socket;
import java.security.GeneralSecurityException;
import java.security.InvalidAlgorithmParameterException;
import java.security.KeyManagementException;
import java.security.KeyStore;
import java.security.KeyStoreException;
import java.security.NoSuchAlgorithmException;
import java.security.Principal;
import java.security.PrivateKey;
import java.security.cert.CertPathBuilder;
import java.security.cert.CertStore;
import java.security.cert.PKIXBuilderParameters;
import java.security.cert.PKIXParameters;
import java.security.cert.PKIXRevocationChecker;
import java.security.cert.X509CertSelector;
import java.security.cert.X509Certificate;
import java.util.Arrays;
import java.util.Collections;
import java.util.EnumSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

import javax.net.ssl.CertPathTrustManagerParameters;
import javax.net.ssl.KeyManager;
import javax.net.ssl.KeyManagerFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.TrustManagerFactory;
import javax.net.ssl.X509KeyManager;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.KuraRuntimeException;
import org.eclipse.kura.configuration.ConfigurableComponent;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.core.ssl.SslManagerServiceOptions.RevocationCheckMode;
import org.eclipse.kura.security.keystore.KeystoreChangedEvent;
import org.eclipse.kura.security.keystore.KeystoreService;
import org.eclipse.kura.ssl.SslManagerService;
import org.eclipse.kura.ssl.SslServiceListener;
import org.osgi.service.component.ComponentContext;
import org.osgi.service.event.Event;
import org.osgi.service.event.EventHandler;
import org.osgi.util.tracker.ServiceTracker;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class SslManagerServiceImpl implements SslManagerService, ConfigurableComponent, EventHandler {

    private static final Logger logger = LoggerFactory.getLogger(SslManagerServiceImpl.class);

    private SslServiceListeners sslServiceListeners;

    private SslManagerServiceOptions options;

    private KeystoreService keystoreService;
    private KeystoreService truststoreKeystoreService;

    private Map<ConnectionSslOptions, SSLContext> sslContexts;

    private Optional<String> keystoreServicePid = Optional.empty();
    private Optional<String> truststoreKeystoreServicePid = Optional.empty();

    // ----------------------------------------------------------------
    //
    // Dependencies
    //
    // ----------------------------------------------------------------

    public void setKeystoreService(KeystoreService keystoreService, final Map<String, Object> properties) {
        this.keystoreService = keystoreService;
        this.keystoreServicePid = Optional.of((String) properties.get(ConfigurationService.KURA_SERVICE_PID));

        this.clearSslContexCache();

        if (this.sslServiceListeners != null) {
            // Notify listeners that service has been updated
            this.sslServiceListeners.onConfigurationUpdated();
        }
    }

    public void unsetKeystoreService(KeystoreService keystoreService) {
        if (this.keystoreService == keystoreService) {

            this.keystoreService = null;
            this.keystoreServicePid = Optional.empty();

            this.clearSslContexCache();

            if (this.sslServiceListeners != null) {
                // Notify listeners that service has been updated
                this.sslServiceListeners.onConfigurationUpdated();
            }
        }
    }

    public void setTruststoreKeystoreService(KeystoreService keystoreService, final Map<String, Object> properties) {
        this.truststoreKeystoreService = keystoreService;
        this.truststoreKeystoreServicePid = Optional.of((String) properties.get(ConfigurationService.KURA_SERVICE_PID));

        this.clearSslContexCache();

        if (this.sslServiceListeners != null) {
            // Notify listeners that service has been updated
            this.sslServiceListeners.onConfigurationUpdated();
        }
    }

    public void unsetTruststoreKeystoreService(KeystoreService keystoreService) {
        if (this.truststoreKeystoreService == keystoreService) {

            this.truststoreKeystoreService = null;
            this.truststoreKeystoreServicePid = Optional.empty();

            this.clearSslContexCache();

            if (this.sslServiceListeners != null) {
                // Notify listeners that service has been updated
                this.sslServiceListeners.onConfigurationUpdated();
            }
        }
    }

    // ----------------------------------------------------------------
    //
    // Activation APIs
    //
    // ----------------------------------------------------------------

    protected void activate(ComponentContext componentContext, Map<String, Object> properties) {
        logger.info("activate...");

        this.options = new SslManagerServiceOptions(properties);
        this.sslContexts = new ConcurrentHashMap<>();

        ServiceTracker<SslServiceListener, SslServiceListener> listenersTracker = new ServiceTracker<>(
                componentContext.getBundleContext(), SslServiceListener.class, null);

        // Deferred open of tracker to prevent
        // java.lang.Exception: Recursive invocation of
        // ServiceFactory.getService
        // on ProSyst
        this.sslServiceListeners = new SslServiceListeners(listenersTracker);
    }

    public void updated(Map<String, Object> properties) {
        logger.info("updated...");

        this.options = new SslManagerServiceOptions(properties);
        this.sslContexts = new ConcurrentHashMap<>();

        // Notify listeners that service has been updated
        this.sslServiceListeners.onConfigurationUpdated();
    }

    protected void deactivate(ComponentContext componentContext) {
        logger.info("deactivate...");
        this.sslServiceListeners.close();
    }

    // ----------------------------------------------------------------
    //
    // Service APIs
    //
    // ----------------------------------------------------------------

    @Override
    public SSLContext getSSLContext() throws GeneralSecurityException, IOException {
        return getSSLContext("");
    }

    @Override
    public SSLContext getSSLContext(String keyAlias) throws GeneralSecurityException, IOException {
        String protocol = this.options.getSslProtocol();
        String ciphers = this.options.getSslCiphers();
        boolean hostnameVerifcation = this.options.isSslHostnameVerification();

        return getSSLContext(protocol, ciphers, keyAlias, hostnameVerifcation);
    }

    @Override
    public SSLSocketFactory getSSLSocketFactory() throws GeneralSecurityException, IOException {
        return getSSLContext().getSocketFactory();
    }

    @Override
    public SSLSocketFactory getSSLSocketFactory(String keyAlias) throws GeneralSecurityException, IOException {
        return getSSLContext(keyAlias).getSocketFactory();
    }

    // ----------------------------------------------------------------
    //
    // Private methods
    //
    // ----------------------------------------------------------------

    private SSLContext getSSLContextInternal(ConnectionSslOptions options)
            throws GeneralSecurityException, IOException {
        // Only create a new SSLSocketFactory instance if the configuration has
        // changed or
        // for a new alias.
        // This allows for SSL Context Resumption and abbreviated SSL handshake
        // in case of reconnects to the same host.
        SSLContext context = this.sslContexts.get(options);
        if (context == null) {
            String alias = options.getAlias();
            alias = alias == null ? "" : alias;
            if (!alias.equals("")) {
                KeyStore ks;
                try {
                    ks = this.keystoreService.getKeyStore();
                } catch (KuraException e) {
                    throw new KeyStoreException("Failed to load the service keystore", e);
                }
                List<String> aliases = Collections.list(ks.aliases());
                if (aliases.isEmpty()) {
                    options.setAlias("");
                } else if (ks.containsAlias(alias) && !aliases.contains(alias)) {
                    // Preserve the bound keystore's case semantics when its manager uses canonical aliases.
                    final String requestedAlias = alias;
                    aliases.stream().filter(requestedAlias::equalsIgnoreCase).findFirst().ifPresent(options::setAlias);
                }
                context = this.sslContexts.get(options);
                if (context != null) {
                    return context;
                }
            }
            logger.info("Creating a new SSLSocketFactory instance");

            TrustManager[] tms = getTrustManagers();
            KeyManager[] kms = getKeyManagers(options.getAlias());

            context = createSSLContext(options.getProtocol(), options.getCiphers(), kms, tms,
                    options.getHostnameVerification());
            this.sslContexts.put(options, context);
        }

        return context;
    }

    private static SSLContext createSSLContext(String protocol, String ciphers, KeyManager[] kms, TrustManager[] tms,
            boolean hostnameVerification) throws NoSuchAlgorithmException, KeyManagementException {
        // inits the SSL context
        SSLContext sslCtx;
        if (protocol == null || protocol.isEmpty()) {
            sslCtx = SSLContext.getDefault();
        } else {
            sslCtx = SSLContext.getInstance(protocol);
            sslCtx.init(kms, tms, null);
        }

        // get the SSLSocketFactory
        final SSLSocketFactory sslSocketFactory = sslCtx.getSocketFactory();
        final SSLSocketFactoryWrapper socketFactoryWrapper = new SSLSocketFactoryWrapper(sslSocketFactory, ciphers,
                hostnameVerification);

        // wrap it
        return new SSLContext(new SSLContextSPIWrapper(sslCtx, socketFactoryWrapper), sslCtx.getProvider(),
                sslCtx.getProtocol()) {
        };
    }

    private TrustManager[] getTrustManagers() throws GeneralSecurityException, IOException {
        TrustManager[] result = new TrustManager[0];
        TrustManagerFactory tmf = null;

        final KeystoreService ks;

        if (this.truststoreKeystoreService != null) {
            ks = truststoreKeystoreService;
        } else if (this.keystoreService != null) {
            ks = keystoreService;
        } else {
            return result;
        }

        try {
            KeyStore ts = ks.getKeyStore();
            tmf = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
            initTrustManagerFactory(tmf, ts);
            result = tmf.getTrustManagers();
        } catch (KuraException e) {
            throw new IOException(e);
        }

        return result;
    }

    private void initTrustManagerFactory(final TrustManagerFactory trustManagerFactory, final KeyStore keyStore)
            throws KeyStoreException, InvalidAlgorithmParameterException, NoSuchAlgorithmException {

        if (!this.options.isSslRevocationCheckEnabled()) {
            trustManagerFactory.init(keyStore);
            return;
        }

        List<CertStore> certStores;

        try {
            certStores = Collections.singletonList(keystoreService.getCRLStore());
        } catch (final Exception e) {
            logger.warn("Failed to get CRL store", e);
            certStores = Collections.emptyList();
        }

        final EnumSet<PKIXRevocationChecker.Option> checkerOptions;

        final RevocationCheckMode revocationCheckMode = options.getRevocationCheckMode();

        if (revocationCheckMode == RevocationCheckMode.CRL_ONLY) {
            checkerOptions = EnumSet.of(PKIXRevocationChecker.Option.PREFER_CRLS,
                    PKIXRevocationChecker.Option.NO_FALLBACK);
        } else if (revocationCheckMode == RevocationCheckMode.PREFER_CRL) {
            checkerOptions = EnumSet.of(PKIXRevocationChecker.Option.PREFER_CRLS);
        } else {
            checkerOptions = EnumSet.noneOf(PKIXRevocationChecker.Option.class);
        }

        if (this.options.isSslRevocationSoftFail()) {
            checkerOptions.add(PKIXRevocationChecker.Option.SOFT_FAIL);
        }

        final CertPathBuilder certPathBuilder = CertPathBuilder.getInstance("PKIX");
        final PKIXRevocationChecker revocationChecker = (PKIXRevocationChecker) certPathBuilder.getRevocationChecker();
        revocationChecker.setOptions(checkerOptions);

        PKIXParameters pkixParams = new PKIXBuilderParameters(keyStore, new X509CertSelector());
        pkixParams.setRevocationEnabled(true);
        pkixParams.setCertStores(certStores);
        pkixParams.addCertPathChecker(revocationChecker);

        trustManagerFactory.init(new CertPathTrustManagerParameters(pkixParams));
    }

    @Override
    public void handleEvent(final Event event) {
        if (!(event instanceof KeystoreChangedEvent)) {
            return;
        }

        final KeystoreChangedEvent keystoreChangedEvent = (KeystoreChangedEvent) event;

        final Optional<String> eventPid = Optional.of(keystoreChangedEvent.getSenderPid());

        if (this.keystoreServicePid.equals(eventPid) || this.truststoreKeystoreServicePid.equals(eventPid)) {
            this.clearSslContexCache();
            this.sslServiceListeners.onConfigurationUpdated();
        }
    }

    private void clearSslContexCache() {
        if (sslContexts != null) {
            this.sslContexts.clear();
        }
    }

    private SSLContext getSSLContext(String protocol, String ciphers, String keyAlias,
            boolean hostnameVerification) throws GeneralSecurityException, IOException {
        ConnectionSslOptions connection = new ConnectionSslOptions(this.options);
        connection.setProtocol(protocol);
        connection.setCiphers(ciphers);
        connection.setAlias(keyAlias);
        connection.setHostnameVerification(hostnameVerification);
        return getSSLContextInternal(connection);
    }

    private KeyManager[] getKeyManagers(String alias) throws IOException {
        if (isNull(this.keystoreService)) {
            throw new KuraRuntimeException(KuraErrorCode.INTERNAL_ERROR);
        }
        try {
            List<KeyManager> managers = this.keystoreService.getKeyManagers(KeyManagerFactory.getDefaultAlgorithm());
            if (alias == null || alias.isEmpty()) {
                return managers.toArray(new KeyManager[0]);
            }
            return managers.stream().filter(X509KeyManager.class::isInstance).map(X509KeyManager.class::cast)
                    .filter(manager -> manager.getCertificateChain(alias) != null && manager.getPrivateKey(alias) != null)
                    .map(manager -> new ManagedAliasKeyManager(alias, manager)).toArray(KeyManager[]::new);
        } catch (KuraException failure) {
            throw new IOException(failure);
        }
    }

    /** Limits both socket and engine handshakes to the requested managed credential. */
    private static final class ManagedAliasKeyManager extends X509ExtendedKeyManager {
        private final String alias;
        private final X509KeyManager delegate;

        ManagedAliasKeyManager(String alias, X509KeyManager delegate) {
            this.alias = alias;
            this.delegate = delegate;
        }

        private boolean containsSelected(String[] aliases) {
            return aliases != null && Arrays.asList(aliases).contains(this.alias);
        }

        @Override
        public String[] getClientAliases(String keyType, Principal[] issuers) {
            return containsSelected(this.delegate.getClientAliases(keyType, issuers)) ? new String[] { this.alias } : null;
        }

        @Override
        public String chooseClientAlias(String[] keyTypes, Principal[] issuers, Socket socket) {
            if (keyTypes != null) {
                for (String keyType : keyTypes) {
                    if (containsSelected(this.delegate.getClientAliases(keyType, issuers))) {
                        return this.alias;
                    }
                }
            }
            return null;
        }

        @Override
        public String[] getServerAliases(String keyType, Principal[] issuers) {
            return containsSelected(this.delegate.getServerAliases(keyType, issuers)) ? new String[] { this.alias } : null;
        }

        @Override
        public String chooseServerAlias(String keyType, Principal[] issuers, Socket socket) {
            return containsSelected(this.delegate.getServerAliases(keyType, issuers)) ? this.alias : null;
        }

        @Override
        public String chooseEngineClientAlias(String[] keyTypes, Principal[] issuers, SSLEngine engine) {
            return chooseClientAlias(keyTypes, issuers, null);
        }

        @Override
        public String chooseEngineServerAlias(String keyType, Principal[] issuers, SSLEngine engine) {
            return chooseServerAlias(keyType, issuers, null);
        }

        @Override
        public X509Certificate[] getCertificateChain(String requestedAlias) {
            return this.alias.equals(requestedAlias) ? this.delegate.getCertificateChain(this.alias) : null;
        }

        @Override
        public PrivateKey getPrivateKey(String requestedAlias) {
            return this.alias.equals(requestedAlias) ? this.delegate.getPrivateKey(this.alias) : null;
        }
    }
}
