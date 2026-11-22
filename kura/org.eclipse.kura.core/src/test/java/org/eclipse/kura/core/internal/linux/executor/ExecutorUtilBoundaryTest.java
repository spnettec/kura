/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.internal.linux.executor;

import static org.junit.jupiter.api.Assertions.*;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import org.apache.commons.exec.CommandLine;
import org.apache.commons.exec.DefaultExecutor;
import org.apache.commons.exec.Executor;
import org.eclipse.kura.executor.Command;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class ExecutorUtilBoundaryTest {
    @TempDir Path directory;

    static class Capture extends ExecutorUtil {
        CommandLine line;
        int calls;
        Capture() { super("kura"); }
        @Override protected Executor getExecutor() {
            return new DefaultExecutor() {
                @Override public int execute(CommandLine command) {
                    line=command;calls++;return 0;
                }
                @Override public int execute(CommandLine command, Map<String,String> environment) {
                    throw new AssertionError("Unprivileged launch must not receive request environment");
                }
            };
        }
    }

    Command command(String... args) {
        Command command=new Command(args);
        command.setOutputStream(new ByteArrayOutputStream());
        command.setErrorStream(new ByteArrayOutputStream());
        return command;
    }

    String script(Capture capture, Command command) {
        assertEquals(0,capture.executeUnprivileged(command).getExitStatus().getExitCode());
        assertEquals("/usr/bin/su",capture.line.getExecutable());
        String[] args=capture.line.getArguments();
        assertEquals(5,args.length);
        assertEquals("--shell=/bin/sh",args[0]);assertEquals("--command",args[1]);
        assertEquals("--",args[3]);assertEquals(capture.getCommandUsername(),args[4]);
        return args[2];
    }

    String runPayload(String script) throws Exception {
        Process process=new ProcessBuilder("/bin/sh","-c",script).start();
        String out=new String(process.getInputStream().readAllBytes(),StandardCharsets.UTF_8);
        String err=new String(process.getErrorStream().readAllBytes(),StandardCharsets.UTF_8);
        assertEquals(0,process.waitFor(),err);return out;
    }

    @Test void literalArgumentsAreData() throws Exception {
        Path marker=directory.resolve("must-not-exist");
        String[] values={"space value","", "single'quote", "double\"quote", "line\nbreak",
            "$(touch "+marker+")", "`touch "+marker+"`", "; touch "+marker, "*", "$HOME", "--option"};
        String[] args=new String[values.length+4];args[0]="/bin/sh";args[1]="-c";
        args[2]="for arg do printf '<%s>' \"$arg\"; done";args[3]="probe";
        System.arraycopy(values,0,args,4,values.length);
        StringBuilder expected=new StringBuilder();for(String value:values)expected.append('<').append(value).append('>');
        assertEquals(expected.toString(),runPayload(script(new Capture(),command(args))));
        assertFalse(Files.exists(marker));
    }

    @Test void explicitShellModeStillSupportsPipelines() throws Exception {
        Command c=command("printf '%s' shell | tr a-z A-Z");c.setExecuteInAShell(true);
        assertEquals("SHELL",runPayload(script(new Capture(),c)));
    }

    @Test void environmentIsAppliedOnlyInsideTargetPayload() throws Exception {
        Path marker=directory.resolve("environment-must-not-execute");
        String value="space ' \" $(touch "+marker+") ; $HOME\nnext";
        Command c=command("/bin/sh","-c","printf '%s' \"$PROBE\"");
        c.setEnvironment(Map.of("PROBE",value,"HOME","requested home","PATH","/usr/bin:/bin"));
        assertEquals(value,runPayload(script(new Capture(),c)));assertFalse(Files.exists(marker));
    }

    @Test void executableContainingEqualsRemainsExecutable() throws Exception {
        Path file=directory.resolve("probe=one with space");Files.writeString(file,"#!/bin/sh\nprintf '%s' executable-ok\n");
        assertTrue(file.toFile().setExecutable(true,true));
        assertEquals("executable-ok",runPayload(script(new Capture(),command(file.toString()))));
    }

    @Test void usernameIsOneOperandAfterOptionTerminator() {
        Capture capture=new Capture();capture.setCommandUsername("--preserve-environment");
        script(capture,command("/bin/true"));
    }

    @Test void positiveTimeoutUsesFixedBinaryAndDefaultSignal() {
        Command c=command("/bin/true");c.setTimeout(7);
        String value=script(new Capture(),c);
        assertTrue(value.contains("'/usr/bin/timeout' '--signal=15' '--' '7'"));
    }

    @Test void zeroAndNegativeTimeoutsRemainUnlimited() {
        for(int timeout:new int[]{0,-1,-2}) {
            Command c=command("/bin/true");c.setTimeout(timeout);
            assertFalse(script(new Capture(),c).contains("/usr/bin/timeout"));
        }
    }

    @Test void invalidArgumentsFailBeforeProcessCreation() {
        for(String[] args:new String[][]{null,{}, {""},{"/bin/true",null},{"/bin/true","bad\0argument"}}) {
            Capture capture=new Capture();Command c=new Command(args);
            assertEquals(1,capture.executeUnprivileged(c).getExitStatus().getExitCode());assertEquals(0,capture.calls);
        }
    }

    @Test void invalidEnvironmentFailsBeforeProcessCreation() {
        for(String name:new String[]{"","BAD=NAME","bad\0name"}) {
            Capture capture=new Capture();Command c=command("/bin/true");c.setEnvironment(Map.of(name,"secret"));
            assertEquals(1,capture.executeUnprivileged(c).getExitStatus().getExitCode());assertEquals(0,capture.calls);
            assertFalse(c.getErrorStream().toString().contains("secret"));
        }
    }

    @Test void invalidAsyncInputCallsBackOnceWithoutLaunch() {
        Capture capture=new Capture();AtomicInteger callbacks=new AtomicInteger();
        Command c=command("/bin/true","invalid\0argument");
        capture.executeUnprivileged(c,status->{assertEquals(1,status.getExitStatus().getExitCode());callbacks.incrementAndGet();});
        assertEquals(1,callbacks.get());assertEquals(0,capture.calls);
    }
}
