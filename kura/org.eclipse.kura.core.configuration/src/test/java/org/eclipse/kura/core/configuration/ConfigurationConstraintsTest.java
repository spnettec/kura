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
}
