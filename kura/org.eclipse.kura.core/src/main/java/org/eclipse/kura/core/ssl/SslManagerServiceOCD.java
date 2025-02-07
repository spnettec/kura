/*******************************************************************************
 * Copyright (c) 2025 Eurotech and/or its affiliates and others
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

import org.osgi.service.metatype.annotations.AttributeDefinition;
import org.osgi.service.metatype.annotations.Icon;
import org.osgi.service.metatype.annotations.ObjectClassDefinition;
import org.osgi.service.metatype.annotations.Option;

@ObjectClassDefinition(id = "org.eclipse.kura.ssl.SslManagerService", //
        name = "%name", //
        description = "%description", //
        icon = @Icon(resource = "SslManagerService", size = 32), //
        localization = "OSGI-INF/l10n/SslManagerService" //
)
@interface SslManagerServiceOCD {

    @AttributeDefinition(name = "%protocol", //
            required = false, //
            defaultValue = "TLSv1.2", //
            description = "%protocolDesc")
    String ssl_default_protocol();

    @AttributeDefinition(name = "%verification", //
            required = false, //
            defaultValue = "true", //
            description = "%verificationDesc")
    boolean ssl_hostname_verification();

    @AttributeDefinition(name = "%keystoreTargetFilter", //
            defaultValue = "(kura.service.pid=changeme)", //
            description = "%keystoreTargetFilterDesc")
    String KeystoreService_target();

    @AttributeDefinition(name = "%truststoreTargetFilter", //
            defaultValue = "(kura.service.pid=changeme)", //
            description = "%truststoreTargetFilterDesc")
    String TruststoreKeystoreService_target();

    @AttributeDefinition(name = "%cipherSuites", //
            required = false, //
            description = "%cipherSuitesDesc")
    String ssl_default_cipherSuites();

    @AttributeDefinition(name = "%revCheckEnabled", //
            required = false, //
            defaultValue = "false", //
            description = "%revCheckEnabledDesc")
    boolean ssl_revocation_check_enabled();

    @AttributeDefinition(name = "%revCheckMode", //
            defaultValue = "PREFER_OCSP", //
            description = "%revCheckModeDesc", //
            options = { @Option(label = "%revModPreOcsp", value = "PREFER_OCSP"), //
                    @Option(label = "%revModPreCrl", value = "PREFER_CRL"), //
                    @Option(label = "%revModCrlOnly", value = "CRL_ONLY") //
            })
    String ssl_revocation_mode();

    @AttributeDefinition(name = "%revSoftEnabled", //
            defaultValue = "false", //
            description = "%revSoftEnabledDesc")
    boolean ssl_revocation_soft_fail();

}
