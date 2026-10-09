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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.io.ByteArrayOutputStream;
import java.util.Arrays;
import java.util.Collection;
import java.util.function.Consumer;

import org.apache.commons.io.Charsets;
import org.eclipse.kura.core.internal.linux.executor.ExecutorUtil;
import org.eclipse.kura.core.linux.executor.privileged.PrivilegedExecutorServiceImpl;
import org.eclipse.kura.core.linux.executor.unprivileged.UnprivilegedExecutorServiceImpl;
import org.eclipse.kura.core.testutil.TestUtil;
import org.eclipse.kura.executor.Command;
import org.eclipse.kura.executor.CommandExecutorService;
import org.eclipse.kura.executor.CommandStatus;
import org.eclipse.kura.system.SystemService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;

public class CommandExecutionTest {

    private CommandExecutorService executor;


        public static Collection<CommandExecutorService> getExecutors() {
        return Arrays.asList(new UnprivilegedExecutorServiceImpl(),
                new PrivilegedExecutorServiceImpl());
    }

    private Command command;
    private CommandStatus status;
    private Consumer<CommandStatus> callback = cs -> {
        this.status = cs;
    };

    @ParameterizedTest
    @MethodSource("getExecutors")
    public void shouldReturnErrorOnEmptyCommand(CommandExecutorService executor) {
        this.executor = executor;
        givenCommand(" ");
        givenCommandExecutor();

        whenCommandSyncExecuted();

        thenReturnExitValue(1);
        thenReturnErrorMessage("The commandLine cannot be empty or not defined");
    }

    @ParameterizedTest
    @MethodSource("getExecutors")
    public void shouldReturnSuccess(CommandExecutorService executor) {
        this.executor = executor;
        givenCommand("ls -all");
        givenCommandExecutor();

        whenCommandSyncExecuted();

        thenReturnExitValue(0);
    }

    @ParameterizedTest
    @MethodSource("getExecutors")
    public void shouldAcceptErrorOnEmptyCommand(CommandExecutorService executor) {
        this.executor = executor;
        givenCommand(" ");
        givenCommandExecutor();

        whenCommandAsyncExecuted(this.callback);

        thenReturnExitValue(1);
    }

    @ParameterizedTest
    @MethodSource("getExecutors")
    public void shouldAcceptSuccess(CommandExecutorService executor) {
        this.executor = executor;
        givenCommand("ls -all");
        givenCommandExecutor();

        whenCommandAsyncExecuted(this.callback);

        thenReturnExitValue(0);
    }

    private void givenCommandExecutor() {
        ExecutorUtil euMock = mock(ExecutorUtil.class);
        CommandStatus cs = new CommandStatus(this.command, new LinuxExitStatus(0));
        when(euMock.executePrivileged(this.command)).thenReturn(cs);
        when(euMock.executeUnprivileged(this.command)).thenReturn(cs);
        doAnswer(invocation -> {
            this.callback.accept(cs);
            return null;
        }).when(euMock).executePrivileged(this.command, this.callback);
        doAnswer(invocation -> {
            this.callback.accept(cs);
            return null;
        }).when(euMock).executeUnprivileged(this.command, this.callback);
        try {
            TestUtil.setFieldValue(executor, "executorUtil", euMock);
        } catch (NoSuchFieldException e) {
            throw new AssertionError(e);
        }
    }

    private void givenCommand(String commandLine) {
        this.command = new Command(commandLine.split(" "));
        this.command.setOutputStream(new ByteArrayOutputStream());
        this.command.setErrorStream(new ByteArrayOutputStream());
    }

    private void whenCommandSyncExecuted() {
        this.status = executor.execute(this.command);
    }

    private void whenCommandAsyncExecuted(Consumer<CommandStatus> callback) {
        executor.execute(this.command, callback);
    }

    private void thenReturnExitValue(int expectedExitValue) {
        assertEquals(expectedExitValue, this.status.getExitStatus().getExitCode());
    }

    private void thenReturnErrorMessage(String expectedErrorMessage) {
        assertEquals(expectedErrorMessage,
                new String(((ByteArrayOutputStream) this.status.getErrorStream()).toByteArray(), Charsets.UTF_8));
    }

}
