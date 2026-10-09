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
 ******************************************************************************/
package org.eclipse.kura.core.system;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import java.io.*;
import java.util.Map;

import org.eclipse.kura.executor.CommandExecutorService;
import org.eclipse.kura.system.SystemService;
import org.eclipse.kura.system.InternetConnectionStatus;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class SystemServiceRuntimeTest extends SystemServiceTestBase {
    private SystemServiceImpl systemService;
    private final CommandExecutorService executorService = mock(CommandExecutorService.class);

    @BeforeEach
    void setup() throws Exception {
        this.systemService = resourceService(Map.of(
                SystemService.KEY_PLATFORM, "DevPlatform", SystemService.KEY_OS_DISTRO, "DevOsDitribution",
                SystemService.KEY_OS_DISTRO_VER, "DevOsDitributionVersion", SystemService.KEY_BIOS_VERSION, "test-bios",
                SystemService.KEY_DEVICE_NAME, "test-device", SystemService.KEY_FIRMWARE_VERSION, "test-firmware",
                SystemService.KEY_MODEL_ID, "test-model", SystemService.KEY_PART_NUMBER, "test-part",
                SystemService.KEY_KURA_TMP_DIR, this.directory.resolve("config").toString()));
        this.systemService.setExecutorService(this.executorService);
        activate(this.systemService);
    }

    @Test
    public void testGetPrimaryMacAddress() throws Exception {
        SystemServiceImpl mac = spy(systemService);
        doReturn(SystemService.OS_MAC_OSX).when(mac).getOsName();
        doReturn("en-test").when(mac).getPrimaryNetworkInterfaceName();
        org.eclipse.kura.executor.Command command = new org.eclipse.kura.executor.Command(new String[] { "ifconfig" });
        org.eclipse.kura.executor.ExitStatus exit = mock(org.eclipse.kura.executor.ExitStatus.class);
        when(exit.isSuccessful()).thenReturn(true);
        org.eclipse.kura.executor.CommandStatus status = new org.eclipse.kura.executor.CommandStatus(command, exit);
        java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream();
        output.write("en-test:\n\tether 00:11:22:33:44:55\n".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        status.setOutputStream(output);
        when(executorService.execute(any(org.eclipse.kura.executor.Command.class))).thenReturn(status);
        assertEquals("00:11:22:33:44:55", mac.getPrimaryMacAddress());
    }

    @Test
    public void testGetPlatform() {
        assertEquals("DevPlatform", this.systemService.getPlatform());
    }

    @Test
    public void testGetOsDistro() {
        assertEquals("DevOsDitribution", this.systemService.getOsDistro());
    }

    @Test
    public void testGetOsDistroVersion() {
        assertEquals("DevOsDitributionVersion", this.systemService.getOsDistroVersion());
    }

    @Test
    public void testGetOsArch() {
        String expected = System.getProperty("os.arch");
        String actual = systemService.getOsArch();

        assertNotNull(actual, "getOsArch() not null");
        assertEquals(expected, actual, "getOsArch() value");
    }

    @Test
    public void testGetOsName() {
        String expected = System.getProperty("os.name");

        String actual = systemService.getOsName();

        assertNotNull(actual, "getOsName() not null");
        assertEquals(expected, actual, "getOsName() value");
    }

    @Test
    public void testGetOsVersion() throws IOException {
        String osVersion = System.getProperty("os.version");
        StringBuilder sbOsVersion = new StringBuilder();
        sbOsVersion.append(osVersion);

        File linuxKernelVersion = null;
        linuxKernelVersion = new File("/proc/sys/kernel/version");
        if (linuxKernelVersion.exists()) {
            StringBuilder kernelVersionData = new StringBuilder();
            try (FileReader fr = new FileReader(linuxKernelVersion); BufferedReader in = new BufferedReader(fr)) {
                String tempLine = null;
                while ((tempLine = in.readLine()) != null) {
                    kernelVersionData.append(" ");
                    kernelVersionData.append(tempLine);
                }
                sbOsVersion.append(kernelVersionData.toString());
            }
        }

        String expected = sbOsVersion.toString();
        String actual = systemService.getOsVersion();

        assertNotNull(actual, "getOsVersion() not null");
        assertEquals(expected, actual, "getOsVersion() value");
    }

    @Test
    public void testGetJavaVersion() {
        String expected = System.getProperty("java.runtime.version");
        String actual = systemService.getJavaVersion();

        assertNotNull(actual, "getJavaVersion() not null");
        assertEquals(expected, actual, "getJavaVersion() value");
    }

    @Test
    public void testGetJavaVmName() {
        String expected = System.getProperty("java.vm.name");
        String actual = systemService.getJavaVmName();

        assertNotNull(actual, "getJavaVmName() not null");
        assertEquals(expected, actual, "getJavaVmName() value");
    }

    @Test
    public void testGetJavaVmVersion() {
        String expected = System.getProperty("java.vm.version");
        String actual = systemService.getJavaVmVersion();

        assertNotNull(actual, "getJavaVmVersion() not null");
        assertEquals(expected, actual, "getJavaVmVersion() value");
    }

    @Test
    public void shouldReturnJavaVmVendor() {
        assertNotNull(systemService.getJavaVmVendor());
    }

    @Test
    public void shouldReturnJdkVendorVersion() {
        assertEquals(System.getProperty(SystemService.KEY_JDK_VENDOR_VERSION), systemService.getJdkVendorVersion());
    }

    @Test
    public void testGetFileSeparator() {
        String expected = System.getProperty("file.separator");
        String actual = systemService.getFileSeparator();

        assertNotNull(actual, "getFileSeparator() not null");
        assertEquals(expected, actual, "getFileSeparator() value");
    }

    @Test
    public void testJavaHome() {
        String actual = systemService.getJavaHome();
        assertNotNull(actual, "getJavaHome() not null");
    }

    @Test
    public void testKuraTemporaryConfigDirectory() {
        assertEquals(this.directory.resolve("config").toString(), this.systemService.getKuraTemporaryConfigDirectory());
    }

    @Test
    public void testGetBiosVersion() {
        assertEquals("test-bios", this.systemService.getBiosVersion());
    }

    @Test
    public void getDeviceName() {
        assertEquals("test-device", this.systemService.getDeviceName());
    }

    @Test
    public void getFirmwareVersion() {
        assertEquals("test-firmware", this.systemService.getFirmwareVersion());
    }

    @Test
    public void getModelId() {
        assertEquals("test-model", this.systemService.getModelId());
    }

    @Test
    public void getPartNumber() {
        assertEquals("test-part", this.systemService.getPartNumber());
    }

    @Test
    public void shouldGetDefaultLogManagerProperty() {
        assertFalse(systemService.getDefaultLogManager().isPresent());
    }

    @Test
    public void shouldGetDefaultWPA3WifiSecuritySupportProperty() {
        assertFalse(systemService.isWPA3WifiSecurityEnabled());
    }

    @Test
    public void shouldGetDefaultNetworkConfigurationTimeoutProperty() {
        assertEquals(30, systemService.getNetworkConfigurationTimeout());
    }

    @Test
    public void shouldNotBeConnectedToInternet() {
        assertEquals(InternetConnectionStatus.UNAVAILABLE, systemService.getInternetConnectionStatus());
    }

    @Test
    public void shouldGetDefaultInternetConnectionStatusCheckHost() {
        assertEquals("eclipse.org", systemService.getInternetConnectionStatusCheckHost());
    }

    @Test
    public void shouldGetDefaultInternetConnectionStatusCheckIp() {
        assertEquals("198.41.30.198", systemService.getInternetConnectionStatusCheckIp());
    }
}
