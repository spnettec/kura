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
import static org.mockito.Mockito.*;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Properties;

import org.eclipse.kura.KuraProcessExecutionErrorException;
import org.eclipse.kura.executor.Command;
import org.eclipse.kura.executor.CommandExecutorService;
import org.eclipse.kura.executor.CommandStatus;
import org.eclipse.kura.executor.ExitStatus;
import org.eclipse.kura.system.SystemResourceInfo;
import org.eclipse.kura.system.SystemResourceType;
import org.eclipse.kura.system.SystemService;
import org.junit.jupiter.api.Test;

class SystemServiceTest extends SystemServiceTestBase {

    @Test
    void testActivateWithExplicitPropertyFiles() throws Exception {
        Path defaults = this.directory.resolve("defaults.properties");
        Path custom = this.directory.resolve("custom.properties");
        writeProperties(defaults, custom);
        System.setProperty(SystemService.KURA_CONFIG, defaults.toUri().toString());
        System.setProperty(SystemService.KURA_CUSTOM_CONFIG, custom.toUri().toString());
        SystemServiceImpl service = fileService();
        activate(service);
        assertPropertyLayers(service);
    }

    @Test
    void testActivateWithHomePropertyValues() throws Exception {
        Path framework = Files.createDirectory(this.directory.resolve("framework"));
        Path user = Files.createDirectory(this.directory.resolve("user"));
        writeProperties(framework.resolve("kura.properties"), user.resolve("kura_custom.properties"));
        System.setProperty(SystemService.KEY_KURA_HOME_DIR, this.directory.toString());
        System.setProperty(SystemService.KEY_KURA_FRAMEWORK_CONFIG_DIR, framework.toString());
        System.setProperty(SystemService.KEY_KURA_USER_CONFIG_DIR, user.toString());
        SystemServiceImpl service = fileService();
        activate(service);
        assertPropertyLayers(service);
    }

    @Test
    void testActivateAllProperties() throws Exception {
        List<String> keys = List.of(
                SystemService.KEY_KURA_NAME,
                SystemService.KEY_DEVICE_NAME,
                SystemService.KEY_PLATFORM,
                SystemService.KEY_MODEL_ID,
                SystemService.KEY_MODEL_NAME,
                SystemService.KEY_PART_NUMBER,
                SystemService.KEY_SERIAL_NUM,
                SystemService.KEY_BIOS_VERSION,
                SystemService.KEY_FIRMWARE_VERSION,
                SystemService.KEY_PRIMARY_NET_IFACE,
                SystemService.KEY_KURA_DATA_DIR,
                SystemService.KEY_KURA_SNAPSHOTS_COUNT,
                SystemService.KEY_KURA_HAVE_NET_ADMIN,
                SystemService.KEY_KURA_HAVE_WEB_INTER,
                SystemService.KEY_KURA_STYLE_DIR,
                SystemService.KEY_KURA_WIFI_TOP_CHANNEL,
                SystemService.KEY_KURA_KEY_STORE_PWD,
                SystemService.KEY_KURA_TRUST_STORE_PWD,
                SystemService.KEY_FILE_COMMAND_ZIP_MAX_SIZE,
                SystemService.KEY_FILE_COMMAND_ZIP_MAX_NUMBER,
                SystemService.KEY_OS_DISTRO,
                SystemService.KEY_OS_DISTRO_VER,
                SystemService.CONFIG_CONSOLE_DEVICE_MANAGE_SERVICE_IGNORE,
                SystemService.DB_URL_PROPNAME,
                SystemService.DB_CACHE_ROWS_PROPNAME,
                SystemService.DB_LOB_FILE_PROPNAME,
                SystemService.DB_DEFRAG_LIMIT_PROPNAME,
                SystemService.DB_LOG_DATA_PROPNAME,
                SystemService.DB_LOG_SIZE_PROPNAME,
                SystemService.DB_NIO_PROPNAME,
                SystemService.DB_WRITE_DELAY_MILLIES_PROPNAME);
        for (String key : keys) { System.setProperty(key, "override:" + key); }
        SystemServiceImpl service = resourceService(Map.of());
        activate(service);
        for (String key : keys) { assertEquals("override:" + key, service.getProperties().getProperty(key), key); }
    }

    @Test
    public void testGetSystemPackages() throws IOException, KuraProcessExecutionErrorException {
        CommandExecutorService cesMock = mock(CommandExecutorService.class);

        Command dpkgCommand = new Command(new String[] { "dpkg-query", "-W" });
        dpkgCommand.setExecuteInAShell(true);
        CommandStatus dpkgSuccessfulStatus = new CommandStatus(dpkgCommand, status(true));
        dpkgSuccessfulStatus.setOutputStream(writeToOutputStream("package1 1.0.0\npackage2"));
        when(cesMock.execute(dpkgCommand)).thenReturn(dpkgSuccessfulStatus);

        Command rpmCommand = new Command(
                new String[] { "rpm", "-qa", "--queryformat", "'%{NAME} %{VERSION}-%{RELEASE}\n'" });
        rpmCommand.setExecuteInAShell(true);
        CommandStatus rpmSuccessfulStatus = new CommandStatus(rpmCommand, status(true));
        rpmSuccessfulStatus.setOutputStream(writeToOutputStream("package3 2.0.0\npackage4"));
        when(cesMock.execute(rpmCommand)).thenReturn(rpmSuccessfulStatus);

        Command apkCommand = new Command(new String[] { "apk", "list", "-I", "|", "awk", "'{ print $1 }'" });
        apkCommand.setExecuteInAShell(true);
        CommandStatus apkSuccessfulStatus = new CommandStatus(apkCommand, status(true));
        apkSuccessfulStatus.setOutputStream(writeToOutputStream("dos2unix-7.4.1-r0\nkmod-26-r0"));
        when(cesMock.execute(apkCommand)).thenReturn(apkSuccessfulStatus);

        SystemServiceImpl systemService = new SystemServiceImpl();
        systemService.setExecutorService(cesMock);

        List<SystemResourceInfo> packages = systemService.getSystemPackages();
        assertFalse(packages.isEmpty());
        assertEquals(6, packages.size());
        assertEquals("package1", packages.get(0).getName());
        assertEquals("1.0.0", packages.get(0).getVersion());
        assertEquals(SystemResourceType.DEB, packages.get(0).getType());
        assertEquals("package2", packages.get(1).getName());
        assertEquals(SystemResourceType.DEB, packages.get(1).getType());
        assertEquals("package3", packages.get(2).getName());
        assertEquals("2.0.0", packages.get(2).getVersion());
        assertEquals(SystemResourceType.RPM, packages.get(2).getType());
        assertEquals("package4", packages.get(3).getName());
        assertEquals(SystemResourceType.RPM, packages.get(3).getType());
        assertEquals(SystemResourceType.APK, packages.get(4).getType());
        assertEquals("dos2unix", packages.get(4).getName());
        assertEquals("7.4.1-r0", packages.get(4).getVersion());
        assertEquals("kmod", packages.get(5).getName());
        assertEquals("26-r0", packages.get(5).getVersion());
    }

    @Test
    public void testgGetSystemPackagesFailed() throws KuraProcessExecutionErrorException {

        CommandExecutorService cesMock = mock(CommandExecutorService.class);

        Command dpkgCommand = new Command(new String[] { "dpkg-query", "-W" });
        dpkgCommand.setExecuteInAShell(true);
        CommandStatus unSuccessfulStatus = new CommandStatus(dpkgCommand, status(false));
        when(cesMock.execute(dpkgCommand)).thenReturn(unSuccessfulStatus);

        Command rpmCommand = new Command(
                new String[] { "rpm", "-qa", "--queryformat", "'%{NAME} %{VERSION}-%{RELEASE}\n'" });
        rpmCommand.setExecuteInAShell(true);
        when(cesMock.execute(rpmCommand)).thenReturn(unSuccessfulStatus);

        Command apkCommand = new Command(new String[] { "apk", "list", "-I", "|", "awk", "'{ print $1 }'" });
        apkCommand.setExecuteInAShell(true);
        when(cesMock.execute(apkCommand)).thenReturn(unSuccessfulStatus);

        SystemServiceImpl systemService = new SystemServiceImpl();
        systemService.setExecutorService(cesMock);

        assertThrows(KuraProcessExecutionErrorException.class, systemService::getSystemPackages);
    }

    private static ExitStatus status(boolean success) {
        ExitStatus status = mock(ExitStatus.class);
        when(status.isSuccessful()).thenReturn(success);
        when(status.getExitCode()).thenReturn(success ? 0 : 1);
        return status;
    }

    private static ByteArrayOutputStream writeToOutputStream(String data) throws IOException {
        ByteArrayOutputStream result = new ByteArrayOutputStream();
        result.write(data.getBytes(StandardCharsets.UTF_8));
        return result;
    }

    private void writeProperties(Path defaults, Path custom) throws IOException {
        Files.writeString(defaults, "property.proper=proper value\n" + SystemService.KEY_KURA_VERSION + "=base version\n");
        Files.writeString(custom, "property.custom=custom value\n" + SystemService.KEY_KURA_VERSION + "=custom version\n");
    }

    private void assertPropertyLayers(SystemServiceImpl service) {
        Properties properties = service.getProperties();
        assertFalse(properties.containsKey("property.proper"));
        assertFalse(properties.containsKey("property.custom"));
        assertEquals("proper value", properties.getProperty("property.proper"));
        assertEquals("custom value", properties.getProperty("property.custom"));
        assertEquals("custom version", service.getKuraVersion());
    }

}
