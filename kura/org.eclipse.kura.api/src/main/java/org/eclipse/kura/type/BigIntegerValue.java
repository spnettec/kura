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
import static org.eclipse.kura.type.DataType.BIGINTEGER;

import java.math.BigInteger;

import org.eclipse.kura.annotation.Immutable;
import org.eclipse.kura.annotation.ThreadSafe;
import org.osgi.annotation.versioning.ProviderType;

/**
 * This class represents a {@link Long} value as a {@link TypedValue}.
 *
 * @noextend This class is not intended to be extended by clients.
 * @since 1.2
 */
@Immutable
@ThreadSafe
@ProviderType
public class BigIntegerValue implements TypedValue<BigInteger> {

    /**
     * The actual contained value that will be represented as
     * {@link TypedValue}.
     */
    private final BigInteger value;

    /**
     * Instantiates a new long value.
     *
     * @param value
     *            the value
     */
    public BigIntegerValue(final BigInteger value) {
        this.value = value;
    }

    /** {@inheritDoc} */
    @Override
    public int compareTo(final TypedValue<BigInteger> otherTypedValue) {
        requireNonNull(otherTypedValue, "Typed Value cannot be null");
        return BigInteger.valueOf(this.value.longValue()).compareTo(otherTypedValue.getValue());
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
        final BigIntegerValue other = (BigIntegerValue) obj;
        if (this.value != other.value) {
            return false;
        }
        return true;
    }

    /** {@inheritDoc} */
    @Override
    public DataType getType() {
        return BIGINTEGER;
    }

    /** {@inheritDoc} */
    @Override
    public BigInteger getValue() {
        return this.value;
    }

    /** {@inheritDoc} */
    @Override
    public int hashCode() {
        final int prime = 31;
        int result = 1;
        result = prime * result + (int) (this.value.longValue() ^ this.value.longValue() >>> 32);
        return result;
    }

    /** {@inheritDoc} */
    @Override
    public String toString() {
        return "BigIntegerValue [value=" + this.value + "]";
    }

}
