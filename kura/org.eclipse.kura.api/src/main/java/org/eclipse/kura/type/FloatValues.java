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
 *******************************************************************************/
package org.eclipse.kura.type;

import static java.util.Objects.requireNonNull;
import static org.eclipse.kura.type.DataType.FLOAT;

import java.util.Arrays;

import org.eclipse.kura.annotation.Immutable;
import org.eclipse.kura.annotation.ThreadSafe;
import org.osgi.annotation.versioning.ProviderType;

/**
 * This class represents a {@link Float} value as a {@link TypedValue}.
 *
 * @noextend This class is not intended to be extended by clients.
 * @since 1.2
 */
@Immutable
@ThreadSafe
@ProviderType
public class FloatValues implements TypedValue<Float[]> {

    /**
     * The actual contained value that will be represented as
     * {@link TypedValue}.
     */
    private final Float[] value;

    /**
     * Instantiates a new {@link Float} value.
     *
     * @param value
     *                  the value
     */
    public FloatValues(final Float[] value) {
        this.value = value;
    }

    /** {@inheritDoc} */
    @Override
    public int compareTo(final TypedValue<Float[]> otherTypedValue) {
        requireNonNull(otherTypedValue, "Typed Value cannot be null");
        final Float[] otherValue = otherTypedValue.getValue();
        for (int i = 0, j = 0; i < this.value.length && j < otherValue.length; i++, j++) {
            int caonpare = Float.valueOf(this.value[i].longValue()).compareTo(otherValue[i]);
            if (caonpare != 0) {
                return caonpare;
            }
        }
        return this.value.length - otherValue.length;
    }

    /** {@inheritDoc} */
    @Override
    public boolean equals(Object obj) {
        if (this == obj) {
            return true;
        }
        if (obj == null) {
            return false;
        }
        if (this.getClass() != obj.getClass()) {
            return false;
        }
        final FloatValues other = (FloatValues) obj;
        if (!Arrays.equals(this.value, other.value)) {
            return false;
        }
        return true;
    }

    /** {@inheritDoc} */
    @Override
    public DataType getType() {
        return FLOAT;
    }

    /** {@inheritDoc} */
    @Override
    public Float[] getValue() {
        return this.value;
    }

    /** {@inheritDoc} */
    @Override
    public int hashCode() {
        final int prime = 31;
        int result = 1;
        result = prime * result + Arrays.hashCode(this.value);
        return result;
    }

    /** {@inheritDoc} */
    @Override
    public String toString() {
        return "FloatValues [value=" + Arrays.toString(this.value) + "]";
    }
}
