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

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;

import org.eclipse.kura.executor.Command;
import org.eclipse.kura.executor.CommandExecutorService;
import org.eclipse.kura.executor.CommandStatus;
import org.eclipse.kura.executor.ExitStatus;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.parallel.ResourceLock;
import org.junit.jupiter.api.parallel.Resources;

@ResourceLock(Resources.SYSTEM_PROPERTIES)
class SystemAdminServiceTest {
    private String originalOs;
    private final SystemAdminServiceImpl service = new SystemAdminServiceImpl();
    private final CommandExecutorService executor = mock(CommandExecutorService.class);

    @BeforeEach
    void setUp() {
        this.originalOs = System.getProperty("os.name");
        System.setProperty("os.name", "Mac OS X");
        this.service.setExecutorService(this.executor);
    }

    @AfterEach
    void tearDown() {
        this.service.unsetExecutorService(this.executor);
        if (this.originalOs == null) {
            System.clearProperty("os.name");
        } else {
            System.setProperty("os.name", this.originalOs);
        }
    }

    @Test
    void testGetUptime() throws Exception {
        bootTime(System.currentTimeMillis() / 1000 - 30);
        assertTrue(Long.parseLong(this.service.getUptime()) > 0);
    }

    @Test
    void macUptimeConvertsBootSecondsToMilliseconds() throws Exception {
        long before = System.currentTimeMillis();
        long bootSeconds = before / 1000 - 30;
        bootTime(bootSeconds);
        long uptime = Long.parseLong(this.service.getUptime());
        long after = System.currentTimeMillis();
        long earliest = before - bootSeconds * 1000;
        long latest = after - bootSeconds * 1000;
        assertTrue(uptime >= earliest && uptime <= latest,
                () -> "Expected uptime between " + earliest + " and " + latest + " ms, got " + uptime);
    }

    private void bootTime(long seconds) throws Exception {
        ExitStatus exit = mock(ExitStatus.class);
        when(exit.isSuccessful()).thenReturn(true);
        when(this.executor.execute(any(Command.class))).thenAnswer(invocation -> {
            Command command = invocation.getArgument(0);
            CommandStatus status = new CommandStatus(command, exit);
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            output.write(("{ sec = " + seconds + ", usec = 0 } Fri Oct 9 16:00:00 2026\n")
                    .getBytes(StandardCharsets.UTF_8));
            status.setOutputStream(output);
            return status;
        });
    }
}
