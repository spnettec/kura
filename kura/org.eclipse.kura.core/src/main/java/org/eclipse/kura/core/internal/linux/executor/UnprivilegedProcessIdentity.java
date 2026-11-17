/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.internal.linux.executor;

import static java.nio.charset.StandardCharsets.US_ASCII;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;

/** Kernel admission for executing under the service's existing identity. */
final class UnprivilegedProcessIdentity {

    private static final Set<String> FIELDS = Set.of("Uid", "Gid", "Groups", "CapInh", "CapPrm", "CapEff",
            "CapBnd", "CapAmb", "NoNewPrivs");

    private UnprivilegedProcessIdentity() {
    }

    static boolean isCurrentUser(String username) {
        try {
            // ProcessHandle uses the OS identity; user.name is caller-controlled.
            String kernelUsername = ProcessHandle.current().info().user().orElse(null);
            if (username == null || !username.equals(kernelUsername)) {
                return false;
            }
            // Linux credentials/capabilities are per-thread. Also require the
            // process leader to agree, including supplementary groups.
            return matches(username, kernelUsername,
                    Files.readString(Path.of("/proc/self/status"), US_ASCII),
                    Files.readString(Path.of("/proc/thread-self/status"), US_ASCII));
        } catch (IOException | SecurityException | UnsupportedOperationException e) {
            return false;
        }
    }

    static boolean matches(String username, String kernelUsername, String processStatus, String threadStatus) {
        if (username == null || username.isEmpty() || !username.equals(kernelUsername)) {
            return false;
        }
        Map<String, String> process = status(processStatus);
        Map<String, String> thread = status(threadStatus);
        return process != null && process.equals(thread) && unprivileged(process);
    }

    private static Map<String, String> status(String status) {
        if (status == null) {
            return null;
        }
        Map<String, String> fields = new HashMap<>();
        for (String line : status.split("\n")) {
            int colon = line.indexOf(':');
            if (colon >= 0) {
                String key = line.substring(0, colon);
                if (FIELDS.contains(key)
                        && fields.putIfAbsent(key, line.substring(colon + 1).trim().replaceAll("\\s+", " ")) != null) {
                    return null;
                }
            }
        }
        return fields.keySet().equals(FIELDS) ? fields : null;
    }

    private static boolean unprivileged(Map<String, String> status) {
        if (!"1".equals(status.get("NoNewPrivs")) || !oneIdentity(status.get("Uid"))
                || !oneIdentity(status.get("Gid"))) {
            return false;
        }
        String groups = status.get("Groups");
        if (!groups.isEmpty()) {
            for (String group : groups.split(" ")) {
                if (!nonRootId(group)) {
                    return false;
                }
            }
        }
        for (String name : Set.of("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")) {
            if (!status.get(name).matches("0{16}")) {
                return false;
            }
        }
        return true;
    }

    private static boolean oneIdentity(String value) {
        String[] ids = value.split(" ");
        return ids.length == 4 && nonRootId(ids[0]) && ids[0].equals(ids[1]) && ids[0].equals(ids[2])
                && ids[0].equals(ids[3]);
    }

    private static boolean nonRootId(String value) {
        if (!value.matches("[1-9][0-9]{0,9}")) {
            return false;
        }
        return Long.parseLong(value) < 0xffff_ffffL;
    }
}
