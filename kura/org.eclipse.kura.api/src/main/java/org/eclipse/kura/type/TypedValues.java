/*******************************************************************************
 * Copyright (c) 2016, 2020 Eurotech and/or its affiliates and others
 * 
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 * 
 * SPDX-License-Identifier: EPL-2.0
 * 
 * Contributors:
 *  Eurotech
 *  Amit Kumar Mondal
 ******************************************************************************/
package org.eclipse.kura.type;

import java.math.BigDecimal;
import java.math.BigInteger;
import java.util.Base64;
import java.util.Base64.Decoder;
import java.util.Objects;
import java.util.stream.Stream;

import org.eclipse.kura.annotation.Nullable;
import org.osgi.annotation.versioning.ProviderType;

/**
 * The Class TypedValues is an utility class to quickly create different
 * {@link TypedValue}
 *
 * @since 1.2
 */
@ProviderType
public final class TypedValues {

    private static final Decoder BASE64_DECODER = Base64.getDecoder();

    private TypedValues() {
        // Static Factory Methods container. No need to instantiate.
    }

    /**
     * Creates new boolean value.
     *
     * @param value
     *            the primitive boolean value
     * @return the boolean value represented as {@link TypedValue}
     */
    public static BooleanValue newBooleanValue(final boolean value) {
        return new BooleanValue(value);
    }

    /**
     * Creates new boolean value array.
     *
     * @param value
     *            the boolean value array
     * @return the boolean value represented as {@link TypedValue}
     */
    public static BooleanValues newBooleanValues(final Boolean[] values) {
        return new BooleanValues(values);
    }

    /**
     * Creates new byte array value.
     *
     * @param value
     *            the primitive byte array value
     * @return the byte array value represented as {@link TypedValue}
     * @throws org.eclipse.kura.KuraRuntimeException
     *             if the argument is null
     */
    public static ByteArrayValue newByteArrayValue(final byte[] value) {
        return new ByteArrayValue(value);
    }

    /**
     * Creates new float value.
     *
     * @param value
     *            the primitive float value
     * @return the float value represented as {@link TypedValue}
     */
    public static FloatValue newFloatValue(final float value) {
        return new FloatValue(value);
    }

    /**
     * Creates new float value array.
     *
     * @param value
     *            the float value array
     * @return the float value represented as {@link TypedValue}
     */
    public static FloatValues newFloatValues(final Float[] value) {
        return new FloatValues(value);
    }

    /**
     * Creates new double value.
     *
     * @param value
     *            the primitive double value
     * @return the double value represented as {@link TypedValue}
     */
    public static DoubleValue newDoubleValue(final double value) {
        return new DoubleValue(value);
    }

    /**
     * Creates new double value array.
     *
     * @param value
     *            the double value
     * @return the double value represented as {@link TypedValue}
     */
    public static DoubleValues newDoubleValues(final Double[] value) {
        return new DoubleValues(value);
    }

    /**
     * Creates new integer value.
     *
     * @param value
     *            the primitive integer value
     * @return the integer value represented as {@link TypedValue}
     */
    public static IntegerValue newIntegerValue(final int value) {
        return new IntegerValue(value);
    }

    /**
     * Creates new integer value array.
     *
     * @param value
     *            the integer value array
     * @return the integer value represented as {@link TypedValue}
     */
    public static IntegerValues newIntegerValues(final Integer[] value) {
        return new IntegerValues(value);
    }

    /**
     * Creates new long value.
     *
     * @param value
     *            the primitive long value
     * @return the long value represented as {@link TypedValue}
     */
    public static LongValue newLongValue(final long value) {
        return new LongValue(value);
    }

    /**
     * Creates new long value array.
     *
     * @param value
     *            array
     *            the long value
     * @return the long value represented as {@link TypedValue}
     */
    public static LongValues newLongValues(final Long[] value) {
        return new LongValues(value);
    }

    public static BigIntegerValue newBigIntegerValue(final BigInteger value) {
        return new BigIntegerValue(value);
    }

    public static BigIntegerValues newBigIntegerValues(final BigInteger[] value) {
        return new BigIntegerValues(value);
    }

    /**
     * Creates new string value.
     *
     * @param value
     *            the string value to be represented as {@link TypedValue}
     * @return the string value represented as {@link TypedValue}
     */
    public static StringValue newStringValue(@Nullable final String value) {
        return new StringValue(value);
    }

    /**
     * Creates new string value array.
     *
     * @param value
     *            the string value to be represented as {@link TypedValue}
     * @return the string value represented as {@link TypedValue}
     */
    public static StringValues newStringValues(@Nullable final String[] value) {
        return new StringValues(value);
    }

    /**
     * Creates new TypedValue inferring the type from the argument.
     *
     * @param value
     *            an object that needs to be represented as {@link TypedValue}
     * @return a {@link TypedValue} that represents the conversion of {@code value}
     * @throws IllegalArgumentException
     *             if {@code value} cannot be represented as {@link TypedValue}
     */
    public static TypedValue<?> newTypedValue(final Object value) {
        if (value instanceof Boolean) {
            return newBooleanValue((Boolean) value);
        } else if (value instanceof byte[]) {
            return newByteArrayValue((byte[]) value);
        } else if (value instanceof Float) {
            return newFloatValue((Float) value);
        } else if (value instanceof Double) {
            return newDoubleValue((Double) value);
        } else if (value instanceof Integer) {
            return newIntegerValue((Integer) value);
        } else if (value instanceof Long) {
            return newLongValue((Long) value);
        } else if (value instanceof BigInteger) {
            return newBigIntegerValue((BigInteger) value);
        } else if (value instanceof BigDecimal) {
            return newDoubleValue(((BigDecimal) value).doubleValue());
        } else if (value instanceof String) {
            return newStringValue((String) value);
        } else if (value instanceof Float[]) {
            return newFloatValues((Float[]) value);
        } else if (value instanceof Double[]) {
            return newDoubleValues((Double[]) value);
        } else if (value instanceof BigDecimal[]) {
            return newDoubleValues(Stream.of((BigDecimal[]) value).map(Number::doubleValue).toArray(Double[]::new));
        } else if (value instanceof Integer[]) {
            return newIntegerValues((Integer[]) value);
        } else if (value instanceof Long[]) {
            return newLongValues((Long[]) value);
        } else if (value instanceof BigInteger[]) {
            return newBigIntegerValues((BigInteger[]) value);
        } else if (value instanceof String[]) {
            return newStringValues((String[]) value);
        }

        throw new IllegalArgumentException("Cannot convert to TypedValue");
    }

    /**
     * Parses a TypedValue of given type from a String.
     *
     * @param value
     *            the String to be parsed into a {@link TypedValue}
     * @param type
     *            the {@link DataType} of the returned {@link TypedValue}
     * @return a {@link TypedValue} that represents the conversion of {@code value}
     * @throws IllegalArgumentException
     *             if {@code value} cannot be represented as {@link TypedValue}
     */
    public static TypedValue<?> parseTypedValue(final DataType type, final String value) {
        Objects.requireNonNull(value, "value cannot be null");
        try {
            switch (type) {
            case BOOLEAN:
                return newBooleanValue(Boolean.parseBoolean(value));
            case BYTE_ARRAY:
                return TypedValues.newByteArrayValue(BASE64_DECODER.decode(value));
            case DOUBLE:
                return newDoubleValue(Double.parseDouble(value));
            case FLOAT:
                return newFloatValue(Float.parseFloat(value));
            case INTEGER:
                return newIntegerValue(Integer.parseInt(value));
            case LONG:
                return newLongValue(Long.parseLong(value));
            case BIGINTEGER:
                return newBigIntegerValue(new BigInteger(value));
            case STRING:
                return newStringValue(value);
            default:
            }
        } catch (Exception e) {
        }
        throw new IllegalArgumentException(value + " cannot be converted into a TypedValue of type " + type);
    }
}
