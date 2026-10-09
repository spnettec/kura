/*******************************************************************************
 * Copyright (c) 2017, 2026 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.core.util;

import static org.junit.jupiter.api.Assertions.*;

import org.eclipse.kura.KuraException;
import org.junit.jupiter.api.TestMethodOrder;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Test;


@TestMethodOrder(MethodOrderer.MethodName.class)
public class ValidationUtilTest {

	@Test
	public void testNotNullWithObject() throws KuraException {
		Object value = new Object();
		ValidationUtil.notNull(value, "value");
	}

	@Test
	public void testNotNullWithNullObject() throws KuraException {
        org.junit.jupiter.api.Assertions.assertThrows(KuraException.class, () -> {
		Object value = null;
		ValidationUtil.notNull(value, "value");

        });
    }

	@Test
	public void testNotEmptyOrNullWithNonEmptyString() throws KuraException {
		String value = "xyz";
		ValidationUtil.notEmptyOrNull(value, "value");
	}

	@Test
	public void testNotEmptyOrNullWithNullString() throws KuraException {
        org.junit.jupiter.api.Assertions.assertThrows(KuraException.class, () -> {
		String value = null;
		ValidationUtil.notEmptyOrNull(value, "value");

        });
    }

	@Test
	public void testNotEmptyOrNullWithEmptyString() throws KuraException {
        org.junit.jupiter.api.Assertions.assertThrows(KuraException.class, () -> {
		String value = "";
		ValidationUtil.notEmptyOrNull(value, "value");

        });
    }

	@Test
	public void testNotEmptyOrNullWithWhitespace() throws KuraException {
        org.junit.jupiter.api.Assertions.assertThrows(KuraException.class, () -> {
		String value = " \t\n\r\f";
		ValidationUtil.notEmptyOrNull(value, "value");

        });
    }

	@Test
	public void testNotNegativeIntStringWithZero() throws KuraException {
		int value = 0;
		ValidationUtil.notNegative(value, "value");
	}

	@Test
	public void testNotNegativeIntStringWithPositive() throws KuraException {
		int value = 1;
		ValidationUtil.notNegative(value, "value");
	}

	@Test
	public void testNotNegativeIntStringWithNegative() throws KuraException {
        org.junit.jupiter.api.Assertions.assertThrows(KuraException.class, () -> {
		int value = -1;
		ValidationUtil.notNegative(value, "value");

        });
    }

	@Test
	public void testNotNegativeShortStringWithZero() throws KuraException {
		short value = 0;
		ValidationUtil.notNegative(value, "value");
	}

	@Test
	public void testNotNegativeShortStringWithPositive() throws KuraException {
		short value = 1;
		ValidationUtil.notNegative(value, "value");
	}

	@Test
	public void testNotNegativeShortStringWithNegative() throws KuraException {
        org.junit.jupiter.api.Assertions.assertThrows(KuraException.class, () -> {
		short value = -1;
		ValidationUtil.notNegative(value, "value");

        });
    }

	@Test
	public void testNotNegativeLongStringWithZero() throws KuraException {
		long value = 0;
		ValidationUtil.notNegative(value, "value");
	}

	@Test
	public void testNotNegativeLongStringWithPositive() throws KuraException {
		long value = 1;
		ValidationUtil.notNegative(value, "value");
	}

	@Test
	public void testNotNegativeLongStringWithNegative() throws KuraException {
        org.junit.jupiter.api.Assertions.assertThrows(KuraException.class, () -> {
		long value = -1;
		ValidationUtil.notNegative(value, "value");

        });
    }
}
