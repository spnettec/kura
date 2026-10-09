/*******************************************************************************
 * Copyright (c) 2016, 2026 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.util.net;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.TestMethodOrder;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.MethodOrderer;

@TestMethodOrder(MethodOrderer.MethodName.class)
public class NetworkUtilTest {

    @Test
    public void testCalculateNetwork() throws IllegalArgumentException {
        String result = NetworkUtil.calculateNetwork("192.168.1.123", "255.255.255.0");
        assertEquals("192.168.1.0", result);

        result = NetworkUtil.calculateNetwork("10.100.250.1", "255.0.0.0");
        assertEquals("10.0.0.0", result);
    }

    @Test
    public void testCalculateNetworkNullAddress() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateNetwork(null, "255.255.255.0");
            });
    }

    @Test
    public void testCalculateNetworkEmptyAddress() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateNetwork("", "255.255.255.0");
            });
    }

    @Test
    public void testCalculateNetworkTooShortAddress() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateNetwork("192.168.1", "255.255.255.0");
            });
    }

    @Test
    public void testCalculateNetworkTooLongAddress() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateNetwork("192.168.1.123.1", "255.255.255.0");
            });
    }

    @Test
    public void testCalculateNetworkInvalidAddress() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateNetwork("256.168.1.123", "255.255.255.0");
            });
    }

    @Test
    public void testCalculateNetworkNullSubnet() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateNetwork("192.168.1.123", null);
            });
    }

    @Test
    public void testCalculateNetworkEmptySubnet() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateNetwork("192.168.1.123", "");
            });
    }

    @Test
    public void testCalculateNetworkTooShortSubnet() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateNetwork("192.168.1.123", "255.255.255");
            });
    }

    @Test
    public void testCalculateNetworkTooLongSubnet() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateNetwork("192.168.1.123", "255.255.255.0.0");
            });
    }

    @Test
    public void testCalculateNetworkInvalidSubnet() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateNetwork("192.168.1.123", "256.255.255.0");
            });
    }

    @Test
    public void testCalculateBroadcast() throws IllegalArgumentException {
        String result = NetworkUtil.calculateBroadcast("192.168.1.123", "255.255.255.0");
        assertEquals("192.168.1.255", result);

        result = NetworkUtil.calculateBroadcast("10.100.250.1", "255.0.0.0");
        assertEquals("10.255.255.255", result);
    }

    @Test
    public void testCalculateBroadcastNullAddress() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateBroadcast(null, "255.255.255.0");
            });
    }

    @Test
    public void testCalculateBroadcastEmptyAddress() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateBroadcast("", "255.255.255.0");
            });
    }

    @Test
    public void testCalculateBroadcastTooShortAddress() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateBroadcast("192.168.1", "255.255.255.0");
            });
    }

    @Test
    public void testCalculateBroadcastTooLongAddress() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateBroadcast("192.168.1.123.1", "255.255.255.0");
            });
    }

    @Test
    public void testCalculateBroadcastInvalidAddress() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateBroadcast("256.168.1.123", "255.255.255.0");
            });
    }

    @Test
    public void testCalculateBroadcastNullSubnet() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateBroadcast("192.168.1.123", null);
            });
    }

    @Test
    public void testCalculateBroadcastEmptySubnet() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateBroadcast("192.168.1.123", "");
            });
    }

    @Test
    public void testCalculateBroadcastTooShortSubnet() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateBroadcast("192.168.1.123", "255.255.255");
            });
    }

    @Test
    public void testCalculateBroadcastTooLongSubnet() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateBroadcast("192.168.1.123", "255.255.255.0.0");
            });
    }

    @Test
    public void testCalculateBroadcastInvalidSubnet() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.calculateBroadcast("192.168.1.123", "256.255.255.0");
            });
    }

    @Test
    public void testGetNetmaskStringForm() throws IllegalArgumentException {
        String result = NetworkUtil.getNetmaskStringForm(32);
        assertEquals("255.255.255.255", result);

        result = NetworkUtil.getNetmaskStringForm(24);
        assertEquals("255.255.255.0", result);

        result = NetworkUtil.getNetmaskStringForm(17);
        assertEquals("255.255.128.0", result);

        result = NetworkUtil.getNetmaskStringForm(1);
        assertEquals("128.0.0.0", result);
    }

    @Test
    public void testGetNetmaskStringFormPrefixAboveUpperLimit() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.getNetmaskStringForm(33);
            });
    }

    @Test
    public void testGetNetmaskStringFormPrefixBelowLowerLimit() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.getNetmaskStringForm(0);
            });
    }

    @Test
    public void testGetNetmaskStringFormNegativePrefix() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.getNetmaskStringForm(-1);
            });
    }

    @Test
    public void testGetNetmaskShortForm() throws IllegalArgumentException {
        short result = NetworkUtil.getNetmaskShortForm("255.255.255.255");
        assertEquals(32, result);

        result = NetworkUtil.getNetmaskShortForm("255.255.0.0");
        assertEquals(16, result);

        result = NetworkUtil.getNetmaskShortForm("255.128.0.0");
        assertEquals(9, result);

        result = NetworkUtil.getNetmaskShortForm("128.0.0.0");
        assertEquals(1, result);
    }

    @Test
    public void testGetNetmaskShortFormNullSubnet() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.getNetmaskShortForm(null);
            });
    }

    @Test
    public void testGetNetmaskShortFormEmptySubnet() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.getNetmaskShortForm("");
            });
    }

    @Test
    public void testGetNetmaskShortFormTooShortSubnet() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.getNetmaskShortForm("255.255.255");
            });
    }

    @Test
    public void testGetNetmaskShortFormTooLongSubnet() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.getNetmaskShortForm("255.255.255.0.0");
            });
    }

    @Test
    public void testGetNetmaskShortFormInvalidSubnet1() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.getNetmaskShortForm("256.255.255.0");
            });
    }

    @Test
    public void testGetNetmaskShortFormInvalidSubnet2() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.getNetmaskShortForm("255.255.127.0");
            });
    }

    @Test
    public void testDottedQuad() {
        String result = NetworkUtil.dottedQuad(0xFFFFFFFF);
        assertEquals("255.255.255.255", result);

        result = NetworkUtil.dottedQuad(0xFFFFFF00);
        assertEquals("255.255.255.0", result);

        result = NetworkUtil.dottedQuad(0xFF120000);
        assertEquals("255.18.0.0", result);

        result = NetworkUtil.dottedQuad(0x80000000);
        assertEquals("128.0.0.0", result);

        result = NetworkUtil.dottedQuad(0x00000000);
        assertEquals("0.0.0.0", result);
    }

    @Test
    public void testConvertIp4Address() throws IllegalArgumentException {
        int result = NetworkUtil.convertIp4Address("255.255.255.255");
        assertEquals(0xFFFFFFFF, result);

        result = NetworkUtil.convertIp4Address("255.255.255.0");
        assertEquals(0xFFFFFF00, result);

        result = NetworkUtil.convertIp4Address("255.18.0.0");
        assertEquals(0xFF120000, result);

        result = NetworkUtil.convertIp4Address("128.0.0.0");
        assertEquals(0x80000000, result);

        result = NetworkUtil.convertIp4Address("0.0.0.0");
        assertEquals(0x00000000, result);
    }

    @Test
    public void testConvertIp4AddressNullAddress() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.convertIp4Address(null);
            });
    }

    @Test
    public void testConvertIp4AddressEmptyAddress() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.convertIp4Address("");
            });
    }

    @Test
    public void testConvertIp4AddressTooShortAddress() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.convertIp4Address("192.168.1");
            });
    }

    @Test
    public void testConvertIp4AddressTooLongAddress() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.convertIp4Address("192.168.1.123.1");
            });
    }

    @Test
    public void testConvertIp4AddressInvalidAddress() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.convertIp4Address("256.168.1.123");
            });
    }

    @Test
    public void testPackIp4AddressBytes() throws IllegalArgumentException {
        int result = NetworkUtil.packIp4AddressBytes(new short[] {255, 255, 255, 255});
        assertEquals(0xFFFFFFFF, result);

        result = NetworkUtil.packIp4AddressBytes(new short[] {255, 255, 255, 0});
        assertEquals(0xFFFFFF00, result);

        result = NetworkUtil.packIp4AddressBytes(new short[] {255, 255, 18, 0});
        assertEquals(0xFFFF1200, result);

        result = NetworkUtil.packIp4AddressBytes(new short[] {128, 0, 0, 0});
        assertEquals(0x80000000, result);

        result = NetworkUtil.packIp4AddressBytes(new short[] {0, 0, 0, 0});
        assertEquals(0x00000000, result);
    }

    @Test
    public void testPackIp4AddressBytesNullValue() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.packIp4AddressBytes(null);
            });
    }

    @Test
    public void testPackIp4AddressBytesEmptyValue() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.packIp4AddressBytes(new short[] {});
            });
    }

    @Test
    public void testPackIp4AddressBytesTooShortValue() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.packIp4AddressBytes(new short[] {192, 168, 1});
            });
    }

    @Test
    public void testPackIp4AddressBytesTooLongValue() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.packIp4AddressBytes(new short[] {192, 168, 1, 123, 1});
            });
    }

    @Test
    public void testPackIp4AddressBytesInvalidValue1() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.packIp4AddressBytes(new short[] {256, 168, 1, 123});
            });
    }

    @Test
    public void testPackIp4AddressBytesInvalidValue2() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.packIp4AddressBytes(new short[] {-1, 168, 1, 123});
            });
    }

    @Test
    public void testUnpackIP4AddressInt() {
        short[] result = NetworkUtil.unpackIP4AddressInt(0xFFFFFFFF);
        assertArrayEquals(new short[] {255, 255, 255, 255}, result);

        result = NetworkUtil.unpackIP4AddressInt(0xFFFFFF00);
        assertArrayEquals(new short[] {255, 255, 255, 0}, result);

        result = NetworkUtil.unpackIP4AddressInt(0xFFFF1200);
        assertArrayEquals(new short[] {255, 255, 18, 0}, result);

        result = NetworkUtil.unpackIP4AddressInt(0x80000000);
        assertArrayEquals(new short[] {128, 0, 0, 0}, result);

        result = NetworkUtil.unpackIP4AddressInt(0x00000000);
        assertArrayEquals(new short[] {0, 0, 0, 0}, result);
    }

    @Test
    public void testConvertIP6AddressStringFullFormat() throws IllegalArgumentException {
        byte[] result = NetworkUtil.convertIP6Address("2001:db8:85a3:0:0:8a2e:370:7334");
        byte[] expected = {
            0x20,
            0x01,
            0x0d,
            (byte) 0xb8,
            (byte) 0x85,
            (byte) 0xa3,
            0x00,
            0x00,
            0x00,
            0x00,
            (byte) 0x8a,
            0x2e,
            0x03,
            0x70,
            0x73,
            0x34
        };
        assertArrayEquals(expected, result);
    }

    @Test
    public void testConvertIP6AddressStringNullValue() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        String input = null;
        NetworkUtil.convertIP6Address(input);
            });
    }

    @Test
    public void testConvertIP6AddressStringEmptyValue() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.convertIP6Address("");
            });
    }

    @Test
    public void testConvertIP6AddressStringInvalidValue() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.convertIP6Address("g001:db8:85a3:0:0:8a2e:370:7334");
            });
    }

    @Test
    public void testConvertIP6AddressStringOutOfRangeValue1() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.convertIP6Address("12345:db8:85a3:0:0:8a2e:370:7334");
            });
    }

    @Test
    public void testConvertIP6AddressStringOutOfRangeValue2() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.convertIP6Address("-1:db8:85a3:0:0:8a2e:370:7334");
            });
    }

    @Test
    public void testConvertIP6AddressStringNotEnoughGroups() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.convertIP6Address("2001:db8:85a3:0:0:8a2e:370");
            });
    }

    @Test
    public void testConvertIP6AddressStringToManyGroups() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.convertIP6Address("2001:db8:85a3:0:0:8a2e:370:7334:7334");
            });
    }

    @Test
    public void testConvertIP6AddressByteArray() throws IllegalArgumentException {
        byte[] input = {
            0x20,
            0x01,
            0x0d,
            (byte) 0xb8,
            (byte) 0x85,
            (byte) 0xa3,
            0x00,
            0x00,
            0x00,
            0x00,
            (byte) 0x8a,
            0x2e,
            0x03,
            0x70,
            0x73,
            0x34
        };
        String result = NetworkUtil.convertIP6Address(input);
        assertEquals("2001:db8:85a3:0:0:8a2e:370:7334", result);
    }

    @Test
    public void testConvertIP6AddressByteArrayNullValue() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        byte[] input = null;
        NetworkUtil.convertIP6Address(input);
            });
    }

    @Test
    public void testConvertIP6AddressByteArrayEmptyValue() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.convertIP6Address(new byte[] {});
            });
    }

    @Test
    public void testConvertIP6AddressByteArrayNotEnoughElements() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        byte[] input = {
            0x20,
            0x01,
            0x0d,
            (byte) 0xb8,
            (byte) 0x85,
            (byte) 0xa3,
            0x00,
            0x00,
            0x00,
            0x00,
            (byte) 0x8a,
            0x2e,
            0x03,
            0x70,
            0x73
        };
        NetworkUtil.convertIP6Address(input);
            });
    }

    @Test
    public void testConvertIP6AddressByteArrayTooManyElements() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        byte[] input = {
            0x20,
            0x01,
            0x0d,
            (byte) 0xb8,
            (byte) 0x85,
            (byte) 0xa3,
            0x00,
            0x00,
            0x00,
            0x00,
            (byte) 0x8a,
            0x2e,
            0x03,
            0x70,
            0x73,
            0x34,
            0x34
        };
        NetworkUtil.convertIP6Address(input);
            });
    }

    @Test
    public void testMacToString() throws IllegalArgumentException {
        byte[] input = {0x01, 0x23, 0x45, 0x67, (byte) 0x89, (byte) 0xAB};
        String result = NetworkUtil.macToString(input);
        assertEquals("01:23:45:67:89:AB", result);
    }

    @Test
    public void testMacToStringNullValue() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.macToString(null);
            });
    }

    @Test
    public void testMacToStringEmptyValue() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.macToString(new byte[] {});
            });
    }

    @Test
    public void testMacToStringNotEnoughElements() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        byte[] input = {0x01, 0x23, 0x45, 0x67, (byte) 0x89};
        NetworkUtil.macToString(input);
            });
    }

    @Test
    public void testMacToStringTooManyElements() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        byte[] input = {0x01, 0x23, 0x45, 0x67, (byte) 0x89, (byte) 0xAB, 0x42};
        NetworkUtil.macToString(input);
            });
    }

    @Test
    public void testMacToBytes() throws IllegalArgumentException {
        byte[] result = NetworkUtil.macToBytes("01:23:45:67:89:AB");
        byte[] expected = {0x01, 0x23, 0x45, 0x67, (byte) 0x89, (byte) 0xAB};
        assertArrayEquals(expected, result);
    }

    @Test
    public void testMacToBytesNullValue() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.macToBytes(null);
            });
    }

    @Test
    public void testMacToBytesEmptyValue() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.macToBytes("");
            });
    }

    @Test
    public void testMacToBytesInvalidValue1() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.macToBytes("g1:23:45:67:89:AB");
            });
    }

    @Test
    public void testMacToBytesInvalidValue2() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.macToBytes("01::45:67:89:AB");
            });
    }

    @Test
    public void testMacToBytesNotEnoughElements() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.macToBytes("01:23:45:67:89");
            });
    }

    @Test
    public void testMacToBytesTooManyElements() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.macToBytes("01:23:45:67:89:AB:42");
            });
    }

    @Test
    public void testMacToBytesOutOfRangeValue() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> {
        NetworkUtil.macToBytes("101:23:45:67:89:AB");
            });
    }
}
