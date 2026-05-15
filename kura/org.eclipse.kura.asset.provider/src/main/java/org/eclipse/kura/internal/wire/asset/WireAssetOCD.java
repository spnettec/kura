/*******************************************************************************
 * Copyright (c) 2018, 2024 Eurotech and/or its affiliates and others
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

package org.eclipse.kura.internal.wire.asset;

import static org.eclipse.kura.asset.provider.AssetConstants.ASSET_DESC_PROP;
import static org.eclipse.kura.asset.provider.AssetConstants.ASSET_DRIVER_PROP;

import java.net.URL;
import java.util.Collections;
import java.util.Enumeration;
import java.util.List;

import org.eclipse.kura.asset.provider.BaseAsset;
import org.eclipse.kura.asset.provider.BaseAssetOCD;
import org.eclipse.kura.configuration.metatype.AD;
import org.eclipse.kura.configuration.metatype.OCD;
import org.eclipse.kura.configuration.metatype.Option;
import org.eclipse.kura.core.configuration.metatype.Tad;
import org.eclipse.kura.core.configuration.metatype.Tmetadata;
import org.eclipse.kura.core.configuration.metatype.Toption;
import org.eclipse.kura.core.configuration.metatype.Tscalar;
import org.eclipse.kura.core.configuration.util.ComponentUtil;
import org.osgi.framework.Bundle;
import org.osgi.framework.FrameworkUtil;

public class WireAssetOCD extends BaseAssetOCD {

    private static final String FALSE = "false";

    private static void addOptions(Tad target, Enum<?>[] values) {
        final List<Option> options = target.getOption();
        for (Enum<?> value : values) {
            final String name = value.name();
            final Toption option = new Toption();
            option.setLabel(name);
            option.setValue(name);
            options.add(option);
        }
    }

    public WireAssetOCD() {
        Tmetadata meta = null;
        try {
            meta = ComponentUtil.readMetadata(FrameworkUtil.getBundle(this.getClass()),
                    WireAssetConstants.CONF_PID.value());
        } catch (Exception e) {

        }
        if (meta != null) {
            this.localization = meta.getLocalization();
            this.localeUrls = meta.getLocaleUrls();
            this.ad.clear();
            for (OCD ocd : meta.getOCD()) {
                setId(ocd.getId());
                setName(ocd.getName());
                setDescription(ocd.getDescription());
                for (AD ad : ocd.getAD()) {
                    this.ad.add((Tad) ad);
                }
            }
        } else {
            setId(BaseAsset.CONF_PID);
            setName("%name");
            setDescription("%description");
            setLocalization("OSGI-INF/l10n/WireAsset");
            final Bundle bundle = FrameworkUtil.getBundle(this.getClass());
            if (bundle != null) {
                final Enumeration<URL> entries = bundle.findEntries("OSGI-INF/l10n", "*.properties", false);
                if (entries != null) {
                    final List<URL> urlList = Collections.list(entries);
                    setLocaleUrls(urlList.toArray(new URL[0]));
                }
            }

            // asset.desc and driver.pid are already added by BaseAssetOCD super-ctor
            // with hardcoded English labels; re-point their name/description to the
            // bundle's l10n keys so the active locale resolves them.
            for (final AD ad : this.ad) {
                final Tad tad = (Tad) ad;
                if (ASSET_DESC_PROP.value().equals(tad.getId())) {
                    tad.setName("%assetdescname");
                    tad.setDescription("%assetdescdesc");
                } else if (ASSET_DRIVER_PROP.value().equals(tad.getId())) {
                    tad.setName("%driverpidname");
                    tad.setDescription("%driverpiddesc");
                }
            }

            final Tad emitAllChannelsAd = new Tad();
            emitAllChannelsAd.setId(WireAssetOptions.EMIT_ALL_CHANNELS_PROP_NAME);
            emitAllChannelsAd.setName("%emitallchannelsname");
            emitAllChannelsAd.setCardinality(0);
            emitAllChannelsAd.setType(Tscalar.BOOLEAN);
            emitAllChannelsAd.setDescription("%emitallchannelsdesc");
            emitAllChannelsAd.setRequired(true);
            emitAllChannelsAd.setDefault(FALSE);

            addAD(emitAllChannelsAd);

            final Tad timestampModeAd = new Tad();
            timestampModeAd.setId(WireAssetOptions.TIMESTAMP_MODE_PROP_NAME);
            timestampModeAd.setName("%timestampmodename");
            timestampModeAd.setCardinality(0);
            timestampModeAd.setType(Tscalar.STRING);
            timestampModeAd.setDescription("%timestampmodedesc");
            timestampModeAd.setRequired(true);
            timestampModeAd.setDefault(TimestampMode.PER_CHANNEL.name());

            addOptions(timestampModeAd, TimestampMode.values());

            addAD(timestampModeAd);

            final Tad emitErrorsAd = new Tad();
            emitErrorsAd.setId(WireAssetOptions.EMIT_ERRORS_PROP_NAME);
            emitErrorsAd.setName("%emiterrorsname");
            emitErrorsAd.setCardinality(0);
            emitErrorsAd.setType(Tscalar.BOOLEAN);
            emitErrorsAd.setDescription("%emiterrorsdesc");
            emitErrorsAd.setRequired(true);
            emitErrorsAd.setDefault(FALSE);

            addAD(emitErrorsAd);

            final Tad emitConnectionErrorsAd = new Tad();
            emitConnectionErrorsAd.setId(WireAssetOptions.EMIT_CONNECTION_ERRORS_PROP_NAME);
            emitConnectionErrorsAd.setName("%emitconnectionerrors");
            emitConnectionErrorsAd.setCardinality(0);
            emitConnectionErrorsAd.setType(Tscalar.BOOLEAN);
            emitConnectionErrorsAd.setDescription("%emitconnectionerrorsDesc");
            emitConnectionErrorsAd.setRequired(true);
            emitConnectionErrorsAd.setDefault(FALSE);

            addAD(emitConnectionErrorsAd);

            final Tad emitOnChangeAd = new Tad();
            emitOnChangeAd.setId(WireAssetOptions.EMIT_ON_CHANGE_PROP_NAME);
            emitOnChangeAd.setName("%emitonchange");
            emitOnChangeAd.setCardinality(0);
            emitOnChangeAd.setType(Tscalar.BOOLEAN);
            emitOnChangeAd.setDescription("%emitonchangedesc");
            emitOnChangeAd.setRequired(true);
            emitOnChangeAd.setDefault(FALSE);

            addAD(emitOnChangeAd);

            final Tad emitEmptyEnvelopesAd = new Tad();
            emitEmptyEnvelopesAd.setId(WireAssetOptions.EMIT_EMPTY_ENVELOPES_PROP_NAME);
            emitEmptyEnvelopesAd.setName("%emitemptyenvelopes");
            emitEmptyEnvelopesAd.setCardinality(0);
            emitEmptyEnvelopesAd.setType(Tscalar.BOOLEAN);
            emitEmptyEnvelopesAd.setDescription("%emitemptyenvelopesdesc");
            emitEmptyEnvelopesAd.setRequired(true);
            emitEmptyEnvelopesAd.setDefault("true");

            addAD(emitEmptyEnvelopesAd);
        }

    }

}
