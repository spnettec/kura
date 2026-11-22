/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.internal.linux.executor;

import static java.nio.charset.StandardCharsets.UTF_8;

import java.io.ByteArrayOutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import org.eclipse.kura.executor.Command;
import org.eclipse.kura.executor.CommandStatus;

/** Invoked only by the disposable, cap-constrained Linux container fixture. */
public final class UnprivilegedExecutorLinuxProbe {

    private static void check(boolean value, String message) {
        if (!value) {
            throw new AssertionError(message);
        }
    }

    private static Command command(String... arguments) {
        Command command = new Command(arguments);
        command.setOutputStream(new ByteArrayOutputStream());
        command.setErrorStream(new ByteArrayOutputStream());
        return command;
    }

    private static String output(CommandStatus status) {
        return status.getOutputStream().toString();
    }

    public static void main(String[] arguments) throws Exception {
        check(arguments.length == 3, "Expected admission, username, uid");
        boolean expected = Boolean.parseBoolean(arguments[0]);
        String username = arguments[1];
        check(UnprivilegedProcessIdentity.isCurrentUser(username) == expected, "Kernel admission differs");
        if (expected) {
            ExecutorUtil executor = new ExecutorUtil(username);
            CommandStatus id = executor.executeUnprivileged(command("/usr/bin/id", "-u"));
            check(id.getExitStatus().isSuccessful() && output(id).trim().equals(arguments[2]), "Identity changed");
            Path directory = Files.createTempDirectory("kura-executor-probe-");
            Path marker = directory.resolve("must-not-exist");
            String literal = "space ' \" $HOME\n$(touch " + marker + ")";
            Command values = command("/bin/sh", "-c", "printf '<%s><%s><%s>' \"$1\" \"$2\" \"$PROBE\"", "probe", literal, "");
            values.setEnvironment(Map.of("PROBE", literal, "PATH", "/requested-path-without-tools"));
            values.setDirectory(directory.toString());
            CommandStatus valueStatus = executor.executeUnprivileged(values);
            check(valueStatus.getExitStatus().isSuccessful(), "Literal command failed");
            check(output(valueStatus).equals("<" + literal + "><><" + literal + ">"), "Arguments or environment changed");
            check(!Files.exists(marker), "Command data was executed");
            Command cwd = command("/bin/pwd");
            cwd.setDirectory(directory.toString());
            check(output(executor.executeUnprivileged(cwd)).trim().equals(directory.toString()), "Working directory changed");
            Command pipeline = command("printf shell | /usr/bin/tr a-z A-Z");
            pipeline.setExecuteInAShell(true);
            CommandStatus shell = executor.executeUnprivileged(pipeline);
            check(shell.getExitStatus().isSuccessful() && output(shell).equals("SHELL"), "Explicit shell failed");
            Command sleep = command("/bin/sleep", "3");
            sleep.setTimeout(1);
            check(!executor.executeUnprivileged(sleep).getExitStatus().isSuccessful(), "Timeout did not fail");
            CountDownLatch completed = new CountDownLatch(1);
            AtomicInteger callbacks = new AtomicInteger();
            executor.executeUnprivileged(command("/usr/bin/id", "-u"), status -> {
                check(status.getExitStatus().isSuccessful() && output(status).trim().equals(arguments[2]), "Async identity changed");
                callbacks.incrementAndGet();
                completed.countDown();
            });
            check(completed.await(5, TimeUnit.SECONDS) && callbacks.get() == 1, "Async completion missing or repeated");
            Files.delete(directory);
        }
        String status = Files.readString(Path.of("/proc/self/status"), UTF_8);
        System.out.println("ADMISSION=" + expected + " KERNEL_USER=" + ProcessHandle.current().info().user().orElse("absent"));
        status.lines().filter(line -> line.matches("^(Uid|Gid|Groups|CapInh|CapPrm|CapEff|CapBnd|CapAmb|NoNewPrivs):.*"))
                .forEach(System.out::println);
    }
}
