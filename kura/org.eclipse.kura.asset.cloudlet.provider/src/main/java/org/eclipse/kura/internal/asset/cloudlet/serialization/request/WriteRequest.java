/*******************************************************************************
 * Copyright (c) 2017, 2020 Eurotech and/or its affiliates and others
 * 
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 * 
 * SPDX-License-Identifier: EPL-2.0
 * 
 * Contributors:
 *  Eurotech
 ******************************************************************************/
package org.eclipse.kura.internal.asset.cloudlet.serialization.request;

import java.util.ArrayList;
import java.util.Base64;
import java.util.Base64.Decoder;
import java.util.List;

import org.eclipse.kura.channel.ChannelRecord;
import org.eclipse.kura.internal.asset.cloudlet.serialization.SerializationConstants;
import org.eclipse.kura.type.DataType;
import org.eclipse.kura.type.TypedValue;
import org.eclipse.kura.type.TypedValues;

import com.eclipsesource.json.JsonArray;
import com.eclipsesource.json.JsonObject;

public class WriteRequest {

    private final String assetName;
    private final List<ChannelRecord> channelRecords = new ArrayList<>();
    private static final Decoder BASE64_DECODER = Base64.getDecoder();

    public WriteRequest(JsonObject object) {
        this.assetName = object.get(SerializationConstants.ASSET_NAME_PROPERTY).asString();
        JsonArray channels = object.get(SerializationConstants.CHANNELS_PROPERTY).asArray();
        channels.asArray().forEach((val) -> {
            final JsonObject obj = val.asObject();
            final String name = obj.get(SerializationConstants.CHANNEL_NAME_PROPERTY).asString();
            final String type = obj.get(SerializationConstants.CHANNEL_TYPE_PROPERTY).asString();
            final String value = obj.get(SerializationConstants.CHANNEL_VALUE_PROPERTY).asString();
            this.channelRecords.add(ChannelRecord.createWriteRecord(name, parseTypedValue(value, type)));
        });
    }

    public String getAssetName() {
        return this.assetName;
    }

    public List<ChannelRecord> getChannelRecords() {
        return this.channelRecords;
    }

    public static List<WriteRequest> parseAll(JsonArray array) {
        List<WriteRequest> result = new ArrayList<>();
        array.forEach((value) -> {
            result.add(new WriteRequest(value.asObject()));
        });
        return result;
    }

    private static TypedValue<?> parseTypedValue(final String userValue, final String userType) {
        final DataType dataType = DataType.getDataType(userType);

        if (DataType.INTEGER == dataType) {
            return TypedValues.newIntegerValue(Integer.parseInt(userValue));
        }
        if (DataType.BOOLEAN == dataType) {
            return TypedValues.newBooleanValue(Boolean.parseBoolean(userValue));
        }
        if (DataType.FLOAT == dataType) {
            return TypedValues.newFloatValue(Float.parseFloat(userValue));
        }
        if (DataType.DOUBLE == dataType) {
            return TypedValues.newDoubleValue(Double.parseDouble(userValue));
        }
        if (DataType.LONG == dataType) {
            return TypedValues.newLongValue(Long.parseLong(userValue));
        }
        if (DataType.STRING == dataType) {
            return TypedValues.newStringValue(userValue);
        }
        if (DataType.BYTE_ARRAY == dataType) {
            return TypedValues.newByteArrayValue(BASE64_DECODER.decode(userValue));
        }

        throw new IllegalArgumentException();
    }
}
