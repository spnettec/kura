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
import java.security.KeyStore;
import java.security.KeyStore.Entry;
import java.security.KeyStoreException;
import java.security.NoSuchAlgorithmException;
import java.security.Provider;
import java.security.SecureRandom;
import java.security.Security;
import java.security.UnrecoverableKeyException;
import java.security.cert.CertificateException;
import java.security.spec.AlgorithmParameterSpec;
import java.util.Arrays;
import java.util.Map;
import java.util.Optional;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.system.SystemService;
import org.osgi.service.component.ComponentContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class PKCS11KeystoreServiceImpl extends BaseKeystoreService {

    private static final Logger logger = LoggerFactory.getLogger(PKCS11KeystoreServiceImpl.class);

    private Optional<Provider> provider = Optional.empty();
    private PKCS11KeystoreServiceOptions options;
    private PKCS11PinCheck.Result pinCheck;

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
                    this.pinCheck = null;
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
        if (this.pinCheck == PKCS11PinCheck.Result.REJECTED || this.pinCheck == PKCS11PinCheck.Result.UNCERTAIN) {
            throw new KuraException(KuraErrorCode.SECURITY_EXCEPTION);
        }
        final char[] pin = this.options.getPin(cryptoService).orElse(null);
        boolean loaded = false;
        try {
            if (pin != null && this.pinCheck != PKCS11PinCheck.Result.VERIFIED) {
                verifyConfiguredPin(pin);
            }
            final KeyStore store = KeyStore.getInstance("PKCS11", getOrRegisterProvider());
            store.load(null, pin);
            loaded = true;
            return new KeystoreInstanceImpl(store, pin);
        } catch (KeyStoreException | NoSuchAlgorithmException | CertificateException | IOException e) {
            if (e instanceof IOException && e.getCause() instanceof UnrecoverableKeyException) {
                rejectPin();
            }
            removeProvider();
            logger.warn("Keystore exception", e);
            throw new KuraException(KuraErrorCode.SECURITY_EXCEPTION);
        } finally {
            if (!loaded && pin != null) {
                Arrays.fill(pin, '\0');
            }
        }
    }

    private void verifyConfiguredPin(char[] pin) throws KuraException {
        // PKCS#11 login is shared by sessions in one application. Verify a
        // configured PIN in a separate JVM without logging out the live token.
        final String config = getProviderConfig();
        switch (checkPin(config, pin)) {
        case VERIFIED:
            this.pinCheck = PKCS11PinCheck.Result.VERIFIED;
            break;
        case REJECTED:
            rejectPin();
            throw new KuraException(KuraErrorCode.SECURITY_EXCEPTION);
        case UNCERTAIN:
            this.pinCheck = PKCS11PinCheck.Result.UNCERTAIN;
            logger.warn("PKCS11 PIN verification was interrupted; further loads require new authentication settings");
            throw new KuraException(KuraErrorCode.SECURITY_EXCEPTION);
        case UNAVAILABLE:
            throw new KuraException(KuraErrorCode.SERVICE_UNAVAILABLE);
        }
    }

    PKCS11PinCheck.Result checkPin(String config, char[] pin) {
        return PKCS11PinCheck.verify(config, pin);
    }

    private void rejectPin() {
        this.pinCheck = PKCS11PinCheck.Result.REJECTED;
        logger.warn("PKCS11 PIN rejected; further loads require new authentication settings");
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
        if (this.provider.isPresent()) {
            final Provider registered = this.provider.get();
            if (Security.getProvider(registered.getName()) == registered) {
                return registered;
            }
            this.provider = Optional.empty();
            logger.warn("PKCS11 provider {} is no longer registered by this service", registered.getName());
            throw new KuraException(KuraErrorCode.SERVICE_UNAVAILABLE);
        }

        logger.info("Registering provider...");

        final String config = getProviderConfig();

        logger.debug("PKCS11 config: {}", config);

        final Provider newProvider = configureProvider(config);
        try {
            if (Security.addProvider(newProvider) < 0) {
                logger.warn("PKCS11 provider name {} is already registered", newProvider.getName());
                throw new KuraException(KuraErrorCode.SERVICE_UNAVAILABLE);
            }
        } catch (SecurityException e) {
            logger.warn("Failed to register PKCS11 provider {}", newProvider.getName(), e);
            throw new KuraException(KuraErrorCode.SERVICE_UNAVAILABLE);
        }

        this.provider = Optional.of(newProvider);

        logger.info("Registering provider...done");

        return newProvider;
    }

    private String getProviderConfig() throws KuraException {
        return this.options.buildSunPKCS11ProviderConfig()
                .orElseThrow(() -> new KuraException(KuraErrorCode.CONFIGURATION_ATTRIBUTE_UNDEFINED, "library.path"));
    }

    Provider configureProvider(String config) throws KuraException {
        if (System.getProperty("java.version").startsWith("1.")) {
            return configureProviderJava8(config);
        }
        return configureProviderJava9(config);
    }

    private Provider configureProviderJava8(final String config) throws KuraException {
        try {
            final Class<?> providerClass = Class.forName("sun.security.pkcs11.SunPKCS11");

            final Constructor<?> ctor = providerClass.getConstructor(InputStream.class);

            return (Provider) ctor.newInstance(new ByteArrayInputStream(config.getBytes()));

        } catch (final Exception e) {
            logger.warn("failed to load PKCS11 provider", e);
            throw new KuraException(KuraErrorCode.SERVICE_UNAVAILABLE);
        }
    }

    private Provider configureProviderJava9(final String config) throws KuraException {

        try {
            final Provider prototype = Security.getProvider("SunPKCS11");

            final Method configure = Provider.class.getMethod("configure", String.class);

            final File configFile = Files.createTempFile(null, null).toFile();

            try {
                try (final OutputStream out = new FileOutputStream(configFile)) {
                    out.write(config.getBytes());
                }

                return (Provider) configure.invoke(prototype, configFile.getAbsolutePath());
            } finally {
                Files.deleteIfExists(configFile.toPath());
            }

        } catch (final Exception e) {
            logger.warn("failed to load PKCS11 provider", e);
            throw new KuraException(KuraErrorCode.SERVICE_UNAVAILABLE);
        }
    }

    private synchronized void removeProvider() {
        if (this.provider.isEmpty()) {
            return;
        }
        final Provider registered = this.provider.get();
        final String name = registered.getName();
        // JCA's process-wide insert and remove operations use this monitor.
        synchronized (Security.class) {
            if (Security.getProvider(name) == registered) {
                Security.removeProvider(name);
            }
        }
        this.provider = Optional.empty();
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
