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

import static java.util.Objects.requireNonNull;
import static org.eclipse.kura.type.DataType.BOOLEANS;

import java.util.Arrays;

import org.eclipse.kura.annotation.Immutable;
import org.eclipse.kura.annotation.ThreadSafe;
import org.osgi.annotation.versioning.ProviderType;

/**
 * This class represents a {@link Boolean} value as a {@link TypedValue}.
 *
 * @noextend This class is not intended to be extended by clients.
 * @since 1.2
 */
@Immutable
@ThreadSafe
@ProviderType
public class BooleanValues implements TypedValue<Boolean[]> {

    /**
     * The actual contained value that will be represented as
     * {@link TypedValue}.
     */
    private final Boolean[] value;

    /**
     * Instantiates a new boolean value.
     *
     * @param value
     *                  the value
     */
    public BooleanValues(final Boolean[] value) {
        this.value = value;
    }

    /** {@inheritDoc} */
    @Override
    public int compareTo(final TypedValue<Boolean[]> otherTypedValue) {
        requireNonNull(otherTypedValue, "Typed Value cannot be null");
        final Boolean[] otherValue = otherTypedValue.getValue();
        for (int i = 0, j = 0; i < this.value.length && j < otherValue.length; i++, j++) {
            int caonpare = this.value[i] == otherTypedValue.getValue()[i] ? 0 : this.value[i] ? 1 : -1;
            if (caonpare != 0) {
                return caonpare;
            }
        }
        return this.value.length - otherValue.length;
    }

    /** {@inheritDoc} */
    @Override
    public boolean equals(final Object obj) {
        if (this == obj) {
            return true;
        }
        if (obj == null) {
            return false;
        }
        if (this.getClass() != obj.getClass()) {
            return false;
        }
        final BooleanValues other = (BooleanValues) obj;
        if (!Arrays.equals(this.value, other.value)) {
            return false;
        }
        return true;
    }

    /** {@inheritDoc} */
    @Override
    public DataType getType() {
        return BOOLEANS;
    }

    /** {@inheritDoc} */
    @Override
    public Boolean[] getValue() {
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
        return "BooleanValue [value=" + this.value + "]";
    }

}
