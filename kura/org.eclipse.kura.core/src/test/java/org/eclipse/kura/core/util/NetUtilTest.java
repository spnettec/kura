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

import org.junit.jupiter.api.TestMethodOrder;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Test;


@TestMethodOrder(MethodOrderer.MethodName.class)
public class NetUtilTest {

	@Test
	public void testHardwareAddressToString() {
		byte[] input = {0x01, 0x23, 0x45, 0x67, (byte) 0x89, (byte) 0xAB};
		String result = NetUtil.hardwareAddressToString(input);
		assertEquals("01:23:45:67:89:AB", result);
	}

	@Test
	public void testHardwareAddressToStringNull() {
		byte[] input = null;
		String result = NetUtil.hardwareAddressToString(input);
		assertEquals("N/A", result);
	}

	@Test
	public void testHardwareAddressToStringEmptyValue() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
		NetUtil.hardwareAddressToString(new byte[]{});

        });
    }

	@Test
	public void testHardwareAddressToStringNotEnoughElements() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
		byte[] input = {0x01, 0x23, 0x45, 0x67, (byte) 0x89};
		NetUtil.hardwareAddressToString(input);

        });
    }

	@Test
	public void testHardwareAddressToStringTooManyElements() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
		byte[] input = {0x01, 0x23, 0x45, 0x67, (byte) 0x89, (byte) 0xAB, 0x42};
		NetUtil.hardwareAddressToString(input);

        });
    }

	@Test
	public void testHardwareAddressToBytes() {
		byte[] result = NetUtil.hardwareAddressToBytes("01:23:45:67:89:AB");
		byte[] expected = {0x01, 0x23, 0x45, 0x67, (byte) 0x89, (byte) 0xAB};
		assertArrayEquals(expected, result);
	}

	@Test
	public void testHardwareAddressToBytesNullOrEmpty() {
		byte[] expected = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00};

		byte[] result = NetUtil.hardwareAddressToBytes(null);
		assertArrayEquals(expected, result);

		result = NetUtil.hardwareAddressToBytes("");
		assertArrayEquals(expected, result);
	}

	@Test
	public void testHardwareAddressToBytesInvalidValue1() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
		NetUtil.hardwareAddressToBytes("g1:23:45:67:89:AB");

        });
    }

	@Test
	public void testHardwareAddressToBytesInvalidValue2() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
		NetUtil.hardwareAddressToBytes("01::45:67:89:AB");

        });
    }

	@Test
	public void testHardwareAddressToBytesInvalidValueNotEnoughElements() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
		NetUtil.hardwareAddressToBytes("01:23:45:67:89");

        });
    }

	@Test
	public void testHardwareAddressToBytesTooManyElements() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
		NetUtil.hardwareAddressToBytes("01:23:45:67:89:AB:42");

        });
    }

	@Test
	public void testHardwareAddressToBytesOutOfRangeValue() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
		NetUtil.hardwareAddressToBytes("101:23:45:67:89:AB");

        });
    }
}
