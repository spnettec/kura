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
 *  Amit Kumar Mondal
 ******************************************************************************/

/**
 * This is a copy of {@code org.eclipse.kura.type.DataType}
 */

package org.eclipse.kura.web.shared;

import org.eclipse.kura.type.TypedValue;

/**
 * This contains all the required data type constants required for representing
 * Java data types as {@link TypedValue}
 *
 * @since 1.2
 */
public enum DataType {

    BOOLEAN,

    BOOLEANS,

    BYTE_ARRAY,

    DOUBLE,

    DOUBLES,

    INTEGER,

    INTEGERS,

    LONG,

    LONGS,

    BIGINTEGER,

    BIGINTEGERS,

    FLOAT,

    FLOATS,

    STRING,

    STRINGS;

    /**
     * Converts {@code stringDataType}, if possible, to the related {@link DataType}.
     *
     * @param stringDataType
     *                           String that we want to use to get the respective {@link DataType}.
     * @return a DataType that corresponds to the String passed as argument.
     * @throws IllegalArgumentException
     *                                      if the passed string does not correspond to an existing {@link DataType}.
     */
    public static DataType getDataType(String stringDataType) {
        if (INTEGER.name().equalsIgnoreCase(stringDataType)) {
            return INTEGER;
        }
        if (INTEGERS.name().equalsIgnoreCase(stringDataType)) {
            return INTEGERS;
        }
        if (FLOAT.name().equalsIgnoreCase(stringDataType)) {
            return FLOAT;
        }
        if (FLOATS.name().equalsIgnoreCase(stringDataType)) {
            return FLOATS;
        }
        if (DOUBLE.name().equalsIgnoreCase(stringDataType)) {
            return DOUBLE;
        }
        if (DOUBLES.name().equalsIgnoreCase(stringDataType)) {
            return DOUBLES;
        }
        if (LONG.name().equalsIgnoreCase(stringDataType)) {
            return LONG;
        }
        if (LONGS.name().equalsIgnoreCase(stringDataType)) {
            return LONGS;
        }
        if (BYTE_ARRAY.name().equalsIgnoreCase(stringDataType)) {
            return BYTE_ARRAY;
        }
        if (BOOLEAN.name().equalsIgnoreCase(stringDataType)) {
            return BOOLEAN;
        }
        if (BOOLEANS.name().equalsIgnoreCase(stringDataType)) {
            return BOOLEANS;
        }
        if (BIGINTEGER.name().equalsIgnoreCase(stringDataType)) {
            return BIGINTEGER;
        }
        if (BIGINTEGERS.name().equalsIgnoreCase(stringDataType)) {
            return BIGINTEGERS;
        }
        if (STRING.name().equalsIgnoreCase(stringDataType)) {
            return STRING;
        }
        if (STRINGS.name().equalsIgnoreCase(stringDataType)) {
            return STRINGS;
        }

        throw new IllegalArgumentException("Cannot convert DataType:" + stringDataType + " to DataType");
    }
}
