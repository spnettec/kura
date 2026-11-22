/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.system.reboot;

import static java.nio.charset.StandardCharsets.US_ASCII;

import java.io.IOException;
import java.io.StringReader;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

import com.google.gson.Strictness;
import com.google.gson.stream.JsonReader;
import com.google.gson.stream.JsonToken;

/** Internal Java client for the standalone Core reboot broker. */
public class RebootBrokerClient {

    public enum Outcome {
        ACCEPTED, NOT_STARTED, PRIOR_BOOT_OBSERVED, UNKNOWN
    }

    private static final int MAX_REPLY_BYTES = 4096;
    private static final int REPLY_TIMEOUT_SECONDS = 45;
    private static final Pattern SHA_256 = Pattern.compile("[0-9a-f]{64}");
    private static final Set<String> RECEIPT_FIELDS = Set.of("schema", "namespace", "requestId", "requestSha256",
            "bootId", "observedBootId", "state", "reason", "currentRequest");

    protected Process startHelper() throws IOException {
        var builder = new ProcessBuilder("/usr/bin/python3", "-I", "-B",
                "/opt/eclipse/kura/bin/kura_reboot_broker.py", "client");
        builder.environment().clear();
        builder.environment().put("PATH", "/usr/bin:/bin");
        builder.environment().put("LC_ALL", "C");
        builder.redirectErrorStream(true);
        return builder.start();
    }

    public Outcome request() {
        if (Thread.currentThread().isInterrupted()) {
            return Outcome.NOT_STARTED;
        }
        final Process helper;
        try {
            helper = startHelper();
        } catch (IOException e) {
            return Outcome.NOT_STARTED;
        }
        try {
            helper.getOutputStream().close();
            if (!helper.waitFor(REPLY_TIMEOUT_SECONDS, TimeUnit.SECONDS) || helper.exitValue() != 0) {
                return Outcome.UNKNOWN;
            }
            try (var output = helper.getInputStream()) {
                byte[] reply = output.readNBytes(MAX_REPLY_BYTES + 1);
                if (reply.length == 0 || reply.length > MAX_REPLY_BYTES) {
                    return Outcome.UNKNOWN;
                }
                return receiptOutcome(new String(reply, US_ASCII));
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return Outcome.UNKNOWN;
        } catch (IOException e) {
            return Outcome.UNKNOWN;
        } finally {
            if (helper.isAlive()) {
                helper.destroyForcibly();
            }
        }
    }

    static Outcome receiptOutcome(String reply) {
        try (var reader = new JsonReader(new StringReader(reply))) {
            reader.setStrictness(Strictness.STRICT);
            Map<String, String> fields = new HashMap<>();
            reader.beginObject();
            while (reader.hasNext()) {
                String name = reader.nextName();
                if (!RECEIPT_FIELDS.contains(name) || fields.containsKey(name)) {
                    return Outcome.UNKNOWN;
                }
                JsonToken type = switch (name) {
                case "schema" -> JsonToken.NUMBER;
                case "currentRequest" -> JsonToken.BOOLEAN;
                default -> JsonToken.STRING;
                };
                if (reader.peek() != type) {
                    return Outcome.UNKNOWN;
                }
                fields.put(name, type == JsonToken.BOOLEAN ? Boolean.toString(reader.nextBoolean()) : reader.nextString());
            }
            reader.endObject();
            if (reader.peek() != JsonToken.END_DOCUMENT || !fields.keySet().equals(RECEIPT_FIELDS)
                    || !"1".equals(fields.get("schema")) || !canonicalId(fields.get("namespace"))
                    || !canonicalId(fields.get("requestId")) || !canonicalId(fields.get("bootId"))
                    || !canonicalId(fields.get("observedBootId"))
                    || !SHA_256.matcher(fields.get("requestSha256")).matches()) {
                return Outcome.UNKNOWN;
            }
            String state = fields.get("state");
            String reason = fields.get("reason");
            if ("ACCEPTED".equals(state) && "MANAGER_ACCEPTED".equals(reason)) {
                if (fields.get("bootId").equals(fields.get("observedBootId"))) {
                    return Outcome.ACCEPTED;
                }
                return Boolean.parseBoolean(fields.get("currentRequest")) ? Outcome.UNKNOWN : Outcome.PRIOR_BOOT_OBSERVED;
            }
            if ("FAILED".equals(state) && ("NOT_STARTED".equals(reason) || "STALE_BOOT".equals(reason))) {
                return Outcome.NOT_STARTED;
            }
        } catch (IOException | IllegalStateException | IllegalArgumentException e) {
            return Outcome.UNKNOWN;
        }
        return Outcome.UNKNOWN;
    }

    private static boolean canonicalId(String value) {
        return UUID.fromString(value).toString().equals(value);
    }
}
