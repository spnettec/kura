/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import org.eclipse.kura.*;
import org.eclipse.kura.configuration.ConfigurationOperationReceiptService.*;
import org.eclipse.kura.configuration.ConfigurationRevisionService.*;

import java.io.*;
import java.nio.*;
import java.nio.channels.*;
import java.nio.file.*;
import java.nio.file.attribute.*;
import java.security.*;
import java.util.*;

/** One-shot reservations and read-only journal correlation. No CM/service access. */
final class ConfigurationOperationStore {
    static final String DIRECTORY = "client-operations";
    private static final int MAGIC = 0x4b4f5031, JOURNAL_MAGIC = 0x4b434931, LIMIT = 2 << 20;
    private static final Set<PosixFilePermission> PUBLIC =
            PosixFilePermissions.fromString("---rwxrwx");

    record Request(
            String id,
            boolean cancelled,
            Map<String, String> created,
            Set<String> updated,
            Set<String> deleted,
            Set<String> scope,
            byte[] hash) {}

    static String uuid(String id) throws Rejected {
        if (id == null || !id.matches("op-[0-9a-f-]{36}"))
            throw new Rejected(Reason.INVALID_ARGUMENT);
        try {
            String uuid = id.substring(3);
            if (!UUID.fromString(uuid).toString().equals(uuid))
                throw new IllegalArgumentException();
            return uuid;
        } catch (IllegalArgumentException failure) {
            throw new Rejected(Reason.INVALID_ARGUMENT);
        }
    }

    static Request reserve(Path root, String id, RecordedConfigurationPlan plan)
            throws KuraException {
        uuid(id);
        try {
            root(root, true);
            directory(root.resolve(DIRECTORY), true);
            if (hasOrphanEvidence(root, uuid(id))) throw new Rejected(Reason.CONFLICT);
            byte[] bytes = requestBytes(id, plan);
            write(root.resolve(DIRECTORY).resolve(uuid(id) + ".request"), bytes);
            return request(bytes, id);
        } catch (FileAlreadyExistsException duplicate) {
            throw new Rejected(Reason.CONFLICT);
        } catch (Rejected invalid) {
            throw invalid;
        } catch (Exception failure) {
            throw unavailable();
        }
    }

    static Receipt cancel(Path root, String id) throws KuraException {
        Request request = reserve(root, id, null);
        return receipt(request, State.CANCELLED, null);
    }

    static void dispatched(Path root, Request request, byte[] intentHash) throws KuraException {
        try {
            var bytes = new ByteArrayOutputStream();
            try (var out = new DataOutputStream(bytes)) {
                out.writeInt(MAGIC);
                out.writeUTF(request.id());
                out.writeUTF("dispatch");
                out.write(request.hash());
                out.write(intentHash);
            }
            write(
                    root.resolve(DIRECTORY).resolve(uuid(request.id()) + ".dispatch"),
                    bytes.toByteArray());
        } catch (Exception failure) {
            throw unavailable();
        }
    }

    static void rejected(Path root, Request request, String reason) throws KuraException {
        try {
            if (!Set.of(
                            "INVALID_ARGUMENT",
                            "NOT_FOUND",
                            "CONFLICT",
                            "UNSUPPORTED",
                            "FAILED_BEFORE_DISPATCH")
                    .contains(reason)) throw new IOException();
            var bytes = new ByteArrayOutputStream();
            try (var out = new DataOutputStream(bytes)) {
                out.writeInt(MAGIC);
                out.writeUTF(request.id());
                out.writeUTF("rejected");
                out.write(request.hash());
                out.writeUTF(reason);
            }
            write(
                    root.resolve(DIRECTORY).resolve(uuid(request.id()) + ".rejected"),
                    bytes.toByteArray());
        } catch (Exception failure) {
            throw unavailable();
        }
    }

    static Receipt read(Path root, String id) throws KuraException {
        String uuid = uuid(id);
        Request request = null;
        try {
            if (!root(root, false)) return empty(id, State.NOT_FOUND);
            Path directory = root.resolve(DIRECTORY), file = directory.resolve(uuid + ".request");
            if (!directory(directory, false) || !Files.exists(file, LinkOption.NOFOLLOW_LINKS)) {
                return empty(id, hasOrphanEvidence(root, uuid) ? State.UNKNOWN : State.NOT_FOUND);
            }
            request = request(readFile(file), id);
            Path intent = root.resolve(uuid + ".intent"),
                    dispatch = directory.resolve(uuid + ".dispatch"),
                    rejected = directory.resolve(uuid + ".rejected");
            boolean hasIntent = Files.exists(intent, LinkOption.NOFOLLOW_LINKS),
                    hasDispatch = Files.exists(dispatch, LinkOption.NOFOLLOW_LINKS);
            if (request.cancelled()) {
                if (hasOrphanEvidence(root, uuid)) throw new IOException();
                return receipt(request, State.CANCELLED, null);
            }
            if (!hasIntent) {
                if (hasDispatch
                        || Files.exists(root.resolve(uuid + ".complete"), LinkOption.NOFOLLOW_LINKS)
                        || Files.exists(
                                root.resolve(uuid + ".resolved"), LinkOption.NOFOLLOW_LINKS)
                        || hasReleaseEvidence(root, uuid))
                    throw new IOException();
                if (!Files.exists(rejected, LinkOption.NOFOLLOW_LINKS))
                    return receipt(request, State.RESERVED, null);
                try (var input = input(readFile(rejected), MAGIC, id, "rejected")) {
                    same(input.readNBytes(32), request.hash());
                    String reason = input.readUTF();
                    if (!Set.of(
                                    "INVALID_ARGUMENT",
                                    "NOT_FOUND",
                                    "CONFLICT",
                                    "UNSUPPORTED",
                                    "FAILED_BEFORE_DISPATCH")
                            .contains(reason)) throw new IOException();
                    end(input);
                    return receipt(request, State.REJECTED, reason);
                }
            }
            if (!hasDispatch || Files.exists(rejected, LinkOption.NOFOLLOW_LINKS))
                throw new IOException();
            byte[] bytes = readFile(intent), intentHash = hash(bytes);
            String previousCompletion;
            try (var input = input(bytes, JOURNAL_MAGIC, uuid, "plan")) {
                previousCompletion = input.readUTF();
                if (!previousCompletion.isEmpty()
                        && !previousCompletion.matches("complete-[0-9a-f-]{36}"))
                    throw new IOException();
                if (!names(input).equals(request.scope())) throw new IOException();
                end(input);
            }
            try (var input = input(readFile(dispatch), MAGIC, id, "dispatch")) {
                same(input.readNBytes(32), request.hash());
                same(input.readNBytes(32), intentHash);
                end(input);
            }
            // Parse every present decision before reporting success. A valid release cannot
            // conceal a damaged completion that would prevent the journal from reopening.
            Path complete = root.resolve(uuid + ".complete");
            boolean completed = Files.exists(complete, LinkOption.NOFOLLOW_LINKS);
            if (completed) {
                try (var input = input(readFile(complete), JOURNAL_MAGIC, uuid, "complete")) {
                    same(input.readNBytes(32), intentHash);
                    end(input);
                }
            }
            Path resolved = root.resolve(uuid + ".resolved");
            boolean recovered = Files.exists(resolved, LinkOption.NOFOLLOW_LINKS);
            if (recovered) {
                try (var input = input(readFile(resolved), JOURNAL_MAGIC, uuid, "resolved")) {
                    same(input.readNBytes(32), intentHash);
                    String completion = input.readUTF();
                    if (!completion.matches("complete-[0-9a-f-]{36}")
                            || completion.equals(previousCompletion)
                            || !input.readUTF().matches("[0-9a-f]{64}")
                            || !input.readUTF().matches("[0-9a-f]{64}")) throw new IOException();
                    end(input);
                }
            }
            // Release publication takes precedence over nominal completion, just as journal startup
            // does.
            int links = 0, valid = 0;
            try (var entries = Files.newDirectoryStream(root, uuid + ".*.release")) {
                for (Path link : entries) {
                    if (++links > 1024) throw new IOException();
                    try (var input = input(readFile(link), JOURNAL_MAGIC, uuid, "release")) {
                        same(input.readNBytes(32), intentHash);
                        String completion = input.readUTF(),
                                snapshot = input.readUTF(),
                                decision = input.readUTF();
                        Path publication = Path.of(input.readUTF());
                        String digest = input.readUTF();
                        end(input);
                        if (!completion.matches("complete-[0-9a-f-]{36}")
                                || completion.equals(previousCompletion)
                                || !link.getFileName()
                                        .toString()
                                        .equals(uuid + "." + completion.substring(9) + ".release")
                                || !snapshot.matches("[0-9a-f]{64}")
                                || !decision.matches("[0-9a-f]{64}")
                                || !publication.isAbsolute()
                                || !digest.matches("[0-9a-f]{64}")) throw new IOException();
                        if (ControlledRecovery.releasePublicationMatches(publication, digest))
                            valid++;
                    }
                }
            }
            if (links > 0)
                return receipt(request, valid == 1 ? State.RECOVERED : State.UNKNOWN, null);
            if (recovered) return receipt(request, State.RECOVERED, null);
            return receipt(request, completed ? State.CORE_COMMITTED : State.UNKNOWN, null);
        } catch (Exception malformed) {
            return request == null
                    ? empty(id, State.UNKNOWN)
                    : receipt(request, State.UNKNOWN, null);
        }
    }

    private static byte[] requestBytes(String id, RecordedConfigurationPlan plan) throws Exception {
        var bytes = new ByteArrayOutputStream();
        try (var out = new DataOutputStream(bytes)) {
            out.writeInt(MAGIC);
            out.writeUTF(id);
            out.writeUTF(plan == null ? "cancelled" : "plan");
            var created = plan == null ? Map.<String, String>of() : plan.createdFactories;
            out.writeInt(created.size());
            for (var entry : new TreeMap<>(created).entrySet()) {
                out.writeUTF(entry.getKey());
                out.writeUTF(entry.getValue());
            }
            names(out, plan == null ? Set.of() : plan.updatedPids);
            names(out, plan == null ? Set.of() : plan.deletions);
            names(out, plan == null ? Set.of() : plan.scope);
        }
        return bytes.toByteArray();
    }

    private static boolean hasOrphanEvidence(Path root, String uuid) throws Exception {
        for (String suffix : List.of(".intent", ".complete", ".resolved")) {
            if (Files.exists(root.resolve(uuid + suffix), LinkOption.NOFOLLOW_LINKS)) return true;
        }
        for (String suffix : List.of(".dispatch", ".rejected")) {
            if (Files.exists(
                    root.resolve(DIRECTORY).resolve(uuid + suffix), LinkOption.NOFOLLOW_LINKS))
                return true;
        }
        return hasReleaseEvidence(root, uuid);
    }

    private static boolean hasReleaseEvidence(Path root, String uuid) throws Exception {
        try (var entries = Files.newDirectoryStream(root, uuid + ".*.release")) {
            return entries.iterator().hasNext();
        }
    }

    private static Request request(byte[] bytes, String id) throws Exception {
        try (var input = new DataInputStream(new ByteArrayInputStream(bytes))) {
            if (input.readInt() != MAGIC || !input.readUTF().equals(id)) throw new IOException();
            String kind = input.readUTF();
            if (!Set.of("plan", "cancelled").contains(kind)) throw new IOException();
            int count = input.readInt();
            if (count < 0 || count > 512) throw new IOException();
            Map<String, String> created = new HashMap<>();
            for (int i = 0; i < count; i++) {
                String pid = RecordedConfigurationPlan.pid(input.readUTF()),
                        factory = RecordedConfigurationPlan.pid(input.readUTF());
                if (created.put(pid, factory) != null) throw new IOException();
            }
            Set<String> updated = names(input), deleted = names(input), scope = names(input);
            end(input);
            Set<String> mutations = new HashSet<>(created.keySet());
            mutations.addAll(updated);
            mutations.addAll(deleted);
            boolean cancelled = kind.equals("cancelled");
            if (cancelled
                    ? (!mutations.isEmpty() || !scope.isEmpty())
                    : (!scope.containsAll(mutations) || mutations.isEmpty()))
                throw new IOException();
            return new Request(
                    id,
                    cancelled,
                    Map.copyOf(created),
                    Set.copyOf(updated),
                    Set.copyOf(deleted),
                    Set.copyOf(scope),
                    hash(bytes));
        }
    }

    private static Receipt receipt(Request request, State state, String rejection) {
        return new Receipt(
                request.id(),
                state,
                request.created(),
                request.updated(),
                request.deleted(),
                request.scope(),
                rejection);
    }

    private static Receipt empty(String id, State state) {
        return new Receipt(id, state, Map.of(), Set.of(), Set.of(), Set.of(), null);
    }

    private static void names(DataOutputStream out, Set<String> values) throws Exception {
        out.writeInt(values.size());
        for (String value : new TreeSet<>(values))
            out.writeUTF(RecordedConfigurationPlan.pid(value));
    }

    private static Set<String> names(DataInputStream input) throws Exception {
        int count = input.readInt();
        if (count < 0 || count > 1024) throw new IOException();
        Set<String> result = new HashSet<>();
        for (int i = 0; i < count; i++)
            if (!result.add(RecordedConfigurationPlan.pid(input.readUTF())))
                throw new IOException();
        return result;
    }

    private static DataInputStream input(byte[] bytes, int magic, String id, String kind)
            throws Exception {
        var input = new DataInputStream(new ByteArrayInputStream(bytes));
        if (input.readInt() != magic
                || !input.readUTF().equals(id)
                || !input.readUTF().equals(kind)) throw new IOException();
        return input;
    }

    private static void end(DataInputStream input) throws Exception {
        if (input.read() != -1) throw new IOException();
    }

    private static void same(byte[] a, byte[] b) throws Exception {
        if (a.length != 32 || b.length != 32 || !MessageDigest.isEqual(a, b))
            throw new IOException();
    }

    private static byte[] hash(byte[] bytes) throws Exception {
        return MessageDigest.getInstance("SHA-256").digest(bytes);
    }

    private static boolean root(Path path, boolean create) throws Exception {
        if (!path.isAbsolute()
                || !path.normalize().equals(path)
                || !Files.isDirectory(path.getParent(), LinkOption.NOFOLLOW_LINKS))
            throw new IOException();
        return directory(path, create);
    }

    private static boolean directory(Path path, boolean create) throws Exception {
        if (!Files.exists(path, LinkOption.NOFOLLOW_LINKS)) {
            if (!create) return false;
            try {
                Files.createDirectory(
                        path,
                        PosixFilePermissions.asFileAttribute(
                                PosixFilePermissions.fromString("rwx------")));
                force(path.getParent());
            } catch (FileAlreadyExistsException race) {
                /* Verify the winner, never follow a link. */
            }
        }
        if (!Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) throw new IOException();
        trusted(path);
        return true;
    }

    private static void trusted(Path path) throws Exception {
        Set<PosixFilePermission> mode =
                Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS);
        if (mode.stream().anyMatch(PUBLIC::contains)) throw new IOException();
        var owner =
                FileSystems.getDefault()
                        .getUserPrincipalLookupService()
                        .lookupPrincipalByName(ProcessHandle.current().info().user().orElseThrow());
        if (!Files.getOwner(path, LinkOption.NOFOLLOW_LINKS).equals(owner)) throw new IOException();
    }

    private static byte[] readFile(Path path) throws Exception {
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) || Files.size(path) > LIMIT)
            throw new IOException();
        trusted(path);
        try (var input =
                Files.newInputStream(path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = input.readNBytes(LIMIT + 1);
            if (bytes.length > LIMIT) throw new IOException();
            return bytes;
        }
    }

    private static void write(Path path, byte[] bytes) throws Exception {
        if (bytes.length > LIMIT) throw new IOException();
        try (var channel =
                FileChannel.open(
                        path,
                        Set.of(
                                StandardOpenOption.CREATE_NEW,
                                StandardOpenOption.WRITE,
                                LinkOption.NOFOLLOW_LINKS),
                        PosixFilePermissions.asFileAttribute(
                                PosixFilePermissions.fromString("rw-------")))) {
            var buffer = ByteBuffer.wrap(bytes);
            while (buffer.hasRemaining()) channel.write(buffer);
            channel.force(true);
        }
        force(path.getParent());
    }

    private static void force(Path directory) throws Exception {
        try (var channel = FileChannel.open(directory, StandardOpenOption.READ)) {
            channel.force(true);
        }
    }

    private static KuraException unavailable() {
        return new KuraException(
                KuraErrorCode.CONFIGURATION_ERROR,
                "Configuration operation receipt unavailable; do not resend");
    }
}
