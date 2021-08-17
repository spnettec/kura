/*******************************************************************************
 * Copyright (c) 2017 Eurotech and/or its affiliates and others
 *
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 * Contributors:
 *     Eurotech
 *******************************************************************************/

package org.eclipse.kura.driver.block.task;

import org.eclipse.kura.channel.ChannelFlag;
import org.eclipse.kura.channel.ChannelRecord;
import org.eclipse.kura.channel.ChannelStatus;
import org.eclipse.kura.driver.binary.Buffer;
import org.eclipse.kura.type.DataType;
import org.eclipse.kura.type.TypedValue;
import org.eclipse.kura.type.TypedValues;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class BitTask extends UpdateBlockTask {

    private static final Logger logger = LoggerFactory.getLogger(BitTask.class);
    private int bit;

    public BitTask(ChannelRecord record, int start, int bit, Mode mode) {
        super(record, start, start + 1, mode);
        this.bit = bit;
    }

    public void setBit(int bit) {
        this.bit = bit;
    }

    @Override
    protected void runRead() {
        final ToplevelBlockTask parent = getParent();
        Buffer buffer = parent.getBuffer();

        byte b = buffer.get(getStart() - parent.getStart());

        final boolean result = (b >> this.bit & 0x01) == 1;

        logger.debug("Reading Bit: offset {} bit index {} result {}", getStart(), this.bit, result);

        try {
            this.record.setValue(map(result, this.record.getValueType()));
        } catch (Exception e) {
            this.record.setChannelStatus(new ChannelStatus(ChannelFlag.FAILURE, e.getMessage(), e));
        }
        onSuccess();
    }

    private static TypedValue<?> map(final Object value, final DataType targetType) throws Exception {
        switch (targetType) {
        case LONG:
            return TypedValues.newLongValue(((Number) (value == null ? 0 : value)).longValue());
        case FLOAT:
            return TypedValues.newFloatValue(((Number) (value == null ? 0 : value)).floatValue());
        case DOUBLE:
            return TypedValues.newDoubleValue(((Number) (value == null ? 0 : value)).doubleValue());
        case INTEGER:
            if (value instanceof Boolean) {
                return TypedValues.newIntegerValue(((Boolean) value) == Boolean.TRUE ? 1 : 0);
            }
            return TypedValues.newIntegerValue(((Number) (value == null ? 0 : value)).intValue());
        case BOOLEAN:
            if (value instanceof Number) {
                return TypedValues.newBooleanValue(((Number) (value == null ? 0 : value)).intValue() > 0);
            } else if (value instanceof Boolean) {
                return TypedValues.newBooleanValue((Boolean) (value == null ? false : value));
            } else {
                return TypedValues.newBooleanValue(Boolean.parseBoolean(value == null ? "" : (String) value));
            }
        case STRING:
            return TypedValues.newStringValue(value == null ? "" : (String) value);
        case BYTE_ARRAY:
            return TypedValues.newByteArrayValue((byte[]) (value == null ? (new byte[] {}) : value));
        default:
            throw new IllegalArgumentException();
        }
    }

    @Override
    protected void runWrite() {
        logger.warn("Write mode not supported");
        onFailure(new UnsupportedOperationException(
                "BitTask does not support WRITE mode, only READ and UPDATE modes are supported"));
    }

    @Override
    protected void runUpdate(ToplevelBlockTask write, ToplevelBlockTask read) {
        Buffer outBuffer = write.getBuffer();
        Buffer inBuffer = read.getBuffer();

        final int previousValueOffset = getStart() - read.getStart();
        final boolean value = (Boolean) this.record.getValue().getValue();

        byte byteValue = inBuffer.get(previousValueOffset);

        if (value) {
            byteValue |= 1 << this.bit;
        } else {
            byteValue &= ~(1 << this.bit);
        }

        inBuffer.put(previousValueOffset, byteValue);
        logger.debug("Write Bit: offset: {} value: {}", getStart(), value);
        outBuffer.put(getStart() - write.getStart(), byteValue);
    }
}