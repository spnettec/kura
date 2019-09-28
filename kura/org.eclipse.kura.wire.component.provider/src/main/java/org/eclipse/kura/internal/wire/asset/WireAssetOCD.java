/*******************************************************************************
 * Copyright (c) 2018 Eurotech and/or its affiliates and others
 *
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 *******************************************************************************/

package org.eclipse.kura.internal.wire.asset;

import static org.eclipse.kura.asset.provider.AssetConstants.ASSET_DESC_PROP;
import static org.eclipse.kura.asset.provider.AssetConstants.ASSET_DRIVER_PROP;

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
import org.osgi.framework.FrameworkUtil;

public class WireAssetOCD extends BaseAssetOCD {

    private static final String EMIT_ALL_CHANNELS_DESCRIPTION = "Specifies wheter the values of all READ or READ_WRITE channels should be emitted in case of a channel event."
            + " If set to true, the values for all channels will be read and emitted,"
            + " if set to false, only the value for the channel related to the event will be emitted.";

    private static final String TIMESTAMP_MODE_DESCRIPTION = "If set to PER_CHANNEL, the component will emit a driver-generated timestamp per channel property."
            + " If set to SINGLE_ASSET_GENERATED, the component will emit a single timestamp per request, generated by the Asset itself before emitting the envelope. "
            + "If set to SINGLE_DRIVER_GENERATED_MAX or SINGLE_DRIVER_GENERATED_MIN, the component will emit a single driver generated timestamp being respectively"
            + " the max (most recent) or min (oldest) among the timestamps of the channels.";

    private static final String EMIT_ERRORS_DESCRIPTION = "Specifies wheter errors should be included or not in the emitted envelope";

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
            this.ad.clear();
            for (OCD ocd : meta.getOCD()) {
                setId(ocd.getId());
                setName(ocd.getName());
                setDescription(ocd.getDescription());
                for (AD ad : ocd.getAD())
                    this.ad.add((Tad) ad);
            }
        } else {
            setId(BaseAsset.CONF_PID);
            setName("Wire Asset");
            setDescription("Configure Wire Asset Instance");

            final Tad assetDescriptionAd = new Tad();
            assetDescriptionAd.setId(ASSET_DESC_PROP.value());
            assetDescriptionAd.setName(ASSET_DESC_PROP.value());
            assetDescriptionAd.setCardinality(0);
            assetDescriptionAd.setType(Tscalar.STRING);
            assetDescriptionAd.setDescription("Asset Description");
            assetDescriptionAd.setRequired(false);

            final Tad driverNameAd = new Tad();
            driverNameAd.setId(ASSET_DRIVER_PROP.value());
            driverNameAd.setName(ASSET_DRIVER_PROP.value());
            driverNameAd.setCardinality(0);
            driverNameAd.setType(Tscalar.STRING);
            driverNameAd.setDescription("Driver Name");
            driverNameAd.setRequired(true);

            addAD(assetDescriptionAd);
            addAD(driverNameAd);

            final Tad emitAllChannelsAd = new Tad();
            emitAllChannelsAd.setId(WireAssetOptions.EMIT_ALL_CHANNELS_PROP_NAME);
            emitAllChannelsAd.setName(WireAssetOptions.EMIT_ALL_CHANNELS_PROP_NAME);
            emitAllChannelsAd.setCardinality(0);
            emitAllChannelsAd.setType(Tscalar.BOOLEAN);
            emitAllChannelsAd.setDescription(EMIT_ALL_CHANNELS_DESCRIPTION);
            emitAllChannelsAd.setRequired(true);
            emitAllChannelsAd.setDefault("false");

            addAD(emitAllChannelsAd);

            final Tad emitmutipleThreadAd = new Tad();
            emitmutipleThreadAd.setId(WireAssetOptions.EMIT_MUTIPLE_THREAD_PROP_NAME);
            emitmutipleThreadAd.setName(WireAssetOptions.EMIT_MUTIPLE_THREAD_PROP_NAME);
            emitmutipleThreadAd.setCardinality(0);
            emitmutipleThreadAd.setType(Tscalar.BOOLEAN);
            emitmutipleThreadAd.setDescription("Is emit mutiple thread");
            emitmutipleThreadAd.setRequired(true);
            emitmutipleThreadAd.setDefault("false");

            addAD(emitmutipleThreadAd);

            final Tad emitThreadCountAd = new Tad();
            emitThreadCountAd.setId(WireAssetOptions.EMIT_THREAD_COUNT_PROP_NAME);
            emitThreadCountAd.setName(WireAssetOptions.EMIT_THREAD_COUNT_PROP_NAME);
            emitThreadCountAd.setCardinality(0);
            emitThreadCountAd.setType(Tscalar.INTEGER);
            emitThreadCountAd.setDescription("Emit thread Count");
            emitThreadCountAd.setRequired(true);
            emitThreadCountAd.setDefault("2");

            addAD(emitThreadCountAd);

            final Tad emitThreadTimeoutAd = new Tad();
            emitThreadTimeoutAd.setId(WireAssetOptions.EMIT_THREAD_TIMEOUT_PROP_NAME);
            emitThreadTimeoutAd.setName(WireAssetOptions.EMIT_THREAD_TIMEOUT_PROP_NAME);
            emitThreadTimeoutAd.setCardinality(0);
            emitThreadTimeoutAd.setType(Tscalar.INTEGER);
            emitThreadTimeoutAd.setDescription("Emit thread TimeOut (millisecond)");
            emitThreadTimeoutAd.setRequired(true);
            emitThreadTimeoutAd.setDefault("10000");

            addAD(emitThreadTimeoutAd);

            final Tad timestampModeAd = new Tad();
            timestampModeAd.setId(WireAssetOptions.TIMESTAMP_MODE_PROP_NAME);
            timestampModeAd.setName(WireAssetOptions.TIMESTAMP_MODE_PROP_NAME);
            timestampModeAd.setCardinality(0);
            timestampModeAd.setType(Tscalar.STRING);
            timestampModeAd.setDescription(TIMESTAMP_MODE_DESCRIPTION);
            timestampModeAd.setRequired(true);
            timestampModeAd.setDefault(TimestampMode.NO_TIMESTAMPS.name());

            addOptions(timestampModeAd, TimestampMode.values());

            addAD(timestampModeAd);

            final Tad emitErrorsAd = new Tad();
            emitErrorsAd.setId(WireAssetOptions.EMIT_ERRORS_PROP_NAME);
            emitErrorsAd.setName(WireAssetOptions.EMIT_ERRORS_PROP_NAME);
            emitErrorsAd.setCardinality(0);
            emitErrorsAd.setType(Tscalar.BOOLEAN);
            emitErrorsAd.setDescription(EMIT_ERRORS_DESCRIPTION);
            emitErrorsAd.setRequired(true);
            emitErrorsAd.setDefault("false");

            addAD(emitErrorsAd);
        }

    }

}
