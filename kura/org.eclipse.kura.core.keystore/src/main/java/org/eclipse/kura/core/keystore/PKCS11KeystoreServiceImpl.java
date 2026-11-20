/*******************************************************************************
 * Copyright (c) 2022, 2024 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.core.keystore;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.security.AuthProvider;
import java.security.KeyStore;
import java.security.KeyStore.Entry;
import java.security.KeyStoreException;
import java.security.NoSuchAlgorithmException;
import java.security.Provider;
import java.security.ProviderException;
import java.security.SecureRandom;
import java.security.Security;
import java.security.UnrecoverableKeyException;
import java.security.cert.CertificateException;
import java.security.spec.AlgorithmParameterSpec;
import java.util.Arrays;
import java.util.Map;
import java.util.Optional;

import javax.security.auth.login.LoginException;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.system.SystemService;
import org.osgi.service.component.ComponentContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class PKCS11KeystoreServiceImpl extends BaseKeystoreService {

    private static final Logger logger = LoggerFactory.getLogger(PKCS11KeystoreServiceImpl.class);

    Optional<Provider> provider = Optional.empty();
    private PKCS11KeystoreServiceOptions options;
    private AuthProvider authenticatedProvider;
    private boolean logoutFailed;
    private boolean pinRejected;

    private CryptoService cryptoService;
    private SystemService systemService;

    public void setCryptoService(final CryptoService cryptoService) {
        this.cryptoService = cryptoService;
    }

    public void setSystemService(final SystemService systemService) {
        this.systemService = systemService;
    }

    @Override
    public void activate(ComponentContext context, Map<String, Object> properties) {
        this.options = new PKCS11KeystoreServiceOptions(properties, (String) properties.get(KURA_SERVICE_PID));
        super.activate(context, properties);
    }

    @Override
    public void updated(Map<String, Object> properties) {
        PKCS11KeystoreServiceOptions newOptions = new PKCS11KeystoreServiceOptions(properties, ownPid);
        boolean changed;
        synchronized (this) {
            changed = !newOptions.equals(this.options);
            if (changed) {
                if (!this.options.hasSameAuthentication(newOptions)) {
                    retireAuthentication();
                }
                removeProvider();
                this.options = newOptions;
            }
        }
        super.updated(properties, changed);
        if (changed) {
            postChangedEvent();
        }
    }

    @Override
    public void deactivate() {
        super.deactivate();
        removeProvider();
    }

    @Override
    protected synchronized KeystoreInstance loadKeystore() throws KuraException {
        if (this.logoutFailed || this.pinRejected) {
            throw new KuraException(KuraErrorCode.SECURITY_EXCEPTION);
        }
        final Provider currentProvider = getOrRegisterProvider();
        final char[] pin = this.options.getPin(cryptoService).orElse(null);
        try {
            final KeyStore store = KeyStore.getInstance("PKCS11", currentProvider);
            store.load(null, pin);
            if (currentProvider instanceof AuthProvider authenticated) {
                this.authenticatedProvider = authenticated;
            }
            return new KeystoreInstanceImpl(store, pin);
        } catch (KeyStoreException | NoSuchAlgorithmException | CertificateException | IOException e) {
            if (pin != null) {
                Arrays.fill(pin, '\0');
            }
            if (e instanceof IOException && e.getCause() instanceof UnrecoverableKeyException) {
                this.pinRejected = true;
                logger.warn("PKCS11 PIN rejected; further loads require new authentication settings");
            }
            removeProvider();
            logger.warn("Keystore exception", e);
            throw new KuraException(KuraErrorCode.SECURITY_EXCEPTION);
        }
    }

    private void retireAuthentication() {
        this.pinRejected = false;
        // SunPKCS11 can keep a token logged in across provider registrations.
        if (this.authenticatedProvider == null && this.provider.orElse(null) instanceof AuthProvider authenticated) {
            this.authenticatedProvider = authenticated;
        }
        if (this.authenticatedProvider != null) {
            try {
                this.authenticatedProvider.logout();
                this.authenticatedProvider = null;
                this.logoutFailed = false;
            } catch (LoginException | ProviderException | SecurityException e) {
                this.logoutFailed = true;
                logger.warn("Could not retire the previous PKCS11 login", e);
            }
        }
    }

    @Override
    protected void saveKeystore(KeystoreInstance keystore) {
        // no need
    }

    @Override
    public void setEntry(String alias, Entry entry) throws KuraException {
        throw new KuraException(KuraErrorCode.OPERATION_NOT_SUPPORTED);
    }

    @Override
    public void deleteEntry(String alias) throws KuraException {
        throw new KuraException(KuraErrorCode.OPERATION_NOT_SUPPORTED);
    }

    @Override
    public void createKeyPair(String alias, String algorithm, AlgorithmParameterSpec algorithmParameter,
            String signatureAlgorithm, String attributes) throws KuraException {
        throw new KuraException(KuraErrorCode.OPERATION_NOT_SUPPORTED);
    }

    @Override
    public void createKeyPair(String alias, String algorithm, AlgorithmParameterSpec algorithmParameter,
            String signatureAlgorithm, String attributes, SecureRandom secureRandom) throws KuraException {
        throw new KuraException(KuraErrorCode.OPERATION_NOT_SUPPORTED);
    }

    @Override
    public void createKeyPair(String alias, String algorithm, int keySize, String signatureAlgorithm, String attributes)
            throws KuraException {
        throw new KuraException(KuraErrorCode.OPERATION_NOT_SUPPORTED);
    }

    @Override
    public void createKeyPair(String alias, String algorithm, int keySize, String signatureAlgorithm, String attributes,
            SecureRandom secureRandom) throws KuraException {
        throw new KuraException(KuraErrorCode.OPERATION_NOT_SUPPORTED);
    }

    @Override
    protected String getCrlStorePath() {
        return this.options.getCrlStorePath().orElseGet(
                () -> this.systemService.getKuraUserConfigDirectory() + "/security/pkcs11." + ownPid + ".crl");
    }

    private synchronized Provider getOrRegisterProvider() throws KuraException {
        if (provider.isPresent()) {
            return provider.get();
        }

        logger.info("Registering provider...");

        final String config = this.options.buildSunPKCS11ProviderConfig()
                .orElseThrow(() -> new KuraException(KuraErrorCode.CONFIGURATION_ATTRIBUTE_UNDEFINED, "library.path"));

        logger.debug("PKCS11 config: {}", config);

        final String javaVersion = System.getProperty("java.version");

        final Provider newProvider;

        if (javaVersion.startsWith("1.")) {
            newProvider = registerProviderJava8(config);
        } else {
            newProvider = registerProviderJava9(config);
        }

        this.provider = Optional.of(newProvider);

        logger.info("Registering provider...done");

        return newProvider;
    }

    private Provider registerProviderJava8(final String config) throws KuraException {
        try {
            final Class<?> providerClass = Class.forName("sun.security.pkcs11.SunPKCS11");

            final Constructor<?> ctor = providerClass.getConstructor(InputStream.class);

            final Provider newProvider = (Provider) ctor.newInstance(new ByteArrayInputStream(config.getBytes()));

            Security.addProvider(newProvider);

            return newProvider;

        } catch (final Exception e) {
            logger.warn("failed to load PKCS11 provider", e);
            throw new KuraException(KuraErrorCode.SERVICE_UNAVAILABLE);
        }
    }

    private Provider registerProviderJava9(final String config) throws KuraException {

        try {
            Provider newProvider = Security.getProvider("SunPKCS11");

            final Method configure = Provider.class.getMethod("configure", String.class);

            final File configFile = Files.createTempFile(null, null).toFile();

            try {
                try (final OutputStream out = new FileOutputStream(configFile)) {
                    out.write(config.getBytes());
                }

                newProvider = (Provider) configure.invoke(newProvider, configFile.getAbsolutePath());
                Security.addProvider(newProvider);
                return newProvider;
            } finally {
                Files.deleteIfExists(configFile.toPath());
            }

        } catch (final Exception e) {
            logger.warn("failed to load PKCS11 provider", e);
            throw new KuraException(KuraErrorCode.SERVICE_UNAVAILABLE);
        }
    }

    private synchronized void removeProvider() {
        if (!provider.isPresent()) {
            return;
        }

        logger.info("Removing provider...");
        Security.removeProvider(provider.get().getName());

        provider = Optional.empty();
        logger.info("Removing provider...done");
    }

    private class KeystoreInstanceImpl implements KeystoreInstance {

        private final KeyStore keystore;
        private final char[] password;

        KeystoreInstanceImpl(KeyStore keystore, char[] password) {
            this.keystore = keystore;
            this.password = password;
        }

        @Override
        public KeyStore getKeystore() {
            return keystore;
        }

        @Override
        public char[] getPassword() {
            return password;
        }

    }
}
