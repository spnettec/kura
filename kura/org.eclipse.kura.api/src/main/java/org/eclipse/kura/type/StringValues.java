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
import static org.eclipse.kura.type.DataType.STRINGS;

import java.util.Arrays;

import org.eclipse.kura.annotation.Immutable;
import org.eclipse.kura.annotation.Nullable;
import org.eclipse.kura.annotation.ThreadSafe;
import org.osgi.annotation.versioning.ProviderType;

/**
 * This class represents a {@link String} value as a {@link TypedValue}.
 *
 * @noextend This class is not intended to be extended by clients.
 * @since 1.2
 */
@Immutable
@ThreadSafe
@ProviderType
public class StringValues implements TypedValue<String[]> {

    /**
     * The actual contained value that will be represented as
     * {@link TypedValue}.
     */
    private final String[] value;

    /**
     * Instantiates a new string value.
     *
     * @param value
     *                  the value
     */
    public StringValues(@Nullable final String[] value) {
        this.value = value;
    }

    /** {@inheritDoc} */
    @Override
    public int compareTo(final TypedValue<String[]> otherTypedValue) {
        requireNonNull(otherTypedValue, "Typed Value cannot be null");
        final String[] otherValue = otherTypedValue.getValue();
        for (int i = 0, j = 0; i < this.value.length && j < otherValue.length; i++, j++) {
            int caonpare = this.value[i].compareTo(otherValue[i]);
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
        final StringValues other = (StringValues) obj;
        if (!Arrays.equals(this.value, other.value)) {
            return false;
        }
        return true;
    }

    /** {@inheritDoc} */
    @Override
    public DataType getType() {
        return STRINGS;
    }

    /** {@inheritDoc} */
    @Override
    public String[] getValue() {
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
        return "StringValues [value=" + Arrays.toString(this.value) + "]";
    }

}
