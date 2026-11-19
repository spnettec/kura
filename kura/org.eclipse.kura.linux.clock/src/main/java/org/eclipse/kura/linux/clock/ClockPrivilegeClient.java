/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.linux.clock;

import static java.nio.charset.StandardCharsets.US_ASCII;

import java.io.IOException;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

/** The paired helper owns durable IDs; Java never retries a clock mutation. */
class ClockPrivilegeClient {

    private static final String REALTIME_FIELD = "correctionMillis";
    private static final String RTC_FIELD = "rtcDevice";
    private static final String CHRONY_START_FIELD = "chronyStartUnit";
    private static final String CHRONY_STOP_FIELD = "chronyStopUnit";
    private static final String CHRONY_STEP_FIELD = "chronyStepUnit";
    private static final long MAX_CORRECTION_MILLIS = 9223372036854L;
    private static final Pattern RTC_DEVICE = Pattern.compile("/dev/(?:rtc(?:0|[1-9][0-9]{0,8})?|misc/rtc)");
    private static final Pattern CORRECTION = Pattern.compile("0|-?[1-9][0-9]{0,12}");
    private static final Pattern TIMESTAMP = Pattern.compile("0|[1-9][0-9]{0,18}");
    private static final Set<String> CHRONY_UNITS = Set.of("chrony.service", "chronyd.service");
    private static final Set<String> UNKNOWN_REASONS = Set.of("NO_LOCAL_INTENT", "UNRESOLVED_INTENT",
            "NO_DURABLE_RESULT", "UNRESOLVED_RESULT", "UNRESOLVED_COMMIT", "UNRESOLVED_PREPARE", "NOT_COMMITTED");
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
        if (!validCorrection(correctionMillis)) {
            throw new IllegalArgumentException("Clock sample is outside the supported kernel range");
        }
        JsonObject request = new JsonObject();
        request.addProperty(REALTIME_FIELD, correctionMillis);
        return appliedForSample(exchange(request), correctionMillis);
    }

    boolean syncRtc(String device) throws IOException, InterruptedException {
        if (device == null || !RTC_DEVICE.matcher(device).matches()) {
            throw new IllegalArgumentException("Unsupported RTC device name");
        }
        JsonObject request = new JsonObject();
        request.addProperty(RTC_FIELD, device);
        return appliedForRtc(exchange(request), device);
    }

    record ChronyStatus(String unit, boolean active) {
    }

    ChronyStatus inspectChrony() throws IOException, InterruptedException {
        JsonObject request = new JsonObject();
        request.addProperty("inspectChrony", true);
        return chronyStatus(exchange(request));
    }

    record ChronyStep(long realtimeMicros, long monotonicMicros) {
    }

    ChronyStep latestChronyStep() throws IOException, InterruptedException {
        JsonObject request = new JsonObject();
        request.addProperty("latestChronyStep", true);
        return chronyStep(exchange(request));
    }

    boolean setChronyRunning(String unit, boolean running) throws IOException, InterruptedException {
        return changeChrony(running ? CHRONY_START_FIELD : CHRONY_STOP_FIELD, unit);
    }

    boolean stepChrony(String unit) throws IOException, InterruptedException {
        return changeChrony(CHRONY_STEP_FIELD, unit);
    }

    private boolean changeChrony(String field, String unit) throws IOException, InterruptedException {
        if (unit == null || !CHRONY_UNITS.contains(unit)) {
            throw new IllegalArgumentException("Unsupported Chrony service");
        }
        JsonObject request = new JsonObject();
        request.addProperty(field, unit);
        return appliedFor(exchange(request, 45), field, unit);
    }

    private String exchange(JsonObject request) throws IOException, InterruptedException {
        return exchange(request, 25);
    }

    private String exchange(JsonObject request, int timeoutSeconds) throws IOException, InterruptedException {
        Process process = startHelper();
        try {
            try (var input = process.getOutputStream()) {
                input.write(request.toString().getBytes(US_ASCII));
            }
            if (!process.waitFor(timeoutSeconds, TimeUnit.SECONDS)) {
                throw new IOException("Clock helper timed out; original decision retained for status lookup");
            }
            byte[] reply = process.getInputStream().readNBytes(4097);
            if (process.exitValue() != 0 || reply.length == 0 || reply.length > 4096) {
                throw new IOException("Clock helper unavailable; original decision retained for status lookup");
            }
            return new String(reply, US_ASCII);
        } finally {
            if (process.isAlive()) {
                process.destroyForcibly();
            }
        }
    }

    static boolean appliedForSample(String raw, long correctionMillis) throws IOException {
        return appliedFor(raw, REALTIME_FIELD, Long.toString(correctionMillis));
    }

    static boolean appliedForRtc(String raw, String device) throws IOException {
        return appliedFor(raw, RTC_FIELD, device);
    }

    static ChronyStatus chronyStatus(String raw) throws IOException {
        try {
            JsonObject result = JsonParser.parseString(raw).getAsJsonObject();
            if (!result.keySet().equals(Set.of("schema", "unit", "active"))
                    || !result.getAsJsonPrimitive("schema").isNumber() || !"1".equals(result.get("schema").getAsString())
                    || !result.getAsJsonPrimitive("active").isBoolean()) {
                throw new IllegalArgumentException();
            }
            String unit = stringField(result, "unit");
            boolean active = result.get("active").getAsBoolean();
            if (!CHRONY_UNITS.contains(unit) && !(unit.isEmpty() && !active)) {
                throw new IllegalArgumentException();
            }
            return new ChronyStatus(unit, active);
        } catch (RuntimeException error) {
            throw new IOException("Invalid Chrony status response", error);
        }
    }

    static ChronyStep chronyStep(String raw) throws IOException {
        try {
            JsonObject result = JsonParser.parseString(raw).getAsJsonObject();
            if (!result.keySet().equals(Set.of("schema", "realtimeMicros", "monotonicMicros"))
                    || !result.getAsJsonPrimitive("schema").isNumber() || !"1".equals(result.get("schema").getAsString())) {
                throw new IllegalArgumentException();
            }
            long realtime = timestampField(result, "realtimeMicros");
            long monotonic = timestampField(result, "monotonicMicros");
            if ((realtime == 0) != (monotonic == 0)) {
                throw new IllegalArgumentException();
            }
            return new ChronyStep(realtime, monotonic);
        } catch (RuntimeException error) {
            throw new IOException("Invalid Chrony step response", error);
        }
    }

    private static long timestampField(JsonObject value, String name) {
        var field = value.getAsJsonPrimitive(name);
        if (!field.isNumber() || !TIMESTAMP.matcher(field.getAsString()).matches()) {
            throw new IllegalArgumentException();
        }
        return Long.parseLong(field.getAsString());
    }

    private static boolean validCorrection(long value) {
        return value >= -MAX_CORRECTION_MILLIS && value <= MAX_CORRECTION_MILLIS;
    }

    private static boolean appliedFor(String raw, String expectedField, String expectedValue) throws IOException {
        try {
            JsonObject result = JsonParser.parseString(raw).getAsJsonObject();
            String field = Set.of(REALTIME_FIELD, RTC_FIELD, CHRONY_START_FIELD, CHRONY_STOP_FIELD, CHRONY_STEP_FIELD).stream()
                    .filter(result::has).findFirst().orElseThrow(IllegalArgumentException::new);
            if (!result.keySet().equals(Set.of("schema", "namespace", "requestId", field, "state", "reason",
                    "currentSample")) || !result.get("schema").getAsJsonPrimitive().isNumber()
                    || !"1".equals(result.get("schema").getAsString())
                    || !result.get("currentSample").getAsJsonPrimitive().isBoolean()) {
                throw new IllegalArgumentException();
            }
            var argument = result.getAsJsonPrimitive(field);
            String value = argument.getAsString();
            boolean valid = switch (field) {
            case REALTIME_FIELD -> argument.isNumber() && CORRECTION.matcher(value).matches()
                    && validCorrection(argument.getAsLong());
            case RTC_FIELD -> argument.isString() && RTC_DEVICE.matcher(value).matches();
            default -> argument.isString() && CHRONY_UNITS.contains(value);
            };
            if (!valid) {
                throw new IllegalArgumentException();
            }
            for (String name : new String[] { "namespace", "requestId" }) {
                String id = stringField(result, name);
                if (!UUID.fromString(id).toString().equals(id)) {
                    throw new IllegalArgumentException();
                }
            }
            String state = stringField(result, "state");
            String reason = stringField(result, "reason");
            String success = switch (field) {
            case REALTIME_FIELD -> "CLOCK_SET_RETURNED";
            case RTC_FIELD -> "RTC_SET_RETURNED";
            case CHRONY_START_FIELD -> "CHRONY_STARTED";
            case CHRONY_STOP_FIELD -> "CHRONY_STOPPED";
            case CHRONY_STEP_FIELD -> "CHRONY_STEP_ACCEPTED";
            default -> throw new IllegalArgumentException();
            };
            boolean validState = switch (state) {
            case "APPLIED" -> reason.equals(success);
            case "FAILED" -> reason.equals("OS_ERROR") || reason.equals("STALE_SAMPLE")
                    || (field.equals(REALTIME_FIELD) && reason.equals("CLOCK_RANGE"));
            case "UNKNOWN" -> UNKNOWN_REASONS.contains(reason);
            default -> false;
            };
            if (!validState) {
                throw new IllegalArgumentException();
            }
            boolean current = result.get("currentSample").getAsBoolean();
            if (current && (!field.equals(expectedField) || !value.equals(expectedValue))) {
                throw new IllegalArgumentException();
            }
            return current && state.equals("APPLIED");
        } catch (RuntimeException error) {
            throw new IOException("Invalid clock helper response; original decision retained", error);
        }
    }

    private static String stringField(JsonObject value, String name) {
        var field = value.getAsJsonPrimitive(name);
        if (!field.isString()) {
            throw new IllegalArgumentException();
        }
        return field.getAsString();
    }
}
