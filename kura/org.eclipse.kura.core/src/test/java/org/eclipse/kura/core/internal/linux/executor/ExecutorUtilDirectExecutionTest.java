/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.internal.linux.executor;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mockStatic;

import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import org.eclipse.kura.executor.Command;
import org.junit.jupiter.api.Test;
import org.mockito.MockedStatic;

class ExecutorUtilDirectExecutionTest {

    @Test
    void preservesArgumentsAndEnvironmentAfterKernelAdmission() {
        try (MockedStatic<UnprivilegedProcessIdentity> identity = mockStatic(UnprivilegedProcessIdentity.class)) {
            identity.when(() -> UnprivilegedProcessIdentity.isCurrentUser("kura")).thenReturn(true);
            ExecutorUtilBoundaryTest.Capture capture = new ExecutorUtilBoundaryTest.Capture();
            Command command = new Command(new String[] { "/bin/printf", "%s", "space ' \" $HOME\nvalue", "" });
            command.setEnvironment(Map.of("PROBE", "$(must-not-run)"));
            assertEquals(0, capture.executeUnprivileged(command).getExitStatus().getExitCode());
            assertEquals("/usr/bin/env", capture.line.getExecutable());
            assertArrayEquals(new String[] { "--", "PROBE=$(must-not-run)", "/bin/sh", "-c", "exec \"$@\"",
                    "kura-command", "/bin/printf", "%s", "space ' \" $HOME\nvalue", "" }, capture.line.getArguments());
            assertEquals(1, capture.calls);
        }
    }

    @Test
    void keepsExplicitShellAndFixedTimeoutArguments() {
        try (MockedStatic<UnprivilegedProcessIdentity> identity = mockStatic(UnprivilegedProcessIdentity.class)) {
            identity.when(() -> UnprivilegedProcessIdentity.isCurrentUser("kura")).thenReturn(true);
            ExecutorUtilBoundaryTest.Capture capture = new ExecutorUtilBoundaryTest.Capture();
            Command command = new Command(new String[] { "printf shell | tr a-z A-Z" });
            command.setExecuteInAShell(true);
            command.setTimeout(7);
            assertEquals(0, capture.executeUnprivileged(command).getExitStatus().getExitCode());
            assertArrayEquals(new String[] { "--", "/usr/bin/timeout", "--signal=15", "--", "7", "/bin/sh", "-c",
                    "printf shell | tr a-z A-Z" }, capture.line.getArguments());
        }
    }

    @Test
    void rejectsInvalidAsyncInputBeforeKernelAdmissionOrLaunch() {
        try (MockedStatic<UnprivilegedProcessIdentity> identity = mockStatic(UnprivilegedProcessIdentity.class)) {
            ExecutorUtilBoundaryTest.Capture capture = new ExecutorUtilBoundaryTest.Capture();
            AtomicInteger calls = new AtomicInteger();
            capture.executeUnprivileged(new Command(new String[] { "/bin/true", "bad\0argument" }), status -> {
                assertEquals(1, status.getExitStatus().getExitCode());
                calls.incrementAndGet();
            });
            assertEquals(1, calls.get());
            assertEquals(0, capture.calls);
            identity.verifyNoInteractions();
        }
    }
}
