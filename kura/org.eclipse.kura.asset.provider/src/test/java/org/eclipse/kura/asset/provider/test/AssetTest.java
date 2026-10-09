/*******************************************************************************
 * Copyright (c) 2016, 2024 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.asset.provider.test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;
import static org.mockito.Mockito.*;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import org.eclipse.kura.KuraException;
import org.eclipse.kura.asset.Asset;
import org.eclipse.kura.asset.AssetConfiguration;
import org.eclipse.kura.asset.provider.AssetConstants;
import org.eclipse.kura.asset.provider.BaseAsset;
import org.eclipse.kura.asset.provider.BaseAssetExecutor;
import org.eclipse.kura.channel.Channel;
import org.eclipse.kura.channel.ChannelFlag;
import org.eclipse.kura.channel.ChannelRecord;
import org.eclipse.kura.channel.ChannelType;
import org.eclipse.kura.channel.ScaleOffsetType;
import org.eclipse.kura.channel.listener.ChannelListener;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.metatype.AD;
import org.eclipse.kura.configuration.metatype.OCD;
import org.eclipse.kura.driver.Driver;
import org.eclipse.kura.type.DataType;
import org.eclipse.kura.type.TypedValues;
import org.eclipse.kura.util.collection.CollectionUtil;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.osgi.framework.BundleContext;
import org.osgi.service.component.ComponentContext;
import org.junit.jupiter.api.Test;

/**
 * This AssetTest is responsible to test {@link Asset}
 */
public final class AssetTest {

    private static final String UNREGISTER_CHANNEL_NAME = "unregister";

    private final StubDriver driver = new StubDriver();
    private final FixtureAsset asset = new FixtureAsset();
    private final ComponentContext context = mock(ComponentContext.class);

    @BeforeEach
    void startAsset() {
        when(this.context.getBundleContext()).thenReturn(mock(BundleContext.class));
        this.asset.start();
        resetChannels();
    }

    @AfterEach
    void stopAsset() throws Exception {
        try {
            this.asset.unsetDriver();
            sync(this.asset);
        } finally {
            this.asset.stop();
            assertTrue(this.asset.io.awaitTermination(5, TimeUnit.SECONDS), "Asset IO executor must terminate");
            assertTrue(this.asset.configuration.awaitTermination(5, TimeUnit.SECONDS),
                    "Asset configuration executor must terminate");
        }
    }

    /**
     * Initializes asset data
     */
    private void resetChannels() {
        final Map<String, Object> channels = CollectionUtil.newHashMap();

        channels.put("kura.service.pid", "AssetTest");

        channels.put(AssetConstants.ASSET_DESC_PROP.value(), "sample.asset.desc");
        channels.put(AssetConstants.ASSET_DRIVER_PROP.value(), "org.eclipse.kura.asset.stub.driver");
        channels.put("1.CH#+name", "1.CH");
        channels.put("1.CH#+type", "READ");
        channels.put("1.CH#+value.type", DataType.INTEGER.name());
        channels.put("1.CH#+scaleoffset.type", ScaleOffsetType.DEFINED_BY_VALUE_TYPE.name());
        channels.put("1.CH#+scale", "1");
        channels.put("1.CH#+offset", "0");
        channels.put("1.CH#DRIVER.modbus.register", "sample.channel1.modbus.register");
        channels.put("1.CH#DRIVER.modbus.FC", "sample.channel1.modbus.FC");

        channels.put("2.CH#+name", "2.CH");
        channels.put("2.CH#+enabled", "true");
        channels.put("2.CH#+type", "WRITE");
        channels.put("2.CH#+value.type", DataType.BOOLEAN.name());
        channels.put("2.CH#DRIVER.modbus.register", "sample.channel2.modbus.register");
        channels.put("2.CH#DRIVER.modbus.DUMMY.NN", "sample.channel2.modbus.FC");

        channels.put("3.CH#+name", "3.CH");
        channels.put("3.CH#+type", "READ");
        channels.put("3.CH#+enabled", "false");
        channels.put("3.CH#+value.type", DataType.INTEGER.name());
        channels.put("3.CH#+scaleoffset.type", ScaleOffsetType.DEFINED_BY_VALUE_TYPE.name());
        channels.put("3.CH#DRIVER.modbus.register", "sample.channel1.modbus.register");
        channels.put("3.CH#DRIVER.modbus.FC", "sample.channel1.modbus.FC");

        channels.put("4.CH#+name", "4.CH");
        channels.put("4.CH#+enabled", "false");
        channels.put("4.CH#+type", "WRITE");
        channels.put("4.CH#+value.type", DataType.BOOLEAN.name());
        channels.put("4.CH#DRIVER.modbus.register", "sample.channel2.modbus.register");
        channels.put("4.CH#DRIVER.modbus.DUMMY.NN", "sample.channel2.modbus.FC");

        channels.put("5.CH#+name", "5.CH");
        channels.put("5.CH#+enabled", "true");
        channels.put("5.CH#+type", "READ");
        channels.put("5.CH#+value.type", DataType.INTEGER.name());
        channels.put("5.CH#+scaleoffset.type", ScaleOffsetType.DOUBLE.name());
        channels.put("5.CH#+scale", "3.3");
        channels.put("5.CH#+offset", "3.2");
        channels.put("5.CH#DRIVER.modbus.register", "sample.channel2.modbus.register");
        channels.put("5.CH#DRIVER.modbus.DUMMY.NN", "sample.channel2.modbus.FC");

        channels.put("6.CH#+name", "6.CH");
        channels.put("6.CH#+enabled", "true");
        channels.put("6.CH#+type", "READ");
        channels.put("6.CH#+value.type", DataType.INTEGER.name());
        channels.put("6.CH#+scaleoffset.type", ScaleOffsetType.DEFINED_BY_VALUE_TYPE.name());
        channels.put("6.CH#+scale", "3");
        channels.put("6.CH#+offset", "4");
        channels.put("6.CH#DRIVER.modbus.register", "sample.channel2.modbus.register");
        channels.put("6.CH#DRIVER.modbus.DUMMY.NN", "sample.channel2.modbus.FC");

        channels.put("7.CH#+name", "7.CH");
        channels.put("7.CH#+enabled", "true");
        channels.put("7.CH#+type", "READ");
        channels.put("7.CH#+value.type", DataType.INTEGER.name());
        channels.put("7.CH#+scaleoffset.type", ScaleOffsetType.INTEGER.name());
        channels.put("7.CH#+scale", "3");
        channels.put("7.CH#+offset", "4");
        channels.put("7.CH#DRIVER.modbus.register", "sample.channel2.modbus.register");
        channels.put("7.CH#DRIVER.modbus.DUMMY.NN", "sample.channel2.modbus.FC");

        channels.put("8.CH#+name", "8.CH");
        channels.put("8.CH#+enabled", "true");
        channels.put("8.CH#+type", "READ");
        channels.put("8.CH#+value.type", DataType.INTEGER.name());
        channels.put("8.CH#+scaleoffset.type", ScaleOffsetType.LONG.name());
        channels.put("8.CH#+scale", "3");
        channels.put("8.CH#+offset", "4");
        channels.put("8.CH#DRIVER.modbus.register", "sample.channel2.modbus.register");
        channels.put("8.CH#DRIVER.modbus.DUMMY.NN", "sample.channel2.modbus.FC");

        channels.put("9.CH#+name", "9.CH");
        channels.put("9.CH#+enabled", "true");
        channels.put("9.CH#+type", "READ");
        channels.put("9.CH#+value.type", DataType.INTEGER.name());
        channels.put("9.CH#+scaleoffset.type", ScaleOffsetType.FLOAT.name());
        channels.put("9.CH#+scale", "3");
        channels.put("9.CH#+offset", "4");
        channels.put("9.CH#DRIVER.modbus.register", "sample.channel2.modbus.register");
        channels.put("9.CH#DRIVER.modbus.DUMMY.NN", "sample.channel2.modbus.FC");

        channels.put("11.CH#+name", "11.CH");
        channels.put("11.CH#+enabled", "true");
        channels.put("11.CH#+type", "READ");
        channels.put("11.CH#+value.type", DataType.LONG.name());
        channels.put("11.CH#+scaleoffset.type", ScaleOffsetType.DEFINED_BY_VALUE_TYPE.name());
        channels.put("11.CH#+scale", "3");
        channels.put("11.CH#+offset", "4");
        channels.put("11.CH#DRIVER.modbus.register", "sample.channel2.modbus.register");
        channels.put("11.CH#DRIVER.modbus.DUMMY.NN", "sample.channel2.modbus.FC");

        channels.put("12.CH#+name", "12.CH");
        channels.put("12.CH#+enabled", "true");
        channels.put("12.CH#+type", "READ");
        channels.put("12.CH#+value.type", DataType.FLOAT.name());
        channels.put("12.CH#+scaleoffset.type", ScaleOffsetType.DEFINED_BY_VALUE_TYPE.name());
        channels.put("12.CH#+scale", "3.3");
        channels.put("12.CH#+offset", "4.7");
        channels.put("12.CH#DRIVER.modbus.register", "sample.channel2.modbus.register");
        channels.put("12.CH#DRIVER.modbus.DUMMY.NN", "sample.channel2.modbus.FC");

        channels.put("13.CH#+name", "13.CH");
        channels.put("13.CH#+enabled", "true");
        channels.put("13.CH#+type", "READ");
        channels.put("13.CH#+value.type", DataType.DOUBLE.name());
        channels.put("13.CH#+scaleoffset.type", ScaleOffsetType.DEFINED_BY_VALUE_TYPE.name());
        channels.put("13.CH#+scale", "3.4");
        channels.put("13.CH#+offset", "4.3");
        channels.put("13.CH#DRIVER.modbus.register", "sample.channel2.modbus.register");
        channels.put("13.CH#DRIVER.modbus.DUMMY.NN", "sample.channel2.modbus.FC");

        ((BaseAsset) asset).updated(channels);
        sync(asset);
    }

    /**
     * Test generic asset properties.
     */
    @Test
    public void testBasicProperties() {
        final AssetConfiguration assetConfiguration = asset.getAssetConfiguration();
        assertNotNull(assetConfiguration);
        assertEquals("org.eclipse.kura.asset.stub.driver", assetConfiguration.getDriverPid());
        assertEquals("sample.asset.desc", assetConfiguration.getAssetDescription());
    }

    /**
     * Test sample channel properties.
     */
    @Test
    public void testChannelProperties() {
        final AssetConfiguration assetConfiguration = asset.getAssetConfiguration();
        assertNotNull(assetConfiguration);
        final Map<String, Channel> channels = assetConfiguration.getAssetChannels();
        assertEquals(12, channels.size());

        final Channel channel1 = channels.get("1.CH");
        assertTrue(channel1.isEnabled());
        assertEquals("1.CH", channel1.getName());
        assertEquals(ChannelType.READ, channel1.getType());
        assertEquals(DataType.INTEGER, channel1.getValueType());
        assertEquals(1, channel1.getValueScaleAsNumber());
        assertEquals(0, channel1.getValueOffsetAsNumber());
        assertEquals("sample.channel1.modbus.register", channel1.getConfiguration().get("DRIVER.modbus.register"));
        assertEquals("sample.channel1.modbus.FC", channel1.getConfiguration().get("DRIVER.modbus.FC"));

        final Channel channel2 = channels.get("2.CH");
        assertTrue(channel2.isEnabled());
        assertEquals("2.CH", channel2.getName());
        assertEquals(ChannelType.WRITE, channel2.getType());
        assertEquals(DataType.BOOLEAN, channel2.getValueType());
        assertEquals("sample.channel2.modbus.register", channel2.getConfiguration().get("DRIVER.modbus.register"));
        assertEquals("sample.channel2.modbus.FC", channel2.getConfiguration().get("DRIVER.modbus.DUMMY.NN"));
    }

    /**
     * Test listening operation.
     */
    @Test
    public void testListen() throws KuraException {

        AtomicBoolean invoked = new AtomicBoolean(false);

        final ChannelListener listener = event -> {
            if (event.getChannelRecord().getValue() != null) {
                assertEquals(1, event.getChannelRecord().getValue().getValue());
            }

            invoked.set(true);
        };

        asset.registerChannelListener("1.CH", listener);
        sync(asset);

        assertTrue(invoked.get());
    }

    /**
     * Listeners should be removed from the driver when it is detached from the asset and added when it is attached.
     */
    @Test
    public void testListenerAttachOnDriverChange() throws KuraException {
        final Driver driver = ((BaseAsset) asset).getDriver();

        final ArrayList<Boolean> attachSequence = new ArrayList<>();

        final ChannelListener listener = event -> {
            boolean toBeAttached = !UNREGISTER_CHANNEL_NAME.equals(event.getChannelRecord().getChannelName());
            attachSequence.add(toBeAttached);
        };

        asset.registerChannelListener("1.CH", listener);
        sync(asset);
        assertEquals(Arrays.asList(true), attachSequence);

        ((BaseAsset) asset).unsetDriver();
        sync(asset);
        assertEquals(Arrays.asList(true, false), attachSequence);

        ((BaseAsset) asset).setDriver(driver);
        sync(asset);
        assertEquals(Arrays.asList(true, false, true), attachSequence);
    }

    /**
     * It should be possible to add listeners to an asset even if the driver is not attached, the asset should attach
     * them later on when the driver is tracked
     */
    @Test
    public void testAttachListenerWhitoutDriver() throws KuraException {
        final Driver driver = ((BaseAsset) asset).getDriver();

        final ArrayList<Boolean> attachSequence = new ArrayList<>();

        final ChannelListener listener = event -> {
            boolean toBeAttached = !UNREGISTER_CHANNEL_NAME.equals(event.getChannelRecord().getChannelName());
            attachSequence.add(toBeAttached);
        };

        ((BaseAsset) asset).unsetDriver();
        sync(asset);

        asset.registerChannelListener("1.CH", listener);
        sync(asset);
        assertEquals(Arrays.asList(), attachSequence);

        asset.registerChannelListener("1.CH", listener);
        sync(asset);
        assertEquals(Arrays.asList(), attachSequence);

        ((BaseAsset) asset).setDriver(driver);
        sync(asset);
        assertEquals(Arrays.asList(true), attachSequence);
    }

    /**
     * The same channel listener should not be attached multiple times.
     */
    @Test
    public void testShouldNotReattachSameListener() throws KuraException {

        final ArrayList<Boolean> attachSequence = new ArrayList<>();

        final ChannelListener listener = event -> {
            boolean toBeAttached = !UNREGISTER_CHANNEL_NAME.equals(event.getChannelRecord().getChannelName());
            attachSequence.add(toBeAttached);
        };

        asset.registerChannelListener("1.CH", listener);
        sync(asset);
        assertEquals(Arrays.asList(true), attachSequence);

        asset.registerChannelListener("1.CH", listener);
        sync(asset);
        assertEquals(Arrays.asList(true), attachSequence);

        asset.registerChannelListener("1.CH", listener);
        sync(asset);
        assertEquals(Arrays.asList(true), attachSequence);

        asset.registerChannelListener("1.CH", listener);
        sync(asset);
        assertEquals(Arrays.asList(true), attachSequence);
    }

    /**
     * Test listener unregistration.
     */
    @Test
    public void testUnlisten() throws KuraException {
        AtomicInteger invoked = new AtomicInteger(0);

        final ChannelListener listener = event -> {
            int cnt = invoked.getAndIncrement();

            if (cnt == 0) {
                assertEquals(1, event.getChannelRecord().getValue().getValue());
            } else if (cnt == 1) {
                assertEquals(UNREGISTER_CHANNEL_NAME, event.getChannelRecord().getChannelName());
                assertEquals(DataType.BOOLEAN, event.getChannelRecord().getValueType());
            } else {
                fail("Unexpected invocation.");
            }
        };

        asset.registerChannelListener("1.CH", listener);
        sync(asset);

        assertEquals(1, invoked.get());

        asset.unregisterChannelListener(listener);
        sync(asset);

        assertEquals(2, invoked.get());
    }

    /**
     * Test exception during listener unregistration.
     */
    @Test
    public void testUnlistenDriverException() throws KuraException {
        AtomicInteger invoked = new AtomicInteger(0);
        AtomicBoolean disableListener = new AtomicBoolean(false);

        final ChannelListener listener = event -> {
            if (disableListener.get()) {
                return;
            }

            int cnt = invoked.getAndIncrement();

            if (cnt == 0) {
                assertEquals(1, event.getChannelRecord().getValue().getValue());
            } else if (cnt == 1) {
                throw new IllegalArgumentException("test");
            } else {
                fail("Unexpected invocation.");
            }
        };

        asset.registerChannelListener("1.CH", listener);
        sync(asset);

        assertEquals(1, invoked.get());

        asset.unregisterChannelListener(listener);
        sync(asset);

        assertEquals(2, invoked.get());

        disableListener.set(true);
    }

    /**
     * Test reading operation.
     */
    @Test
    public void testRead() throws KuraException {
        final List<ChannelRecord> records = asset.read(new HashSet<>(Arrays.asList("1.CH")));

        assertNotNull(records);
        assertEquals(1, records.size());
        assertEquals(1, records.get(0).getValue().getValue());
    }

    /**
     * Tests the condition in case the channel type is not readable
     */
    @Test
    public void testReadChannelNotReadable() throws KuraException {
        List<ChannelRecord> result = asset.read(new HashSet<>(Arrays.asList("2.CH")));

        assertNotNull(result);
        assertEquals(1, result.size());
        assertEquals(ChannelFlag.FAILURE, result.get(0).getChannelStatus().getChannelFlag());
    }

    /**
     * Test reading operation on all channels.
     */
    @Test
    public void testReadAllChannels() throws KuraException {
        final List<ChannelRecord> records = asset.readAllChannels();

        assertNotNull(records);
        assertEquals(9, records.size());
        assertEquals(7, records.stream().filter(r -> "6.CH".equals(r.getChannelName()))
                .findFirst().orElseThrow().getValue().getValue());
    }

    /**
     * Test writing operation.
     */
    @Test
    public void testWrite() throws KuraException {
        ChannelRecord channelRecord = ChannelRecord.createWriteRecord("2.CH", TypedValues.newBooleanValue(true));

        List<ChannelRecord> records = new ArrayList<>();
        records.add(channelRecord);
        assertEquals(1, records.size());

        asset.write(records);

        assertEquals(ChannelFlag.SUCCESS, channelRecord.getChannelStatus().getChannelFlag());
    }

    /**
     * Tests the condition in case the channel type is not writable
     */
    @Test
    public void testWriteChannelNotWritable() throws KuraException {
        ChannelRecord channelRecord = ChannelRecord.createWriteRecord("1.CH", TypedValues.newLongValue(1L));

        List<ChannelRecord> list = Arrays.asList(channelRecord);
        assertEquals(1, list.size());

        asset.write(list);

        assertEquals(ChannelFlag.FAILURE, channelRecord.getChannelStatus().getChannelFlag());
    }

    @Test
    public void testGetConfiguration() throws KuraException {

        ComponentConfiguration cfg = ((BaseAsset) asset).getConfiguration();

        assertEquals("AssetTest", cfg.getPid());

        OCD ocd = cfg.getDefinition();
        assertEquals("org.eclipse.kura.asset", ocd.getId());
        assertTrue("Wire Asset".equals(ocd.getName()) || "AssetMessages.ocdName".equals(ocd.getName()));

        List<AD> ads = ocd.getAD();
        assertNotNull(ads);
        assertEquals(123, ads.size()); // Three local asset fields plus ten fields for each of 12 channels.

        assertEquals("asset.desc", ads.get(0).getId());
        assertEquals("request.timeout", ads.get(1).getId());
        assertEquals("driver.pid", ads.get(2).getId());

        String[] expectedValues = { "#+enabled", "#+name", "#+type", "#+value.type", "#+scale", "#+offset", "#+desc", "#+unit", "#+scaleoffset.type",
                "#unit.id" };

        final int expectedChannelCount = 4;
        for (String expectedValue : expectedValues) {
            for (int j = 0; j < expectedChannelCount; j++) {
                final String id = j + 1 + ".CH" + expectedValue;
                assertEquals(1, ads.parallelStream().filter(ad -> ad.getId().equals(id)).count());
            }
        }
    }

    /**
     * Tests reading disabled channel
     */
    @Test
    public void testReadChannelDisabled() throws KuraException {
        List<ChannelRecord> result = asset.read(new HashSet<>(Arrays.asList("3.CH")));

        assertNotNull(result);
        assertEquals(1, result.size());
        assertEquals(ChannelFlag.FAILURE, result.get(0).getChannelStatus().getChannelFlag());
    }

    /**
     * Tests writing disabled channel
     */
    @Test
    public void testWriteChannelDisabled() throws KuraException {
        ChannelRecord channelRecord = ChannelRecord.createWriteRecord("4.CH", TypedValues.newLongValue(1L));

        List<ChannelRecord> list = Arrays.asList(channelRecord);
        assertEquals(1, list.size());

        asset.write(list);

        assertEquals(ChannelFlag.FAILURE, channelRecord.getChannelStatus().getChannelFlag());
    }

    /**
     * It should be possible to attach listeners on disabled channels, but listener should not be forwarded to the
     * driver in this case driver
     */
    @Test
    public void testListenerAttachOnDisabledChannel() throws KuraException {
        final ArrayList<Boolean> attachSequence = new ArrayList<>();

        final ChannelListener listener = event -> {
            boolean toBeAttached = !UNREGISTER_CHANNEL_NAME.equals(event.getChannelRecord().getChannelName());
            attachSequence.add(toBeAttached);
        };

        asset.registerChannelListener("3.CH", listener);
        sync(asset);
        assertEquals(Arrays.asList(), attachSequence);
    }

    /**
     * Listeners attached to a channel should be detached from the driver if the channel is disabled and reattached if
     * the channel is enabled again
     */
    @Test
    public void testEnableDisableChannelWithListener() throws KuraException {
        final ArrayList<Boolean> attachSequence = new ArrayList<>();

        final Map<String, Object> channels = CollectionUtil.newHashMap();
        channels.put("kura.service.pid", "AssetTest");
        channels.put(AssetConstants.ASSET_DESC_PROP.value(), "sample.asset.desc");
        channels.put(AssetConstants.ASSET_DRIVER_PROP.value(), "org.eclipse.kura.asset.stub.driver");
        channels.put("3.CH#+name", "3.CH");
        channels.put("3.CH#+type", "READ");
        channels.put("3.CH#+enabled", "false");
        channels.put("3.CH#+value.type", "INTEGER");
        channels.put("3.CH#DRIVER.modbus.register", "sample.channel1.modbus.register");
        channels.put("3.CH#DRIVER.modbus.FC", "sample.channel1.modbus.FC");

        ((BaseAsset) asset).updated(channels);
        sync(asset);

        final ChannelListener listener = event -> {
            boolean toBeAttached = !UNREGISTER_CHANNEL_NAME.equals(event.getChannelRecord().getChannelName());
            attachSequence.add(toBeAttached);
        };

        asset.registerChannelListener("3.CH", listener);
        sync(asset);
        assertEquals(Arrays.asList(), attachSequence);

        channels.put("3.CH#+enabled", "true");
        ((BaseAsset) asset).updated(channels);
        sync(asset);

        assertEquals(Arrays.asList(true), attachSequence);

        channels.put("3.CH#+enabled", "false");

        ((BaseAsset) asset).updated(channels);
        sync(asset);

        assertEquals(Arrays.asList(true, false), attachSequence);

    }

    /**
     * Listeners attached to a channel should be detached from the driver if the channel is disabled and reattached if
     * the channel is enabled again
     */
    @Test
    public void testCompleteConfigWithDefaults() {

        final Map<String, Object> channels = CollectionUtil.newHashMap();
        channels.put("kura.service.pid", "AssetTest");
        channels.put(AssetConstants.ASSET_DESC_PROP.value(), "sample.asset.desc");
        channels.put(AssetConstants.ASSET_DRIVER_PROP.value(), "non.existing.pid");
        channels.put("3.CH#+name", "3.CH");
        channels.put("3.CH#+type", "READ");
        channels.put("3.CH#+enabled", "false");
        channels.put("3.CH#+value.type", "INTEGER");

        ((BaseAsset) asset).updated(channels);
        sync(asset);

        assertFalse(
                asset.getAssetConfiguration().getAssetChannels().get("3.CH").getConfiguration().containsKey("unit.id"));

        channels.put(AssetConstants.ASSET_DRIVER_PROP.value(), "org.eclipse.kura.asset.stub.driver");

        ((BaseAsset) asset).updated(channels);
        sync(asset);

        assertEquals("5",
                asset.getAssetConfiguration().getAssetChannels().get("3.CH").getConfiguration().get("unit.id"));

    }

    @Test
    public void testChannelRecordValueTypeWithDoubleScaleOffset() throws KuraException {

        List<ChannelRecord> records = asset.read(new HashSet<>(Arrays.asList("5.CH")));

        assertEquals(DataType.DOUBLE, records.get(0).getValueType());

    }

    @Test
    public void testChannelRecordValueTypeWithIntegerScaleOffset() throws KuraException {

        List<ChannelRecord> records = asset.read(new HashSet<>(Arrays.asList("7.CH")));

        assertEquals(DataType.INTEGER, records.get(0).getValueType());
    }

    @Test
    public void testChannelRecordValueTypeWithLongScaleOffset() throws KuraException {

        List<ChannelRecord> records = asset.read(new HashSet<>(Arrays.asList("8.CH")));

        assertEquals(DataType.LONG, records.get(0).getValueType());
    }

    @Test
    public void testChannelRecordValueTypeWithFloatScaleOffset() throws KuraException {

        List<ChannelRecord> records = asset.read(new HashSet<>(Arrays.asList("9.CH")));

        assertEquals(DataType.FLOAT, records.get(0).getValueType());

    }

    @Test
    public void testChannelRecordValueTypeWithDefiniedByValueScaleOffsetInteger() throws KuraException {

        List<ChannelRecord> records = asset.read(new HashSet<>(Arrays.asList("6.CH")));

        assertEquals(DataType.INTEGER, records.get(0).getValueType());
    }

    @Test
    public void testChannelRecordValueTypeWithDefiniedByValueScaleOffsetLong() throws KuraException {

        List<ChannelRecord> records = asset.read(new HashSet<>(Arrays.asList("11.CH")));

        assertEquals(DataType.LONG, records.get(0).getValueType());
    }

    @Test
    public void testChannelRecordValueTypeWithDefiniedByValueScaleOffsetFloat() throws KuraException {

        List<ChannelRecord> records = asset.read(new HashSet<>(Arrays.asList("12.CH")));

        assertEquals(DataType.FLOAT, records.get(0).getValueType());
    }

    @Test
    public void testChannelRecordValueTypeWithDefiniedByValueScaleOffsetDouble() throws KuraException {

        List<ChannelRecord> records = asset.read(new HashSet<>(Arrays.asList("13.CH")));

        assertEquals(DataType.DOUBLE, records.get(0).getValueType());
    }

    private void sync(final Asset currentAsset) {
        try {
            ((BaseAsset) currentAsset).getBaseAssetExecutor().runConfig(() -> { }).get(5, TimeUnit.SECONDS);
        } catch (Exception e) {
            throw new AssertionError("Asset configuration did not settle", e);
        }
        AssertionError failure = this.driver.callbackFailure.get();
        if (failure != null) {
            throw failure;
        }
    }

    /** The registry boundary is explicit; all asset configuration and IO logic is real. */
    private final class FixtureAsset extends BaseAsset {
        private final ExecutorService io = Executors.newSingleThreadExecutor();
        private final ExecutorService configuration = Executors.newSingleThreadExecutor();

        void start() {
            activate(context, Map.of("kura.service.pid", "AssetTest",
                    "driver.pid", "org.eclipse.kura.asset.stub.driver", "request.timeout", 5000));
        }

        void stop() {
            deactivate(context);
        }

        @Override
        protected BaseAssetExecutor initBaseAssetExecutor() {
            return new BaseAssetExecutor(this.io, false, this.configuration, false);
        }

        @Override
        public void updated(Map<String, Object> properties) {
            // Model driver removal/arrival at the tracker boundary when the configuration changes.
            unsetDriver();
            sync(this);
            Map<String, Object> options = new HashMap<>(properties);
            options.putIfAbsent("request.timeout", 5000);
            super.updated(options);
            if ("org.eclipse.kura.asset.stub.driver".equals(options.get("driver.pid"))) {
                setDriver(driver);
            }
            sync(this);
        }
    }
}
