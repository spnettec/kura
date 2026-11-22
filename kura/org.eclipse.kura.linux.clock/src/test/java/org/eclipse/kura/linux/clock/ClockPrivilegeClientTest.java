/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.linux.clock;

import static java.nio.charset.StandardCharsets.US_ASCII;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.concurrent.TimeUnit;

import org.junit.jupiter.api.Test;

class ClockPrivilegeClientTest {

    private static final long SAMPLE = 500L;
    private static final String APPLIED = "{\"schema\":1,\"namespace\":\"352c852f-4125-4491-8b6e-3aeb3c624ed1\","
            + "\"requestId\":\"98682ee6-54e5-4593-aa16-ee775d482401\",\"correctionMillis\":500,"
            + "\"state\":\"APPLIED\",\"reason\":\"CLOCK_SET_RETURNED\",\"currentSample\":true}";
    private static final String RTC_APPLIED = APPLIED.replace("\"correctionMillis\":500", "\"rtcDevice\":\"/dev/rtc4\"")
            .replace("CLOCK_SET_RETURNED", "RTC_SET_RETURNED");

    @Test
    void acceptsOnlyAppliedCurrentSample() throws Exception {
        assertTrue(ClockPrivilegeClient.appliedForSample(APPLIED, SAMPLE));
        assertTrue(ClockPrivilegeClient.appliedForSample(APPLIED.replace("500", "-500"), -SAMPLE));
        assertFalse(ClockPrivilegeClient.appliedForSample(APPLIED.replace("true", "false"), SAMPLE + 1));
        assertFalse(ClockPrivilegeClient.appliedForSample(APPLIED.replace("APPLIED", "FAILED")
                .replace("CLOCK_SET_RETURNED", "OS_ERROR"), SAMPLE));
        assertFalse(ClockPrivilegeClient.appliedForSample(APPLIED.replace("APPLIED", "UNKNOWN")
                .replace("CLOCK_SET_RETURNED", "NOT_COMMITTED"), SAMPLE));
    }

    @Test
    void rejectsDifferentCurrentTargetAndUnboundResponse() {
        assertThrows(IOException.class, () -> ClockPrivilegeClient.appliedForSample(APPLIED, SAMPLE + 1));
        for (String invalid : new String[] { "{}", "null", "[]", APPLIED.replace("\"schema\":1", "\"schema\":true"),
                APPLIED.replace("\"currentSample\":true", "\"currentSample\":\"true\""),
                APPLIED.replace("98682ee6-54e5-4593-aa16-ee775d482401", "bad-id"),
                APPLIED.replace("500", "5e2"), APPLIED.replace("\"state\":", "\"extra\":0,\"state\":") }) {
            assertThrows(IOException.class, () -> ClockPrivilegeClient.appliedForSample(invalid, SAMPLE));
        }
    }

    @Test
    void acceptsOnlyActionAndDeviceMatchingCurrentReceipt() throws Exception {
        assertTrue(ClockPrivilegeClient.appliedForRtc(RTC_APPLIED, "/dev/rtc4"));
        assertFalse(ClockPrivilegeClient.appliedForRtc(APPLIED.replace("true", "false"), "/dev/rtc4"));
        assertFalse(ClockPrivilegeClient.appliedForSample(RTC_APPLIED.replace("true", "false"), SAMPLE));
        assertThrows(IOException.class, () -> ClockPrivilegeClient.appliedForRtc(APPLIED, "/dev/rtc4"));
        assertThrows(IOException.class, () -> ClockPrivilegeClient.appliedForSample(RTC_APPLIED, SAMPLE));
        assertThrows(IOException.class, () -> ClockPrivilegeClient.appliedForRtc(RTC_APPLIED, "/dev/rtc0"));
        assertThrows(IOException.class, () -> ClockPrivilegeClient.appliedForRtc(
                RTC_APPLIED.replace("RTC_SET_RETURNED", "CLOCK_SET_RETURNED"), "/dev/rtc4"));
    }

    private ClockPrivilegeClient helper(Process process) {
        return new ClockPrivilegeClient("/test-data") {
            @Override protected Process startHelper() {
                return process;
            }
        };
    }

    @Test
    void startsOneHelperAndSendsTypedInput() throws Exception {
        Process process = mock(Process.class);
        ByteArrayOutputStream input = new ByteArrayOutputStream();
        when(process.getOutputStream()).thenReturn(input);
        when(process.waitFor(25, TimeUnit.SECONDS)).thenReturn(true);
        when(process.getInputStream()).thenReturn(new ByteArrayInputStream(APPLIED.getBytes(US_ASCII)));
        when(process.exitValue()).thenReturn(0);
        assertTrue(helper(process).adjustRealtime(SAMPLE));
        assertTrue(input.toString(US_ASCII).equals("{\"correctionMillis\":500}"));
        verify(process, times(1)).waitFor(25, TimeUnit.SECONDS);
    }

    @Test
    void sendsOnlyTheConfiguredRtcDevice() throws Exception {
        Process process = mock(Process.class);
        ByteArrayOutputStream input = new ByteArrayOutputStream();
        when(process.getOutputStream()).thenReturn(input);
        when(process.waitFor(25, TimeUnit.SECONDS)).thenReturn(true);
        when(process.getInputStream()).thenReturn(new ByteArrayInputStream(RTC_APPLIED.getBytes(US_ASCII)));
        assertTrue(helper(process).syncRtc("/dev/rtc4"));
        assertTrue(input.toString(US_ASCII).equals("{\"rtcDevice\":\"/dev/rtc4\"}"));
        assertThrows(IllegalArgumentException.class, () -> helper(process).syncRtc("/dev/null"));
        verify(process, times(1)).waitFor(25, TimeUnit.SECONDS);
    }

    @Test
    void inspectsChronyWithoutSendingAUnitOrOperationId() throws Exception {
        Process process = mock(Process.class);
        ByteArrayOutputStream input = new ByteArrayOutputStream();
        String response = "{\"schema\":1,\"unit\":\"chrony.service\",\"active\":false}";
        when(process.getOutputStream()).thenReturn(input);
        when(process.waitFor(25, TimeUnit.SECONDS)).thenReturn(true);
        when(process.getInputStream()).thenReturn(new ByteArrayInputStream(response.getBytes(US_ASCII)));
        assertEquals(new ClockPrivilegeClient.ChronyStatus("chrony.service", false), helper(process).inspectChrony());
        assertEquals("{\"inspectChrony\":true}", input.toString(US_ASCII));
        assertEquals(new ClockPrivilegeClient.ChronyStatus("", false),
                ClockPrivilegeClient.chronyStatus(response.replace("chrony.service", "")));
        assertThrows(IOException.class, () -> ClockPrivilegeClient.chronyStatus(response.replace("chrony.service", "kura.service")));
        assertThrows(IOException.class, () -> ClockPrivilegeClient.chronyStatus(response.replace("false", "\"false\"")));
    }

    @Test
    void readsChronyStepWithoutSendingTargetsAndValidatesTheTwoTimestamps() throws Exception {
        Process process = mock(Process.class);
        ByteArrayOutputStream input = new ByteArrayOutputStream();
        String response = "{\"schema\":1,\"realtimeMicros\":12345,\"monotonicMicros\":789}";
        when(process.getOutputStream()).thenReturn(input);
        when(process.waitFor(25, TimeUnit.SECONDS)).thenReturn(true);
        when(process.getInputStream()).thenReturn(new ByteArrayInputStream(response.getBytes(US_ASCII)));
        assertEquals(new ClockPrivilegeClient.ChronyStep(12345, 789), helper(process).latestChronyStep());
        assertEquals("{\"latestChronyStep\":true}", input.toString(US_ASCII));
        assertEquals(new ClockPrivilegeClient.ChronyStep(0, 0),
                ClockPrivilegeClient.chronyStep(response.replace("12345", "0").replace("789", "0")));
        for (String invalid : new String[] { "\"789\"", "0", "-1", "7e2", "9223372036854775808" }) {
            assertThrows(IOException.class, () -> ClockPrivilegeClient.chronyStep(response.replace("789", invalid)));
        }
    }

    @Test
    void chronyStopRequiresItsOwnCurrentReceiptAndCanonicalUnit() throws Exception {
        Process process = mock(Process.class);
        ByteArrayOutputStream input = new ByteArrayOutputStream();
        String reply = APPLIED.replace("\"correctionMillis\":500", "\"chronyStopUnit\":\"chrony.service\"")
                .replace("CLOCK_SET_RETURNED", "CHRONY_STOPPED");
        when(process.getOutputStream()).thenReturn(input);
        when(process.waitFor(45, TimeUnit.SECONDS)).thenReturn(true);
        when(process.getInputStream()).thenReturn(new ByteArrayInputStream(reply.getBytes(US_ASCII)));
        assertTrue(helper(process).setChronyRunning("chrony.service", false));
        assertEquals("{\"chronyStopUnit\":\"chrony.service\"}", input.toString(US_ASCII));
        assertThrows(IllegalArgumentException.class, () -> helper(process).setChronyRunning("kura.service", false));

        when(process.getInputStream()).thenReturn(new ByteArrayInputStream(reply.getBytes(US_ASCII)));
        assertThrows(IOException.class, () -> helper(process).setChronyRunning("chrony.service", true));
    }

    @Test
    void timeoutStopsOnlyOwnedHelperAndDoesNotRetry() throws Exception {
        Process process = mock(Process.class);
        when(process.getOutputStream()).thenReturn(new ByteArrayOutputStream());
        when(process.waitFor(25, TimeUnit.SECONDS)).thenReturn(false);
        when(process.isAlive()).thenReturn(true);
        assertThrows(IOException.class, () -> helper(process).adjustRealtime(SAMPLE));
        verify(process, times(1)).destroyForcibly();
        verify(process, times(1)).waitFor(25, TimeUnit.SECONDS);
    }

    @Test
    void nonzeroHelperExitAndInvalidReplyAreNotSuccess() throws Exception {
        Process process = mock(Process.class);
        when(process.getOutputStream()).thenReturn(new ByteArrayOutputStream());
        when(process.waitFor(25, TimeUnit.SECONDS)).thenReturn(true);
        when(process.getInputStream()).thenReturn(new ByteArrayInputStream("UNAVAILABLE".getBytes(US_ASCII)));
        when(process.exitValue()).thenReturn(1);
        assertThrows(IOException.class, () -> helper(process).adjustRealtime(SAMPLE));
        when(process.getInputStream()).thenReturn(new ByteArrayInputStream("{}".getBytes(US_ASCII)));
        when(process.exitValue()).thenReturn(0);
        assertThrows(IOException.class, () -> helper(process).adjustRealtime(SAMPLE));
    }

    @Test
    void outOfRangeTargetDoesNotStartHelper() {
        ClockPrivilegeClient client = new ClockPrivilegeClient("/test-data") {
            @Override protected Process startHelper() {
                throw new AssertionError("Invalid sample started a helper");
            }
        };
        assertThrows(IllegalArgumentException.class, () -> client.adjustRealtime(Long.MIN_VALUE));
        assertThrows(IllegalArgumentException.class, () -> client.adjustRealtime(Long.MAX_VALUE));
    }
}
