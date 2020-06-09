/**
 * Copyright (c) 2018, 2020 Eurotech and/or its affiliates and others
 *
 *  All rights reserved. This program and the accompanying materials
 *  are made available under the terms of the Eclipse Public License v1.0
 *  which accompanies this distribution, and is available at
 *  http://www.eclipse.org/legal/epl-v10.html
 *
 */

package org.eclipse.kura.internal.driver.opcua.auth;

import java.security.InvalidKeyException;
import java.security.KeyPair;
import java.security.PublicKey;
import java.security.SignatureException;
import java.security.cert.CertPathBuilder;
import java.security.cert.CertPathChecker;
import java.security.cert.CertStore;
import java.security.cert.CollectionCertStoreParameters;
import java.security.cert.PKIXBuilderParameters;
import java.security.cert.PKIXCertPathBuilderResult;
import java.security.cert.PKIXRevocationChecker;
import java.security.cert.TrustAnchor;
import java.security.cert.X509CRL;
import java.security.cert.X509CertSelector;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;

import org.eclipse.milo.opcua.stack.client.security.ClientCertificateValidator;
import org.eclipse.milo.opcua.stack.core.StatusCodes;
import org.eclipse.milo.opcua.stack.core.UaException;
import org.eclipse.milo.opcua.stack.core.util.validation.CertificateValidationUtil;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.google.common.base.Preconditions;
import com.google.common.collect.Lists;
import com.google.common.collect.Sets;

public abstract class CertificateManager implements ClientCertificateValidator {

    private static final Logger logger = LoggerFactory.getLogger(CertificateManager.class);

    private final boolean enabled;

    private Set<X509Certificate> trustedCertificates = Collections.emptySet();
    private Set<X509Certificate> issuerCertificates = Collections.emptySet();

    private KeyPair clientKeyPair;
    private X509Certificate clientCertificate;

    public CertificateManager(final boolean enabled) {
        this.enabled = enabled;
    }

    public abstract void load() throws Exception;

    public KeyPair getClientKeyPair() {
        return this.clientKeyPair;
    }

    public X509Certificate getClientCertificate() {
        return this.clientCertificate;
    }

    @Override
    public void validateCertificateChain(List<X509Certificate> certificateChain) throws UaException {
        if (!this.enabled) {
            logger.debug("skipping certificate chain verification");
            return;
        }

        logger.debug("verifiyng certificate chain: {}", certificateChain);

        verifyTrustChain(certificateChain, this.trustedCertificates, this.issuerCertificates);

        logger.debug("certificate chain verification successful");
    }

    @Override
    public void validateCertificateChain(List<X509Certificate> certificateChain, String applicationUri,
            String... validHostNames) throws UaException {
        validateCertificateChain(certificateChain);

        X509Certificate certificate = certificateChain.get(0);

        CertificateValidationUtil.checkApplicationUri(certificate, applicationUri);

        try {
            CertificateValidationUtil.checkHostnameOrIpAddress(certificate, validHostNames);
        } catch (UaException e) {
            logger.warn("check suppressed: certificate failed hostname check: {}",
                    certificate.getSubjectX500Principal().getName());
        }

    }

    protected void load(final X509Certificate[] certificates, final KeyPair clientKeyPair,
            final X509Certificate clientCertificate) throws UaException {
        final Set<X509Certificate> trustedCerts = new HashSet<>();
        final Set<X509Certificate> issuerCerts = new HashSet<>();

        for (final X509Certificate cert : certificates) {
            if (certificateIsSelfSigned(cert)) {
                issuerCerts.add(cert);
            } else {
                trustedCerts.add(cert);
            }
        }

        logger.debug("client certificate loaded: {}", clientCertificate != null);
        logger.debug("client key pair loaded: {}", clientKeyPair != null);
        logger.debug("available issuer certificates: {}", issuerCerts.size());
        logger.debug("available trusted certificates: {}", trustedCerts.size());

        this.trustedCertificates = trustedCerts;
        this.issuerCertificates = issuerCerts;

        this.clientKeyPair = clientKeyPair;
        this.clientCertificate = clientCertificate;
    }

    private static void verifyTrustChain(List<X509Certificate> certificateChain,
            Set<X509Certificate> trustedCertificates, Set<X509Certificate> issuerCertificates) throws UaException {

        verifyTrustChain(certificateChain, trustedCertificates, Collections.emptySet(), issuerCertificates,
                Collections.emptySet());
    }

    private static void verifyTrustChain(List<X509Certificate> certificateChain,
            Collection<X509Certificate> trustedCertificates, Collection<X509CRL> trustedCrls,
            Collection<X509Certificate> issuerCertificates, Collection<X509CRL> issuerCrls) throws UaException {

        Preconditions.checkArgument(!certificateChain.isEmpty(), "certificateChain must not be empty");

        if (logger.isTraceEnabled()) {
            logger.trace("certificateChain: {}", certificateChain);
            logger.trace("trustedCertificates: {}", trustedCertificates);
            logger.trace("trustedCrls: {}", trustedCrls);
            logger.trace("issuerCertificates: {}", issuerCertificates);
            logger.trace("issuerCrls: {}", issuerCrls);
        }

        X509Certificate certificate = certificateChain.get(0);

        try {
            Set<TrustAnchor> trustAnchors = new HashSet<>();
            for (X509Certificate c : trustedCertificates) {
                if (certificateIsCa(c) && certificateIsSelfSigned(c)) {
                    trustAnchors.add(new TrustAnchor(c, null));
                }
            }
            for (X509Certificate c : issuerCertificates) {
                if (certificateIsCa(c) && certificateIsSelfSigned(c)) {
                    trustAnchors.add(new TrustAnchor(c, null));
                }
            }

            X509CertSelector selector = new X509CertSelector();
            selector.setCertificate(certificate);

            PKIXBuilderParameters params = new PKIXBuilderParameters(trustAnchors, selector);

            // Add a CertStore containing any intermediate certs and CRLs
            Collection<Object> collection = Lists.newArrayList();
            collection.addAll(certificateChain.subList(1, certificateChain.size()));

            for (X509Certificate c : trustedCertificates) {
                if (certificateIsCa(c) && !certificateIsSelfSigned(c)) {
                    collection.add(c);
                }
            }
            for (X509Certificate c : issuerCertificates) {
                if (certificateIsCa(c) && !certificateIsSelfSigned(c)) {
                    collection.add(c);
                }
            }

            collection.addAll(trustedCrls);
            collection.addAll(issuerCrls);

            if (collection.size() > 0) {
                CertStore certStore = CertStore.getInstance("Collection",
                        new CollectionCertStoreParameters(collection));

                params.addCertStore(certStore);
            }

            // Only enable revocation checking if the CRL list is non-empty
            params.setRevocationEnabled(!trustedCrls.isEmpty() || !issuerCrls.isEmpty());

            CertPathBuilder builder = CertPathBuilder.getInstance("PKIX");

            // Set up revocation options regardless of whether it's actually enabled
            CertPathChecker revocationChecker = builder.getRevocationChecker();

            if (revocationChecker instanceof PKIXRevocationChecker) {
                ((PKIXRevocationChecker) revocationChecker)
                        .setOptions(Sets.newHashSet(PKIXRevocationChecker.Option.NO_FALLBACK,
                                PKIXRevocationChecker.Option.PREFER_CRLS, PKIXRevocationChecker.Option.SOFT_FAIL));
            }

            PKIXCertPathBuilderResult result = (PKIXCertPathBuilderResult) builder.build(params);

            List<X509Certificate> certificatePath = new ArrayList<>();

            result.getCertPath().getCertificates().stream().map(X509Certificate.class::cast)
                    .forEach(certificatePath::add);

            certificatePath.add(result.getTrustAnchor().getTrustedCert());

            logger.debug("certificate path: {}", certificatePath);

            if (certificatePath.stream().noneMatch(trustedCertificates::contains)) {
                throw new UaException(StatusCodes.Bad_SecurityChecksFailed,
                        "certificate path did not contain a trusted certificate");
            }
        } catch (UaException e) {
            throw e;
        } catch (Throwable t) {
            logger.debug("certificate path validation failed: {}", t.getMessage());

            throw new UaException(StatusCodes.Bad_SecurityChecksFailed, "certificate path validation failed");
        }
    }

    private static boolean certificateIsCa(X509Certificate certificate) {
        boolean[] keyUsage = certificate.getKeyUsage();
        int basicConstraints = certificate.getBasicConstraints();

        if (keyUsage == null) {
            // no KeyUsage, just check if the cA BasicConstraint is set.
            return basicConstraints >= 0;
        } else {
            if (keyUsage[5] && basicConstraints == -1) {
                // KeyUsage is present and the keyCertSign bit is set.
                // According to RFC 5280 the BasicConstraint cA bit must also
                // be set, but it's not!
                logger.warn(
                        "'{}' violates RFC 5280: KeyUsage keyCertSign " + "bit set without BasicConstraint cA bit set",
                        certificate.getSubjectX500Principal().getName());
            }

            return keyUsage[5] || basicConstraints >= 0;
        }
    }

    private static boolean certificateIsSelfSigned(X509Certificate cert) throws UaException {
        try {
            // Verify certificate signature with its own public key
            PublicKey key = cert.getPublicKey();
            cert.verify(key);

            // Check that subject and issuer are the same
            return Objects.equals(cert.getSubjectX500Principal(), cert.getIssuerX500Principal());
        } catch (SignatureException | InvalidKeyException sigEx) {
            // Invalid signature or key: not self-signed
            return false;
        } catch (Exception e) {
            throw new UaException(StatusCodes.Bad_CertificateInvalid, e);
        }
    }

}
