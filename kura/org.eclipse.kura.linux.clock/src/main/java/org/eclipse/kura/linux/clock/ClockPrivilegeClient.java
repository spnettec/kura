/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.linux.clock;

import static java.nio.charset.StandardCharsets.US_ASCII;

import java.io.IOException;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

/** The paired helper owns durable IDs; Java never retries a clock mutation. */
class ClockPrivilegeClient {

    private static final Set<String> FIELDS = Set.of("schema", "namespace", "requestId", "correctionMillis", "state",
            "reason", "currentSample");
    private static final Set<String> REASONS = Set.of("CLOCK_SET_RETURNED", "OS_ERROR", "NO_LOCAL_INTENT",
            "UNRESOLVED_INTENT", "NO_DURABLE_RESULT", "UNRESOLVED_RESULT", "UNRESOLVED_COMMIT", "UNRESOLVED_PREPARE",
            "NOT_COMMITTED", "STALE_SAMPLE", "CLOCK_RANGE");
    private final String dataDirectory;

    ClockPrivilegeClient(String dataDirectory) {
        if (dataDirectory == null || dataDirectory.isEmpty()) {
            throw new IllegalArgumentException("Kura data directory is required for durable clock decisions");
        }
        this.dataDirectory = dataDirectory;
    }

    protected Process startHelper() throws IOException {
        ProcessBuilder builder = new ProcessBuilder("/usr/bin/python3", "-I", "-B",
                "/opt/eclipse/kura/bin/kura_clock_client.py", "client", this.dataDirectory);
        builder.environment().clear();
        builder.environment().put("PATH", "/usr/bin:/bin");
        builder.environment().put("LC_ALL", "C");
        builder.redirectErrorStream(true);
        return builder.start();
    }

    boolean adjustRealtime(long correctionMillis) throws IOException, InterruptedException {
        if (correctionMillis < -9223372036854L || correctionMillis > 9223372036854L) {
            throw new IllegalArgumentException("Clock sample is outside the supported kernel range");
        }
        Process process = startHelper();
        try {
            JsonObject request = new JsonObject();
            request.addProperty("correctionMillis", correctionMillis);
            try (var input = process.getOutputStream()) {
                input.write(request.toString().getBytes(US_ASCII));
            }
            if (!process.waitFor(25, TimeUnit.SECONDS)) {
                throw new IOException("Clock helper timed out; original decision retained for status lookup");
            }
            byte[] reply = process.getInputStream().readNBytes(4097);
            if (process.exitValue() != 0 || reply.length == 0 || reply.length > 4096) {
                throw new IOException("Clock helper unavailable; original decision retained for status lookup");
            }
            return appliedForSample(new String(reply, US_ASCII), correctionMillis);
        } finally {
            if (process.isAlive()) {
                process.destroyForcibly();
            }
        }
    }

    static boolean appliedForSample(String raw, long correctionMillis) throws IOException {
        try {
            JsonObject result = JsonParser.parseString(raw).getAsJsonObject();
            if (!result.keySet().equals(FIELDS) || !result.get("schema").getAsJsonPrimitive().isNumber()
                    || !"1".equals(result.get("schema").getAsString())
                    || !result.get("correctionMillis").getAsJsonPrimitive().isNumber()
                    || !result.get("correctionMillis").getAsString().matches("0|-?[1-9][0-9]{0,12}")
                    || !result.get("currentSample").getAsJsonPrimitive().isBoolean()
                    || !REASONS.contains(result.get("reason").getAsString())) {
                throw new IllegalArgumentException();
            }
            for (String name : new String[] { "namespace", "requestId" }) {
                String value = result.get(name).getAsString();
                if (!UUID.fromString(value).toString().equals(value)) {
                    throw new IllegalArgumentException();
                }
            }
            String state = result.get("state").getAsString();
            if (!Set.of("APPLIED", "FAILED", "UNKNOWN").contains(state)
                    || (state.equals("APPLIED") && !result.get("reason").getAsString().equals("CLOCK_SET_RETURNED"))
                    || (state.equals("FAILED") && !Set.of("OS_ERROR", "STALE_SAMPLE", "CLOCK_RANGE")
                            .contains(result.get("reason").getAsString()))) {
                throw new IllegalArgumentException();
            }
            boolean current = result.get("currentSample").getAsBoolean();
            if (current && result.get("correctionMillis").getAsLong() != correctionMillis) {
                throw new IllegalArgumentException();
            }
            return current && state.equals("APPLIED");
        } catch (RuntimeException error) {
            throw new IOException("Invalid clock helper response; original decision retained", error);
        }
    }
}
