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
package org.eclipse.kura.core.linux.executor;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.util.Arrays;
import java.util.Collection;

import org.eclipse.kura.core.internal.linux.executor.ExecutorUtil;
import org.eclipse.kura.core.linux.executor.privileged.PrivilegedExecutorServiceImpl;
import org.eclipse.kura.core.linux.executor.unprivileged.UnprivilegedExecutorServiceImpl;
import org.eclipse.kura.core.testutil.TestUtil;
import org.eclipse.kura.executor.CommandExecutorService;
import org.eclipse.kura.executor.Pid;
import org.eclipse.kura.system.SystemService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;

public class CommandRunningTest {

    private CommandExecutorService executor;
    private static Pid pid = new LinuxPid(1234);
    private static String[] commandLine = { "find", "/", "-name", "foo" };
    private boolean isRunning;


        public static Collection<CommandExecutorService> getExecutors() {
        return Arrays.asList(new UnprivilegedExecutorServiceImpl(),
                new PrivilegedExecutorServiceImpl());
    }

    @ParameterizedTest
    @MethodSource("getExecutors")
    public void shouldBeRunningPid(CommandExecutorService executor) {
        this.executor = executor;
        givenCommandExecutor();

        whenCheckIfRunning(pid);

        thenCommandIsRunning();
    }

    @ParameterizedTest
    @MethodSource("getExecutors")
    public void shouldNotBeRunningCommandLine(CommandExecutorService executor) {
        this.executor = executor;
        givenCommandExecutor();

        whenCheckIfRunning(commandLine);

        thenCommandIsNotRunning();
    }

    private void givenCommandExecutor() {
        ExecutorUtil euMock = mock(ExecutorUtil.class);
        when(euMock.isRunning(pid)).thenReturn(true);
        when(euMock.isRunning(commandLine)).thenReturn(false);
        try {
            TestUtil.setFieldValue(executor, "executorUtil", euMock);
        } catch (NoSuchFieldException e) {
            throw new AssertionError(e);
        }
    }

    private void whenCheckIfRunning(Pid pid) {
        this.isRunning = executor.isRunning(pid);
    }

    private void whenCheckIfRunning(String[] commandLine) {
        this.isRunning = executor.isRunning(commandLine);
    }

    private void thenCommandIsRunning() {
        assertTrue(this.isRunning);
    }

    private void thenCommandIsNotRunning() {
        assertFalse(this.isRunning);
    }

}
