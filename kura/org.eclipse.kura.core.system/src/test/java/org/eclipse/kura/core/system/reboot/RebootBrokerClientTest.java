/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.system.reboot;

import static java.nio.charset.StandardCharsets.US_ASCII;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.util.concurrent.TimeUnit;

import org.eclipse.kura.core.system.reboot.RebootBrokerClient.Outcome;
import org.junit.jupiter.api.Test;

class RebootBrokerClientTest {

    private static final String BOOT = "54f26686-6544-4c7d-a7c1-97545b6795f9";
    private static final String LATER_BOOT = "3ee3b8b9-5596-488b-8c57-6acd43c1e7bf";
    private static final int WAIT_SECONDS = 45;

    @Test
    void readsBrokerAcceptanceWithoutClaimingBootCompletion() {
        assertEquals(Outcome.ACCEPTED, classify("ACCEPTED", "MANAGER_ACCEPTED", BOOT, true));
        assertEquals(Outcome.ACCEPTED, classify("ACCEPTED", "MANAGER_ACCEPTED", BOOT, false));
        assertEquals(Outcome.PRIOR_BOOT_OBSERVED, classify("ACCEPTED", "MANAGER_ACCEPTED", LATER_BOOT, false));
        assertEquals(Outcome.UNKNOWN, classify("ACCEPTED", "MANAGER_ACCEPTED", LATER_BOOT, true));
    }

    @Test
    void onlyAuthoritativePredispatchFailuresPermitRetry() {
        assertEquals(Outcome.NOT_STARTED, classify("FAILED", "NOT_STARTED", BOOT, true));
        assertEquals(Outcome.NOT_STARTED, classify("FAILED", "STALE_BOOT", LATER_BOOT, false));
        assertEquals(Outcome.UNKNOWN, classify("FAILED", "DISPATCH_UNCONFIRMED", BOOT, true));
        assertEquals(Outcome.UNKNOWN, classify("UNKNOWN", "NO_DURABLE_RESULT", BOOT, false));
    }

    @Test
    void malformedOrAmbiguousReceiptCannotPermitRetry() {
        String failed = receipt("FAILED", "NOT_STARTED", BOOT, true);
        assertEquals(Outcome.UNKNOWN, RebootBrokerClient.receiptOutcome(failed.replace("\"state\":", "\"state\":\"UNKNOWN\",\"state\":")));
        assertEquals(Outcome.UNKNOWN, RebootBrokerClient.receiptOutcome(failed + "{}"));
        assertEquals(Outcome.UNKNOWN, RebootBrokerClient.receiptOutcome(failed.replace("\"schema\": 1", "\"schema\": \"1\"")));
        assertEquals(Outcome.UNKNOWN, RebootBrokerClient.receiptOutcome(failed.replace(BOOT, "invalid")));
        assertEquals(Outcome.UNKNOWN, RebootBrokerClient.receiptOutcome("{\"state\":\"FAILED\",\"reason\":\"NOT_STARTED\"}"));
    }

    @Test
    void nonexistentHelperIsDefinitelyNotStarted() {
        RebootBrokerClient client = new RebootBrokerClient() {
            @Override
            protected Process startHelper() throws IOException {
                throw new IOException("Could not start helper");
            }
        };
        assertEquals(Outcome.NOT_STARTED, client.request());
    }

    @Test
    void nonzeroExitCannotDisproveDispatch() throws Exception {
        Process process = helper();
        when(process.waitFor(WAIT_SECONDS, TimeUnit.SECONDS)).thenReturn(true);
        when(process.exitValue()).thenReturn(1);
        assertEquals(Outcome.UNKNOWN, client(process).request());
    }

    @Test
    void timeoutEndsTheHelperWaitWithoutChangingTheOutcomeToNotStarted() throws Exception {
        Process process = helper();
        when(process.waitFor(WAIT_SECONDS, TimeUnit.SECONDS)).thenReturn(false);
        when(process.isAlive()).thenReturn(true);
        assertEquals(Outcome.UNKNOWN, client(process).request());
        verify(process).destroyForcibly();
    }

    @Test
    void interruptedWaitReassertsTheInterruptAndKeepsUnknown() throws Exception {
        Process process = helper();
        when(process.waitFor(WAIT_SECONDS, TimeUnit.SECONDS)).thenThrow(new InterruptedException());
        try {
            assertEquals(Outcome.UNKNOWN, client(process).request());
            assertTrue(Thread.currentThread().isInterrupted());
        } finally {
            Thread.interrupted();
        }
    }

    @Test
    void actualClientEntryConsumesTheValidatedResult() throws Exception {
        Process process = helper();
        when(process.waitFor(WAIT_SECONDS, TimeUnit.SECONDS)).thenReturn(true);
        when(process.getInputStream()).thenReturn(new ByteArrayInputStream(
                receipt("FAILED", "NOT_STARTED", BOOT, true).getBytes(US_ASCII)));
        assertEquals(Outcome.NOT_STARTED, client(process).request());
    }

    private static Process helper() {
        Process process = mock(Process.class);
        when(process.getOutputStream()).thenReturn(OutputStream.nullOutputStream());
        return process;
    }

    private static RebootBrokerClient client(Process process) {
        return new RebootBrokerClient() {
            @Override
            protected Process startHelper() {
                return process;
            }
        };
    }

    private static Outcome classify(String state, String reason, String observedBoot, boolean currentRequest) {
        return RebootBrokerClient.receiptOutcome(receipt(state, reason, observedBoot, currentRequest));
    }

    private static String receipt(String state, String reason, String observedBoot, boolean currentRequest) {
        return """
                {"schema": 1, "namespace": "ba0b6d77-ece0-4bef-8f17-46a1ad7072b1",
                 "requestId": "12b5f634-ec03-41d5-b170-016448bffd71",
                 "requestSha256": "%s", "bootId": "%s", "observedBootId": "%s",
                 "state":"%s", "reason":"%s", "currentRequest":%s}
                """.formatted("a".repeat(64), BOOT, observedBoot, state, reason, currentRequest);
    }
}
