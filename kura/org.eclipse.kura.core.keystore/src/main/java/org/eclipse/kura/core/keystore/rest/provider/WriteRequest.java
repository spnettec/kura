/*******************************************************************************
 * Copyright (c) 2021 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.core.keystore.rest.provider;

import org.eclipse.kura.core.keystore.util.EntryType;
import org.eclipse.kura.rest.utils.Validable;

public class WriteRequest implements Validable {

    private String keystoreName;
    private String alias;
    private String type;
    private String privateKey;
    private String[] certificateChain;
    private String certificate;
    private String algorithm;
    private String signatureAlgorithm;
    private String attributes;
    private int size;

    public String getKeystoreName() {
        return this.keystoreName;
    }

    public String getAlias() {
        return this.alias;
    }

    public String getType() {
        return this.type;
    }

    public String getPrivateKey() {
        return this.privateKey;
    }

    public String[] getCertificateChain() {
        return this.certificateChain;
    }

    public String getCertificate() {
        return this.certificate;
    }

    public String getAlgorithm() {
        return this.algorithm;
    }

    public String getSignatureAlgorithm() {
        return this.signatureAlgorithm;
    }

    public int getSize() {
        return this.size;
    }

    public String getAttributes() {
        return this.attributes;
    }

    @Override
    public String toString() {
        return "WriteRequest [keystoreName=" + this.keystoreName + ", alias=" + this.alias + ", type=" + this.type
                + "]";
    }

    @Override
    public boolean isValid() {
        if (this.keystoreName == null || this.alias == null || this.type == null) {
            return false;
        }
        if (EntryType.valueOfType(this.type) != EntryType.TRUSTED_CERTIFICATE
                && EntryType.valueOfType(this.type) != EntryType.KEY_PAIR) {
            return false;
        }
        if (EntryType.valueOfType(this.type) == EntryType.TRUSTED_CERTIFICATE && certificate == null) {
            return false;
        }
        return !(EntryType.valueOfType(this.type) == EntryType.KEY_PAIR && (this.algorithm == null || this.size == 0
                || this.signatureAlgorithm == null || this.attributes == null));
    }

}
