/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.util.List;

import org.eclipse.kura.configuration.ConfigurationConstraints;
import org.eclipse.kura.configuration.ConfigurationConstraints.Status;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.configuration.metatype.AD;
import org.eclipse.kura.configuration.metatype.Option;
import org.eclipse.kura.configuration.metatype.Scalar;
import org.junit.jupiter.api.Test;

class ConfigurationConstraintsTest {
    @Test void legacyOneCardinalityScalarsRemainValidAlongsideBoundedContainers() {
        AD ad = org.mockito.Mockito.mock(AD.class, org.mockito.Mockito.CALLS_REAL_METHODS);
        when(ad.getId()).thenReturn("field"); when(ad.getType()).thenReturn(Scalar.STRING);
        for (int cardinality : new int[] {1, -1}) {
            when(ad.getCardinality()).thenReturn(cardinality);
            assertEquals(Status.SATISFIED, ConfigurationConstraints.value(ad, " spaced "));
            assertEquals(Status.SATISFIED, ConfigurationConstraints.value(ad, cardinality > 0
                    ? new String[] {"x"} : new java.util.ArrayList<>(List.of("x"))));
            assertEquals(Status.REJECTED, ConfigurationConstraints.value(ad, new String[] {"x", "y"}));
        }
    }
    private AD attribute(Scalar type) {
        AD value = mock(AD.class);
        when(value.getId()).thenReturn("field");
        when(value.getType()).thenReturn(type);
        return value;
    }

    @Test void enforcesNumericBoundsAndOptionsWithoutIgnoringUnreadableMetadata() {
        AD count = attribute(Scalar.INTEGER);
        when(count.getMin()).thenReturn("2");
        when(count.getMax()).thenReturn("4");
        assertEquals(Status.SATISFIED, ConfigurationConstraints.field(count));
        assertEquals(Status.REJECTED, ConfigurationConstraints.value(count, 1));
        assertEquals(Status.SATISFIED, ConfigurationConstraints.value(count, 2));
        when(count.getMin()).thenReturn("not-a-number");
        assertEquals(Status.UNSUPPORTED, ConfigurationConstraints.field(count));
        Option option = mock(Option.class);
        when(option.getValue()).thenReturn("7");
        when(count.getMin()).thenReturn(null);
        when(count.getMax()).thenReturn(null);
        when(count.getOption()).thenReturn(List.of(option));
        assertEquals(Status.SATISFIED, ConfigurationConstraints.value(count, 7));
        assertEquals(Status.REJECTED, ConfigurationConstraints.value(count, 8));
    }

    @Test void stringLengthUsesCodeUnitsAndSecretOptionsStayClosed() {
        AD text = attribute(Scalar.STRING);
        when(text.getMin()).thenReturn("2");
        when(text.getMax()).thenReturn("4");
        assertEquals(Status.REJECTED, ConfigurationConstraints.value(text, "a"));
        assertEquals(Status.SATISFIED, ConfigurationConstraints.value(text, "abcd"));
        assertEquals(Status.REJECTED, ConfigurationConstraints.value(text, "abcde"));
        AD password = attribute(Scalar.PASSWORD);
        when(password.getMin()).thenReturn("4");
        assertEquals(Status.SATISFIED, ConfigurationConstraints.value(password, new Password("safe")));
        assertEquals(Status.REJECTED, ConfigurationConstraints.value(password, new Password("no")));
        when(password.getOption()).thenReturn(List.of(mock(Option.class)));
        assertEquals(Status.UNSUPPORTED, ConfigurationConstraints.field(password));
    }

    @Test void stringOptionsMatchExactValuesForScalarsAndContainers() {
        AD text = attribute(Scalar.STRING);
        Option option = mock(Option.class);
        when(option.getValue()).thenReturn("safe");
        when(text.getOption()).thenReturn(List.of(option));
        assertEquals(Status.SATISFIED, ConfigurationConstraints.value(text, "safe"));
        assertEquals(Status.REJECTED, ConfigurationConstraints.value(text, "same"));
        when(option.getValue()).thenReturn("4");
        assertEquals(Status.SATISFIED, ConfigurationConstraints.value(text, "4"));
        assertEquals(Status.REJECTED, ConfigurationConstraints.value(text, "abcd"));
        assertEquals(Status.REJECTED, ConfigurationConstraints.value(text, 4));
        when(text.getCardinality()).thenReturn(4);
        assertEquals(Status.SATISFIED, ConfigurationConstraints.value(text, new String[] {"4", "4"}));
        assertEquals(Status.REJECTED, ConfigurationConstraints.value(text, new String[] {"4", "abcd"}));
        assertEquals(Status.REJECTED, ConfigurationConstraints.value(text, new Integer[] {4}));
        assertEquals(Status.REJECTED, ConfigurationConstraints.value(text, new String[] {"4", "4", "4", "4", "4"}));
        when(text.getCardinality()).thenReturn(-2);
        assertEquals(Status.SATISFIED, ConfigurationConstraints.value(text, new java.util.Vector<>(List.of("4", "4"))));
        assertEquals(Status.REJECTED, ConfigurationConstraints.value(text, new java.util.Vector<>(List.of("4", "4", "4"))));
        when(text.getCardinality()).thenReturn(Integer.MIN_VALUE);
        assertEquals(Status.SATISFIED, ConfigurationConstraints.value(text, new String[] {"4"}));
        assertEquals(Status.REJECTED, ConfigurationConstraints.value(attribute(Scalar.BYTE), 256));
    }
}
