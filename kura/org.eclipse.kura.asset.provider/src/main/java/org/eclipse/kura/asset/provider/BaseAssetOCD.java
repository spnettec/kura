/*******************************************************************************
 * Copyright (c) 2018, 2020 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.asset.provider;

import static org.eclipse.kura.asset.provider.AssetConstants.ASSET_DESC_PROP;
import static org.eclipse.kura.asset.provider.AssetConstants.ASSET_DRIVER_PROP;
import static org.eclipse.kura.asset.provider.AssetConstants.REQUEST_TIMEOUT_PROP;

import java.util.Collections;

import org.osgi.framework.FrameworkUtil;
import org.eclipse.kura.core.configuration.metatype.Tad;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.eclipse.kura.core.configuration.metatype.Tscalar;

public class BaseAssetOCD extends Tocd {

    public BaseAssetOCD() {
        setId("org.eclipse.kura.asset");
        setName("Asset");
        setDescription("Configure Asset instance");

        final Tad assetDescriptionAd = new Tad();
        assetDescriptionAd.setId(ASSET_DESC_PROP.value());
        assetDescriptionAd.setName("Asset description");
        assetDescriptionAd.setCardinality(0);
        assetDescriptionAd.setType(Tscalar.STRING);
        assetDescriptionAd.setDescription("Asset Description");
        assetDescriptionAd.setRequired(false);

        final Tad requestTimeoutAd = new Tad();
        requestTimeoutAd.setId(REQUEST_TIMEOUT_PROP.value());
        requestTimeoutAd.setName("Request timeout");
        requestTimeoutAd.setCardinality(0);
        requestTimeoutAd.setType(Tscalar.INTEGER);
        requestTimeoutAd.setDescription("Request timeout (in seconds)");
        requestTimeoutAd.setRequired(true);
        requestTimeoutAd.setDefault("10");

        final Tad driverNameAd = new Tad();
        driverNameAd.setId(ASSET_DRIVER_PROP.value());
        driverNameAd.setName("Driver PID");
        driverNameAd.setCardinality(0);
        driverNameAd.setType(Tscalar.STRING);
        driverNameAd.setDescription("Driver Name");
        driverNameAd.setRequired(true);

        final var bundle = FrameworkUtil.getBundle(BaseAssetOCD.class);
        final var resources = bundle == null ? null : bundle.findEntries("OSGI-INF/l10n", "*.properties", false);
        if (resources != null) {
            setLocalization("OSGI-INF/l10n/WireAsset");
            setLocaleUrls(Collections.list(resources).toArray(java.net.URL[]::new));
            setName("%baseAssetName");
            setDescription("%baseAssetDescription");
            assetDescriptionAd.setName("%assetdescname");
            assetDescriptionAd.setDescription("%assetdescdesc");
            requestTimeoutAd.setName("%requestTimeout");
            requestTimeoutAd.setDescription("%requestTimeoutDesc");
            driverNameAd.setName("%driverpidname");
            driverNameAd.setDescription("%driverpiddesc");
        }

        addAD(assetDescriptionAd);
        addAD(requestTimeoutAd);
        addAD(driverNameAd);
    }

}
