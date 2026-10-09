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

public class CommandTerminationTest {

    private CommandExecutorService executor;
    private static Pid pid = new LinuxPid(1234);
    private static String[] commandLine = { "find", "/", "-name", "foo" };
    private boolean isStopped;
    private boolean isKilled;


        public static Collection<CommandExecutorService> getExecutors() {
        return Arrays.asList(new UnprivilegedExecutorServiceImpl(),
                new PrivilegedExecutorServiceImpl());
    }

    @ParameterizedTest
    @MethodSource("getExecutors")
    public void shouldStopCommand(CommandExecutorService executor) {
        this.executor = executor;
        givenCommandExecutor();

        whenStopCommand(pid, null);

        thenCommandIsStopped();
    }

    @ParameterizedTest
    @MethodSource("getExecutors")
    public void shouldNotStopCommandWithSignal(CommandExecutorService executor) {
        this.executor = executor;
        givenCommandExecutor();

        whenStopCommand(pid, LinuxSignal.SIGHUP);

        thenCommandIsNotStopped();
    }

    @ParameterizedTest
    @MethodSource("getExecutors")
    public void shouldKillCommand(CommandExecutorService executor) {
        this.executor = executor;
        givenCommandExecutor();

        whenKillCommand(commandLine, null);

        thenCommandIsKilled();
    }

    @ParameterizedTest
    @MethodSource("getExecutors")
    public void shouldNotKillCommandWithSignal(CommandExecutorService executor) {
        this.executor = executor;
        givenCommandExecutor();

        whenKillCommand(commandLine, LinuxSignal.SIGHUP);

        thenCommandIsNotKilled();
    }

    private void givenCommandExecutor() {
        ExecutorUtil euMock = mock(ExecutorUtil.class);
        when(euMock.stopPrivileged(pid, LinuxSignal.SIGTERM)).thenReturn(true);
        when(euMock.stopPrivileged(pid, LinuxSignal.SIGHUP)).thenReturn(false);
        when(euMock.killPrivileged(commandLine, LinuxSignal.SIGTERM)).thenReturn(true);
        when(euMock.killPrivileged(commandLine, LinuxSignal.SIGHUP)).thenReturn(false);
        when(euMock.stopUnprivileged(pid, LinuxSignal.SIGTERM)).thenReturn(true);
        when(euMock.stopUnprivileged(pid, LinuxSignal.SIGHUP)).thenReturn(false);
        when(euMock.killUnprivileged(commandLine, LinuxSignal.SIGTERM)).thenReturn(true);
        when(euMock.killUnprivileged(commandLine, LinuxSignal.SIGHUP)).thenReturn(false);
        try {
            TestUtil.setFieldValue(executor, "executorUtil", euMock);
        } catch (NoSuchFieldException e) {
            throw new AssertionError(e);
        }
    }

    private void whenStopCommand(Pid pid, LinuxSignal signal) {
        this.isStopped = executor.stop(pid, signal);
    }

    private void whenKillCommand(String[] commandLine, LinuxSignal signal) {
        this.isKilled = executor.kill(commandLine, signal);
    }

    private void thenCommandIsStopped() {
        assertTrue(this.isStopped);
    }

    private void thenCommandIsNotStopped() {
        assertFalse(this.isStopped);
    }

    private void thenCommandIsKilled() {
        assertTrue(this.isKilled);
    }

    private void thenCommandIsNotKilled() {
        assertFalse(this.isKilled);
    }
}
