/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.linux.watchdog;

import static org.junit.jupiter.api.Assertions.*;
import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import com.sun.jna.NativeLong;
import com.sun.jna.ptr.IntByReference;

class LinuxWatchdogDeviceContractTest {
    private Field library;
    private Object previous;
    private int openResult = 7;
    private int writeResult = 1;
    private int ioctlResult;
    private int closeResult;
    private int closes;
    private final List<Byte> writes = new ArrayList<>();

    @BeforeEach
    void replaceNativeCallsWithARecordingProxy() throws Exception {
        library = LinuxWatchdogDevice.class.getDeclaredField("cLib");
        library.setAccessible(true);
        previous = library.get(null);
        Class<?> type = Class.forName(LinuxWatchdogDevice.class.getName() + "$CLib");
        Object proxy = Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[] { type }, (p, method, args) -> {
            switch (method.getName()) {
            case "open":
                assertEquals("owned-native-fixture", args[0]);
                return openResult;
            case "write":
                writes.add(((byte[]) args[1])[0]);
                assertEquals(1, ((NativeLong) args[2]).longValue());
                if (method.getReturnType().equals(NativeLong.class)) { return new NativeLong(writeResult); }
                return writeResult;
            case "ioctl":
                assertEquals(0x80045707L, ((NativeLong) args[1]).longValue());
                ((IntByReference) args[2]).setValue(30);
                return ioctlResult;
            case "close":
                closes++;
                return closeResult;
            default: throw new AssertionError("Unexpected native proxy call: " + method);
            }
        });
        library.set(null, proxy);
    }

    @AfterEach
    void restoreNativeBoundary() throws Exception {
        library.set(null, previous);
    }

    @Test
    void keepaliveDisarmTimeoutAndCloseUseTheExpectedNativeContract() throws Exception {
        WatchdogDevice device = LinuxWatchdogDevice.open("owned-native-fixture");
        device.keepAlive();
        assertEquals(30, device.getTimeout());
        device.disarm();
        device.close();
        device.close();
        assertEquals(List.of((byte) 'w', (byte) 'V'), writes);
        assertEquals(1, closes);
        assertThrows(IOException.class, device::keepAlive);
        assertThrows(IOException.class, device::getTimeout);
    }

    @Test
    void shortWriteCannotBeReportedAsASuccessfulKeepalive() throws Exception {
        WatchdogDevice device = LinuxWatchdogDevice.open("owned-native-fixture");
        writeResult = 0;
        assertThrows(IOException.class, device::keepAlive);
    }

    @Test
    void negativeOpenDoesNotCreateAnApparentlyOpenDevice() {
        openResult = -1;
        assertThrows(IOException.class, () -> LinuxWatchdogDevice.open("owned-native-fixture"));
    }

    @Test
    void failedIoctlDoesNotReturnAnApparentlyValidTimeout() throws Exception {
        WatchdogDevice device = LinuxWatchdogDevice.open("owned-native-fixture");
        ioctlResult = -1;
        assertThrows(IOException.class, device::getTimeout);
    }

    @Test
    void negativeCloseIsReportedAndNeverRetriedOnAReusedDescriptor() throws Exception {
        WatchdogDevice device = LinuxWatchdogDevice.open("owned-native-fixture");
        closeResult = -1;
        assertThrows(IOException.class, device::close);
        device.close();
        assertEquals(1, closes);
    }
}
