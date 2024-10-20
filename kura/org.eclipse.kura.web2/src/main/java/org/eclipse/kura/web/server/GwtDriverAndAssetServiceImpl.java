/*******************************************************************************
 * Copyright (c) 2017, 2021 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.web.server;

import static java.lang.String.format;
import static org.eclipse.kura.configuration.ConfigurationService.KURA_SERVICE_PID;

import java.io.IOException;
import java.io.StringWriter;
import java.io.Writer;
import java.math.BigInteger;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Base64;
import java.util.Base64.Decoder;
import java.util.Base64.Encoder;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.concurrent.atomic.AtomicInteger;

import javax.servlet.http.HttpSession;

import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVPrinter;
import org.eclipse.kura.asset.Asset;
import org.eclipse.kura.channel.ChannelFlag;
import org.eclipse.kura.channel.ChannelRecord;
import org.eclipse.kura.channel.ChannelStatus;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.configuration.metatype.AD;
import org.eclipse.kura.driver.Driver;
import org.eclipse.kura.internal.wire.asset.WireAssetChannelDescriptor;
import org.eclipse.kura.type.DataType;
import org.eclipse.kura.type.TypedValue;
import org.eclipse.kura.type.TypedValues;
import org.eclipse.kura.web.server.util.GwtComponentServiceInternal;
import org.eclipse.kura.web.server.util.GwtServerUtil;
import org.eclipse.kura.web.server.util.ServiceLocator;
import org.eclipse.kura.web.server.util.ServiceLocator.ServiceConsumer;
import org.eclipse.kura.web.shared.GwtKuraErrorCode;
import org.eclipse.kura.web.shared.GwtKuraException;
import org.eclipse.kura.web.shared.model.GwtChannelOperationResult;
import org.eclipse.kura.web.shared.model.GwtChannelRecord;
import org.eclipse.kura.web.shared.model.GwtConfigComponent;
import org.eclipse.kura.web.shared.model.GwtConfigParameter;
import org.eclipse.kura.web.shared.model.GwtXSRFToken;
import org.eclipse.kura.web.shared.service.GwtDriverAndAssetService;
import org.osgi.framework.BundleContext;
import org.osgi.framework.FrameworkUtil;
import org.osgi.framework.ServiceReference;

import com.eclipsesource.json.Json;

public class GwtDriverAndAssetServiceImpl extends OsgiRemoteServiceServlet implements GwtDriverAndAssetService {

    private static final long serialVersionUID = 8627173534436639487L;

    private static final Decoder BASE64_DECODER = Base64.getDecoder();
    private static final Encoder BASE64_ENCODER = Base64.getEncoder();
    private static final AtomicInteger nextId = new AtomicInteger();

    @Override
    public GwtChannelOperationResult readAllChannels(GwtXSRFToken xsrfToken, String assetPid) throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        try {
            List<GwtChannelRecord> result = new ArrayList<>();

            withAsset(assetPid, asset -> {
                List<ChannelRecord> assetData = asset.readAllChannels();
                for (ChannelRecord channelRecord : assetData) {
                    result.add(toGwt(channelRecord));
                }
            });

            return new GwtChannelOperationResult(result);
        } catch (Exception e) {
            return getFailureResult(e);
        }
    }

    @Override
    public GwtConfigComponent getUploadedCsvConfig(final GwtXSRFToken xsrfToken, final String assetPid)
            throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        final HttpSession session = getThreadLocalRequest().getSession(false);
        final String key = "kura.csv.config." + assetPid;

        final GwtConfigComponent result = (GwtConfigComponent) session.getAttribute(key);

        if (result == null) {
            throw new GwtKuraException("Uploaded configuration not available");
        }

        session.removeAttribute(key);

        return result;
    }

    @Override
    public GwtChannelOperationResult write(GwtXSRFToken xsrfToken, String assetPid,
            List<GwtChannelRecord> gwtChannelRecords) throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        try {
            final Map<String, GwtChannelRecord> groupedRecords = new HashMap<>(gwtChannelRecords.size());

            for (final GwtChannelRecord record : gwtChannelRecords) {
                record.setUnescaped(true);
                groupedRecords.put(record.getName(), record);
            }

            final List<ChannelRecord> channelRecords = new ArrayList<>();

            for (GwtChannelRecord gwtChannelData : gwtChannelRecords) {
                String channelName = gwtChannelData.getName();
                String typedValue = gwtChannelData.getValueType();
                String value = gwtChannelData.getValue();
                try {
                    channelRecords
                            .add(ChannelRecord.createWriteRecord(channelName, parseTypedValue(value, typedValue)));
                } catch (Exception e) {
                    gwtChannelData.setValue(null);
                    gwtChannelData.setExceptionMessage(e.getMessage());
                    gwtChannelData.setExceptionStackTrace(e.getStackTrace());
                }
            }

            withAsset(assetPid, asset -> asset.write(channelRecords));

            for (final ChannelRecord record : channelRecords) {
                final GwtChannelRecord gwtChannelRecord = groupedRecords.get(record.getChannelName());
                final ChannelStatus status = record.getChannelStatus();

                if (status.getChannelFlag() == ChannelFlag.FAILURE) {
                    fillErrorData(status, gwtChannelRecord);
                }
            }

            return new GwtChannelOperationResult(gwtChannelRecords);
        } catch (Exception e) {
            return getFailureResult(e);
        }
    }

    private GwtChannelOperationResult getFailureResult(final Throwable e) {
        final Throwable rootCause = e.getCause();
        if (rootCause != null) {
            // e is likely a not so interesting KuraException thrown by BaseAsset.
            // Since the FailureHandler widget is not able to display the
            // stack traces of the whole exception stack, forward the root
            // exception generated by the Driver if available.
            // TODO modify FailureHandler to display the whole exception stack
            return new GwtChannelOperationResult(rootCause);
        }
        return new GwtChannelOperationResult(e);
    }

    private void withAsset(final String kuraServicePid, final ServiceConsumer<Asset> consumer) throws Exception {
        final BundleContext ctx = FrameworkUtil.getBundle(ServiceLocator.class).getBundleContext();

        final String filter = format("(%s=%s)", KURA_SERVICE_PID, kuraServicePid);
        final Collection<ServiceReference<Asset>> refs = ctx.getServiceReferences(Asset.class, filter);

        if (refs == null || refs.isEmpty()) {
            return;
        }

        final ServiceReference<Asset> assetRef = refs.iterator().next();

        try {
            consumer.consume(ctx.getService(assetRef));
        } finally {
            ctx.ungetService(assetRef);
        }
    }

    private static GwtChannelRecord toGwt(final ChannelRecord channelRecord) {
        GwtChannelRecord channelData = new GwtChannelRecord();
        channelData.setName(channelRecord.getChannelName());
        channelData.setValueType(channelRecord.getValueType().toString());

        final ChannelStatus status = channelRecord.getChannelStatus();

        if (ChannelFlag.SUCCESS.equals(status.getChannelFlag())) {
            channelData.setValue(typedValueToString(channelRecord.getValue()));
        } else {
            fillErrorData(status, channelData);
        }
        return channelData;
    }

    private static void fillErrorData(final ChannelStatus status, final GwtChannelRecord record) {
        record.setValue(null);

        final Exception exception = status.getException();

        final String userMessage = status.getExceptionMessage();
        final String exceptionMessage = exception != null ? exception.getMessage() : null;

        final StringBuilder exceptionMessageBuilder = new StringBuilder();

        if (userMessage != null) {
            exceptionMessageBuilder.append(userMessage);
        }

        if (exceptionMessage != null && !exceptionMessage.equals(userMessage)) {
            exceptionMessageBuilder.append(exceptionMessage);
        }

        record.setExceptionMessage(exceptionMessageBuilder.toString());

        if (exception != null) {
            record.setExceptionStackTrace(exception.getStackTrace());
        }
    }

    private static TypedValue<?> parseTypedValue(final String userValue, final String userType) {
        final DataType dataType = DataType.getDataType(userType);

        if (DataType.INTEGER == dataType) {
            return TypedValues.newIntegerValue(Integer.parseInt(userValue));
        }
        if (DataType.INTEGERS == dataType) {
            Integer[] values = Json.parse(userValue).asArray().values().stream().map(v -> v.asInt())
                    .toArray(Integer[]::new);
            return TypedValues.newIntegerValues(values);
        }
        if (DataType.BOOLEAN == dataType) {
            return TypedValues.newBooleanValue(Boolean.parseBoolean(userValue));
        }
        if (DataType.BOOLEANS == dataType) {
            Boolean[] values = Json.parse(userValue).asArray().values().stream().map(v -> v.asBoolean())
                    .toArray(Boolean[]::new);
            return TypedValues.newBooleanValues(values);
        }
        if (DataType.FLOAT == dataType) {
            return TypedValues.newFloatValue(Float.parseFloat(userValue));
        }
        if (DataType.DOUBLE == dataType) {
            return TypedValues.newDoubleValue(Double.parseDouble(userValue));
        }
        if (DataType.DOUBLES == dataType) {
            Double[] values = Json.parse(userValue).asArray().values().stream().map(v -> v.asDouble())
                    .toArray(Double[]::new);
            return TypedValues.newDoubleValues(values);
        }
        if (DataType.LONG == dataType) {
            return TypedValues.newLongValue(Long.parseLong(userValue));
        }
        if (DataType.LONGS == dataType) {
            Long[] values = Json.parse(userValue).asArray().values().stream().map(v -> v.asLong()).toArray(Long[]::new);
            return TypedValues.newLongValues(values);
        }
        if (DataType.BIGINTEGER == dataType) {
            return TypedValues.newBigIntegerValue(new BigInteger(userValue));
        }
        if (DataType.BIGINTEGERS == dataType) {
            BigInteger[] values = Json.parse(userValue).asArray().values().stream()
                    .map(v -> new BigInteger(v.toString())).toArray(BigInteger[]::new);
            return TypedValues.newBigIntegerValues(values);
        }
        if (DataType.STRING == dataType) {
            return TypedValues.newStringValue(userValue);
        }
        if (DataType.STRINGS == dataType) {
            String[] values = Json.parse(userValue).asArray().values().stream().map(Object::toString)
                    .toArray(String[]::new);
            return TypedValues.newStringValues(values);
        }
        if (DataType.BYTE_ARRAY == dataType) {
            return TypedValues.newByteArrayValue(BASE64_DECODER.decode(userValue));
        }

        throw new IllegalArgumentException();
    }

    private static String typedValueToString(TypedValue<?> typedValue) {
        if (typedValue.getType() == DataType.BYTE_ARRAY) {
            return BASE64_ENCODER.encodeToString((byte[]) typedValue.getValue());
        }
        if (typedValue.getValue().getClass().isArray()) {
            return Arrays.toString((Object[]) typedValue.getValue());
        }
        return typedValue.getValue().toString();
    }

    @SuppressWarnings("unchecked")
    @Override
    public int convertToCsv(final GwtXSRFToken token, final String driverPid, final GwtConfigComponent assetConfig)
            throws GwtKuraException, IOException {

        checkXSRFToken(token);

        final List<AD> wireAssetDescriptor = (List<AD>) WireAssetChannelDescriptor.get().getDescriptor();

        final List<AD> channelDescriptor = new ArrayList<>();

        for (final AD ad : wireAssetDescriptor) {
            channelDescriptor.add(ad);
        }

        ServiceLocator.withAllServices(Driver.class, "(kura.service.pid=" + driverPid + ")", d -> {
            final List<AD> desc = (List<AD>) d.getChannelDescriptor().getDescriptor();

            channelDescriptor.addAll(desc);
        });

        if (channelDescriptor.size() == wireAssetDescriptor.size()) {
            throw new GwtKuraException("Driver not found");
        }

        final Set<String> channelNames = new TreeSet<>();
        final Map<String, GwtConfigParameter> paramsById = new HashMap<>();

        assetConfig.getParameters().forEach(p -> {
            final String id = p.getId();
            final int index = id.indexOf('#');
            if (index == -1) {
                return;
            }
            channelNames.add(id.substring(0, index));
            paramsById.put(id, p);
        });

        final Writer out = new StringWriter();

        try (final CSVPrinter printer = new CSVPrinter(out, CSVFormat.RFC4180)) {

            for (int i = 0; i < channelDescriptor.size(); i++) {
                final String id = channelDescriptor.get(i).getId();

                if (i < wireAssetDescriptor.size()) {
                    printer.print(id.substring(1));
                } else {
                    printer.print(id);
                }
            }

            printer.println();

            for (final String channel : channelNames) {
                for (final AD ad : channelDescriptor) {
                    final String key = channel + '#' + ad.getId();
                    final GwtConfigParameter param = paramsById.get(key);
                    printer.print(param != null ? param.getValue() : null);
                }
                printer.println();
            }

        }

        final int id = nextId.getAndIncrement();

        final HttpSession session = getThreadLocalRequest().getSession(false);

        session.setAttribute("kura.csv.download." + id, out.toString());

        return id;
    }

    @Override
    public void createDriverOrAssetConfiguration(GwtXSRFToken token, String factoryPid, String pid, String name,
            String componentDescription) throws GwtKuraException {
        checkXSRFToken(token);

        requireIsDriverOrAssetFactory(factoryPid);
        Map<String, Object> properties = new HashMap<>();
        properties.put(ConfigurationService.KURA_SERVICE_NAME, name);
        properties.put(ConfigurationService.KURA_SERVICE_DESC, componentDescription);

        GwtComponentServiceInternal.createFactoryComponent(factoryPid, pid, properties);
    }

    @Override
    public void createDriverOrAssetConfiguration(GwtXSRFToken token, String factoryPid, String pid,
            GwtConfigComponent config) throws GwtKuraException {
        checkXSRFToken(token);

        requireIsDriverOrAssetFactory(factoryPid);

        GwtComponentServiceInternal.createFactoryComponent(factoryPid, pid, config);
    }

    @Override
    public void updateDriverOrAssetConfiguration(GwtXSRFToken token, GwtConfigComponent config)
            throws GwtKuraException {

        checkXSRFToken(token);

        requireIsDriverOrAsset(config.getComponentId());

        GwtComponentServiceInternal.updateComponentConfiguration(config);
    }

    @Override
    public void deleteDriverOrAssetConfiguration(GwtXSRFToken token, String pid, boolean takeSnapshot)
            throws GwtKuraException {

        checkXSRFToken(token);

        requireIsDriverOrAsset(pid);

        GwtComponentServiceInternal.deleteFactoryConfiguration(pid, takeSnapshot);
    }

    private static void requireIsDriverOrAssetFactory(String factoryPid) throws GwtKuraException {
        if (!(GwtServerUtil.isFactoryOfAnyService(factoryPid, Driver.class)
                || GwtServerUtil.isFactoryOfAnyService(factoryPid, Asset.class))) {
            throw new GwtKuraException(GwtKuraErrorCode.ILLEGAL_ARGUMENT);
        }
    }

    private static void requireIsDriverOrAsset(String kuraServicePid) throws GwtKuraException {
        if (!(GwtServerUtil.providesService(kuraServicePid, Driver.class)
                || GwtServerUtil.providesService(kuraServicePid, Asset.class))) {
            throw new GwtKuraException(GwtKuraErrorCode.ILLEGAL_ARGUMENT);
        }
    }
}