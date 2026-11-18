/*******************************************************************************
 * Copyright (c) 2021, 2026 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.linux.clock;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

import org.apache.commons.io.IOUtils;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.core.linux.executor.LinuxExitStatus;
import org.eclipse.kura.core.util.IOUtil;
import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.executor.Command;
import org.eclipse.kura.executor.CommandExecutorService;
import org.eclipse.kura.executor.CommandStatus;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

public class ChronyClockSyncProviderTest {

    @Test
    public void testSynch() throws Exception {

        InputStream journalEntry = new ByteArrayInputStream(
                IOUtil.readResource("journal-entry.json").getBytes(StandardCharsets.UTF_8));
        OutputStream statusOutputStream = new ByteArrayOutputStream();
        IOUtils.copy(journalEntry, statusOutputStream);

        CommandStatus successFullStatus = new CommandStatus(new Command(new String[] {}), new LinuxExitStatus(0));
        successFullStatus.setOutputStream(statusOutputStream);

        CommandExecutorService commandExecutorMock = mock(CommandExecutorService.class);
        when(commandExecutorMock.execute(any())).thenReturn(successFullStatus);

        CryptoService cryptoServiceMock = mock(CryptoService.class);
        when(cryptoServiceMock.sha256Hash(any())).thenReturn("");

        ClockPrivilegeClient broker = mock(ClockPrivilegeClient.class);
        when(broker.inspectChrony()).thenReturn(new ClockPrivilegeClient.ChronyStatus("chrony.service", true));
        ChronyClockSyncProvider ntsClockSyncProvider = new ChronyClockSyncProvider(commandExecutorMock,
                cryptoServiceMock, broker);
        AtomicBoolean invoked = new AtomicBoolean(false);
        ClockSyncListener listener = (offset, update) -> {
            assertEquals(0, offset);

            invoked.set(true);
        };

        Map<String, Object> properties = new HashMap<>();
        properties.put("enabled", true);
        properties.put("clock.provider", "chrony-advanced");
        properties.put("chrony.advanced.configlocation", "placeholder_path");
        ClockServiceConfig clockServiceConfig = new ClockServiceConfig(properties);

        ntsClockSyncProvider.init(clockServiceConfig, null, listener);

        boolean synched = ntsClockSyncProvider.syncClock();

        assertTrue(synched);
        assertTrue(invoked.get());
        ArgumentCaptor<Command> calls = ArgumentCaptor.forClass(Command.class);
        verify(commandExecutorMock, times(2)).execute(calls.capture());
        Command read = calls.getAllValues().get(1);
        assertEquals("/usr/bin/journalctl", read.getCommandLine()[0]);
        assertTrue(Arrays.asList(read.getCommandLine()).contains("--grep=System clock was stepped by"));
        assertFalse(read.isExecutedInAShell());
    }

    @Test
    void serviceSwitchBetweenInitAndStartDoesNotDispatchAnyCommand() throws Exception {
        CommandExecutorService executor = mock(CommandExecutorService.class);
        ClockPrivilegeClient broker = mock(ClockPrivilegeClient.class);
        when(broker.inspectChrony()).thenReturn(new ClockPrivilegeClient.ChronyStatus("chrony.service", false),
                new ClockPrivilegeClient.ChronyStatus("chronyd.service", true));
        ChronyClockSyncProvider provider = new ChronyClockSyncProvider(executor, mock(CryptoService.class), broker);
        provider.init(new ClockServiceConfig(Map.of()), null, (offset, update) -> {});
        assertThrows(KuraException.class, provider::start);
        verifyNoInteractions(executor);
    }
}
