/*******************************************************************************
 * Copyright (c) 2026 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.core.token.jwt.verifier;

import java.security.KeyStore.Entry;
import java.security.KeyStore.PrivateKeyEntry;
import java.security.KeyStore.TrustedCertificateEntry;
import java.security.cert.Certificate;
import java.security.cert.X509Certificate;
import java.security.interfaces.RSAPublicKey;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.atomic.AtomicReference;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ConfigurableComponent;
import org.eclipse.kura.core.token.jwt.KeystoreTracker;
import org.eclipse.kura.security.keystore.KeystoreChangedEvent;
import org.eclipse.kura.security.keystore.KeystoreService;
import org.eclipse.kura.security.token.TokenVerificationService;
import org.eclipse.kura.security.token.TokenVerifyRequest;
import org.eclipse.kura.security.token.VerificationProof;
import org.osgi.service.component.ComponentContext;
import org.osgi.service.event.Event;
import org.osgi.service.event.EventHandler;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class JwtVerificationService implements TokenVerificationService, ConfigurableComponent, EventHandler {

    private static final Logger logger = LoggerFactory.getLogger(JwtVerificationService.class);

    private final KeystoreTracker keystoreTracker = new KeystoreTracker();
    private Optional<JwtVerificationServiceOptions> serviceOptions = Optional.empty();

    private final AtomicReference<JwtVerifier> verifier = new AtomicReference<>();

    public synchronized void setKeystoreService(final KeystoreService keystoreService,
            final Map<String, Object> properties) {
        this.keystoreTracker.bind(keystoreService, properties);
        rebuildVerifier();
    }

    public synchronized void unsetKeystoreService(final KeystoreService keystoreService) {
        if (this.keystoreTracker.unbind(keystoreService)) {
            rebuildVerifier();
        }
    }

    @Override
    public synchronized void handleEvent(final Event event) {
        if (this.keystoreTracker.isContentChangedBy(event)) {
            logger.info("Trust store changed, reloading JWT key material");
            rebuildVerifier();
        }
    }

    public synchronized void activate(final ComponentContext context, final Map<String, Object> properties) {
        updated(properties);
    }

    public synchronized void updated(final Map<String, Object> properties) {
        this.serviceOptions = Optional.of(new JwtVerificationServiceOptions(properties));
        rebuildVerifier();
    }

    public synchronized void deactivate() {
        this.serviceOptions = Optional.empty();
        this.keystoreTracker.release();
        this.verifier.set(null);
    }

    @Override
    public VerificationProof verify(final TokenVerifyRequest request) throws KuraException {
        Objects.requireNonNull(request, "Request cannot be null");

        final JwtVerifier currentVerifier = this.verifier.get();

        if (currentVerifier == null) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR,
                    "JwtVerificationService misconfigured or not yet ready");
        }

        return currentVerifier.verify(request.getToken(), request.getIntendedConsumer());
    }

    private synchronized void rebuildVerifier() {
        logger.info("Rebuilding JWT verification service state");

        final Optional<JwtVerificationServiceOptions> options = this.serviceOptions;
        final Optional<KeystoreService> keystore = this.keystoreTracker.get();

        if (options.isEmpty() || keystore.isEmpty()) {
            this.verifier.set(null);
            return;
        }

        final Map<String, X509Certificate> certificates = loadVerificationCertificates(keystore.get(),
                options.get().getVerificationKeyAliases());

        if (certificates.isEmpty()) {
            logger.warn("No usable certificate found in the configured key store, token verification is not available");
            this.verifier.set(null);
            return;
        }

        this.verifier.set(new JwtVerifier(options.get(), certificates));

        logger.info("JWT verification service state rebuilt, {} trusted certificate(s) loaded", certificates.size());
    }

    private static Map<String, X509Certificate> loadVerificationCertificates(final KeystoreService keystoreService,
            final Set<String> aliases) {

        final Map<String, X509Certificate> result = new LinkedHashMap<>();

        try {
            for (final Map.Entry<String, Entry> storeEntry : keystoreService.getEntries().entrySet()) {
                final String alias = storeEntry.getKey();

                if (!aliases.isEmpty() && !aliases.contains(alias)) {
                    continue;
                }

                asX509Certificate(storeEntry.getValue()) //
                        .filter(JwtVerificationService::isX509CertificateUsable) //
                        .ifPresent(certificate -> result.put(alias, certificate));
            }
        } catch (Exception e) {
            logger.error("Error retrieving certificates for aliases: {}", aliases, e);
        }

        return result;
    }

    private static boolean isX509CertificateUsable(final X509Certificate certificate) {
        return certificate.getPublicKey() instanceof RSAPublicKey;
    }

    private static Optional<X509Certificate> asX509Certificate(final Entry entry) {
        if (entry instanceof TrustedCertificateEntry trustedCertificateEntry) {
            return asX509Certificate(trustedCertificateEntry.getTrustedCertificate());
        }

        if (entry instanceof PrivateKeyEntry privateKeyEntry) {
            return asX509Certificate(privateKeyEntry.getCertificate());
        }

        return Optional.empty();
    }

    private static Optional<X509Certificate> asX509Certificate(final Certificate certificate) {
        return certificate instanceof X509Certificate x509Certificate ? Optional.of(x509Certificate) : Optional.empty();
    }

}
