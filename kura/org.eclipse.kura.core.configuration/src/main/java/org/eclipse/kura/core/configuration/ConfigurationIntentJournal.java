/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import java.io.*;
import java.nio.channels.*;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.*;
import java.util.*;
import org.eclipse.kura.*;

/** Value-free, append-only dispatch decisions. Unfinished intents never authorize replay. */
final class ConfigurationIntentJournal implements AutoCloseable {
    private static final int MAGIC = 0x4b434931, LIMIT = 1 << 20, MAX_RECORDS = 1_000_000;
    private final Path directory;
    private final FileChannel lockChannel;
    private final FileLock lock;
    private record Pending(byte[] hash, String previousCompletion) { }
    private final Map<String, Pending> pending = new HashMap<>();
    private record ReleaseLink(String completionId, String snapshotSha256, String decisionSha256, Path receipt, String receiptSha256) { }
    private final Map<String, List<ReleaseLink>> releaseLinks = new HashMap<>();
    private Thread dispatchThread;
    private ClientOperation clientOperation;

    private ConfigurationIntentJournal(Path directory, FileChannel channel, FileLock lock) {
        this.directory = directory; this.lockChannel = channel; this.lock = lock;
    }

    static ConfigurationIntentJournal open(Path directory) throws KuraException {
        FileChannel channel = null; FileLock lock = null;
        try {
            if (!directory.isAbsolute()) { throw new IOException("absolute journal required"); }
            if (!Files.exists(directory, LinkOption.NOFOLLOW_LINKS)) {
                  try { Files.createDirectory(directory, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------"))); }
                  catch (FileAlreadyExistsException race) { /* Validate a concurrently created receipt root below. */ }
                forceDirectory(directory.getParent());
            }
            if (!Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS)) { throw new IOException("journal directory required"); }
            channel = FileChannel.open(directory.resolve("journal.lock"), StandardOpenOption.CREATE, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS);
            lock = channel.tryLock();
            if (lock == null) { throw new IOException("journal already owned"); }
            forceDirectory(directory);
            var result = new ConfigurationIntentJournal(directory, channel, lock);
            result.load(); return result;
        } catch (Exception e) {
            try { if (lock != null) lock.release(); if (channel != null) channel.close(); } catch (IOException ignored) { }
            throw failure(e);
        }
    }

    private void load() throws Exception {
        Map<String, byte[]> decisions = new HashMap<>();
        Map<String, List<byte[]>> releaseHashes = new HashMap<>(); int count = 0;
        try (var entries = Files.newDirectoryStream(this.directory)) {
            for (Path entry : entries) {
                String name = entry.getFileName().toString();
                if (name.equals("journal.lock")) continue;
                  if (name.equals(ConfigurationOperationStore.DIRECTORY)) {
                      if (!Files.isDirectory(entry, LinkOption.NOFOLLOW_LINKS)) throw new IOException("invalid receipt directory");
                      continue;
                  }
                if (++count > MAX_RECORDS || !name.matches("[0-9a-f-]{36}\\.(intent|complete|resolved)")
                        && !name.matches("[0-9a-f-]{36}\\.[0-9a-f-]{36}\\.release")) throw new IOException("invalid journal entry");
                byte[] bytes = read(entry); String id = name.substring(0, 36);
                try (var input = new DataInputStream(new ByteArrayInputStream(bytes))) {
                    if (input.readInt() != MAGIC || !input.readUTF().equals(id)) throw new IOException("invalid journal header");
                    String kind = input.readUTF();
                    if (name.endsWith(".intent")) {
                        if (!Set.of("single", "batch", "plan", "rollback").contains(kind)) throw new IOException("invalid operation");
                        String previousCompletion = input.readUTF();
                        if (!previousCompletion.isEmpty() && !previousCompletion.matches("complete-[0-9a-f-]{36}")) throw new IOException("invalid prior completion");
                        int size = input.readInt(); if (size < 0 || size > 1024 || size == 0 && !kind.equals("rollback")) throw new IOException("invalid scope");
                        Set<String> pids = new HashSet<>();
                        for (int i = 0; i < size; i++) { String pid = input.readUTF(); validatePid(pid); if (!pids.add(pid)) throw new IOException("duplicate scope"); }
                        this.pending.put(id, new Pending(digest(bytes), previousCompletion));
                    } else if (name.endsWith(".release")) {
                        if (!kind.equals("release")) throw new IOException("invalid release link");
                        byte[] hash = input.readNBytes(32); if (hash.length != 32) throw new EOFException();
                        String completionId = input.readUTF(), snapshotSha = input.readUTF(), decisionSha = input.readUTF();
                        Path receipt = Path.of(input.readUTF()); String receiptSha = input.readUTF();
                        if (!completionId.matches("complete-[0-9a-f-]{36}") || !name.equals(id + "." + completionId.substring(9) + ".release")
                                || !snapshotSha.matches("[0-9a-f]{64}") || !decisionSha.matches("[0-9a-f]{64}")
                                || !receipt.isAbsolute() || !receiptSha.matches("[0-9a-f]{64}")) throw new IOException("invalid release publication");
                        this.releaseLinks.computeIfAbsent(id, ignored -> new ArrayList<>()).add(new ReleaseLink(
                                completionId, snapshotSha, decisionSha, receipt, receiptSha));
                        releaseHashes.computeIfAbsent(id, ignored -> new ArrayList<>()).add(hash);
                    } else {
                        if (!kind.equals(name.endsWith(".complete") ? "complete" : "resolved")) throw new IOException("invalid decision");
                        byte[] hash = input.readNBytes(32); if (hash.length != 32) throw new EOFException();
                        if (kind.equals("resolved")) {
                            if (!input.readUTF().matches("complete-[0-9a-f-]{36}") || !input.readUTF().matches("[0-9a-f]{64}")
                                    || !input.readUTF().matches("[0-9a-f]{64}")) throw new IOException("invalid recovery decision");
                        }
                        byte[] previous = decisions.put(id, hash);
                        if (previous != null && !MessageDigest.isEqual(previous, hash)) throw new IOException("conflicting decisions");
                    }
                    if (input.read() != -1) throw new IOException("trailing journal data");
                }
            }
        }
        Map<String, Pending> originalIntents = new HashMap<>(this.pending);
        for (var entry : decisions.entrySet()) {
            if (!MessageDigest.isEqual(entry.getValue(), Objects.requireNonNull(this.pending.remove(entry.getKey())).hash())) {
                throw new IOException("decision does not match intent");
            }
        }
        for (var entry : this.releaseLinks.entrySet()) {
            Pending intent = Objects.requireNonNull(originalIntents.get(entry.getKey()));
            for (byte[] hash : releaseHashes.get(entry.getKey())) {
                if (!MessageDigest.isEqual(hash, intent.hash())) throw new IOException("release link does not match intent");
            }
            int valid = 0;
            for (ReleaseLink link : entry.getValue()) {
                if (link.completionId().equals(intent.previousCompletion())) throw new IOException("stale release decision");
                if (ControlledRecovery.releasePublicationMatches(link.receipt(), link.receiptSha256())) valid++;
            }
            if (valid > 1) throw new IOException("multiple committed releases for one intent");
            if (valid == 1) this.pending.remove(entry.getKey());
            else this.pending.put(entry.getKey(), intent);
        }
    }

    synchronized void requireStartup() throws KuraException {
        if (!this.pending.isEmpty() && ControlledRecovery.evidence().isEmpty()) throw failure(null);
    }

    synchronized void requireOrdinaryWrite() throws KuraException {
        if (this.clientOperation != null && this.dispatchThread != Thread.currentThread()) {
            if (this.clientOperation.thread != Thread.currentThread() || !this.clientOperation.entryPermit) {
                throw new org.eclipse.kura.configuration.ConfigurationRevisionService.Rejected(
                        org.eclipse.kura.configuration.ConfigurationRevisionService.Reason.CONFLICT);
            }
            this.clientOperation.entryPermit = false;
        }
        if (this.dispatchThread != Thread.currentThread() && !this.pending.isEmpty()) throw failure(null);
    }

    synchronized ClientOperation clientOperation(String id, RecordedConfigurationPlan plan) throws KuraException {
        if (this.clientOperation != null || this.dispatchThread != null) throw failure(null);
        requireOrdinaryWrite();
        var request = ConfigurationOperationStore.reserve(this.directory, id, plan);
        var operation = new ClientOperation(request);
        this.clientOperation = operation;
        return operation;
    }

    final class ClientOperation implements AutoCloseable {
        private final ConfigurationOperationStore.Request request;
        private final Thread thread = Thread.currentThread();
        private boolean entryPermit = true, intentAttempted, committed;
        private ClientOperation(ConfigurationOperationStore.Request request) { this.request = request; }
        void requireCommitted() throws KuraException { if (!this.committed) throw failure(null); }
        void rejectIfUndispatched(Throwable cause) throws KuraException {
            if (!this.intentAttempted) {
                String reason = cause instanceof org.eclipse.kura.configuration.ConfigurationRevisionService.Rejected rejected
                        ? rejected.getReason().name() : "FAILED_BEFORE_DISPATCH";
                ConfigurationOperationStore.rejected(directory, this.request, reason);
            }
        }
        @Override public void close() {
            synchronized (ConfigurationIntentJournal.this) {
                if (clientOperation == this && this.thread == Thread.currentThread()) clientOperation = null;
            }
        }
    }

    synchronized boolean revisionsBlocked() {
        return this.dispatchThread != Thread.currentThread() && !this.pending.isEmpty();
    }

    synchronized void prepareRelease(ControlledRecovery.CompletionEvidence recovery, Path receipt, String receiptSha) throws KuraException {
        if (this.pending.isEmpty()) return;
        if (this.dispatchThread != null || receipt == null || receiptSha == null || !receipt.isAbsolute()
                || receipt.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8).length > 8192) throw failure(null);
        try {
            for (var entry : this.pending.entrySet()) {
                if (recovery.completionId().equals(entry.getValue().previousCompletion())) throw failure(null);
                var bytes = new ByteArrayOutputStream();
                try (var output = new DataOutputStream(bytes)) {
                    output.writeInt(MAGIC); output.writeUTF(entry.getKey()); output.writeUTF("release"); output.write(entry.getValue().hash());
                    output.writeUTF(recovery.completionId()); output.writeUTF(recovery.snapshotSha256()); output.writeUTF(recovery.decisionSha256());
                    output.writeUTF(receipt.toString()); output.writeUTF(receiptSha);
                }
                write(entry.getKey() + "." + recovery.completionId().substring(9) + ".release", bytes.toByteArray());
                this.releaseLinks.computeIfAbsent(entry.getKey(), ignored -> new ArrayList<>()).add(new ReleaseLink(
                        recovery.completionId(), recovery.snapshotSha256(), recovery.decisionSha256(), receipt, receiptSha));
            }
        } catch (Exception e) { throw failure(e); }
    }

    synchronized void commitRelease(ControlledRecovery.CompletionEvidence recovery) throws KuraException {
        try {
            for (String id : new ArrayList<>(this.pending.keySet())) {
                var links = this.releaseLinks.getOrDefault(id, List.of()); boolean matched = false;
                for (ReleaseLink link : links) {
                    if (link.completionId().equals(recovery.completionId()) && link.snapshotSha256().equals(recovery.snapshotSha256())
                            && link.decisionSha256().equals(recovery.decisionSha256())
                            && ControlledRecovery.releasePublicationMatches(link.receipt(), link.receiptSha256())) matched = true;
                }
                if (!matched) throw failure(null);
            }
            this.pending.clear();
        } catch (Exception e) { throw failure(e); }
    }

    synchronized Ticket begin(String kind, Set<String> pids) throws KuraException {
        if (this.clientOperation == null) requireOrdinaryWrite();
        else if (this.clientOperation.thread != Thread.currentThread() || this.clientOperation.entryPermit
                || this.clientOperation.intentAttempted || !kind.equals("plan")
                || !pids.equals(this.clientOperation.request.scope()) || !this.pending.isEmpty()) throw failure(null);
        if (this.dispatchThread != null || !Set.of("single", "batch", "plan", "rollback").contains(kind)
                || pids.isEmpty() && !kind.equals("rollback") || pids.size() > 1024) throw failure(null);
        String id = this.clientOperation == null ? UUID.randomUUID().toString()
                : ConfigurationOperationStore.uuid(this.clientOperation.request.id());
        if (this.clientOperation != null) this.clientOperation.intentAttempted = true;
        try {
            var bytes = new ByteArrayOutputStream();
            try (var output = new DataOutputStream(bytes)) {
                output.writeInt(MAGIC); output.writeUTF(id); output.writeUTF(kind);
                output.writeUTF(ControlledRecovery.completionEvidence().map(ControlledRecovery.CompletionEvidence::completionId).orElse(""));
                output.writeInt(pids.size());
                for (String pid : new TreeSet<>(pids)) { validatePid(pid); output.writeUTF(pid); }
            }
            byte[] record = bytes.toByteArray();
            // Keep the in-memory gate even if a partial record or directory fsync fails.
            this.pending.put(id, new Pending(digest(record), ControlledRecovery.completionEvidence().map(ControlledRecovery.CompletionEvidence::completionId).orElse("")));
            Ticket ticket = new Ticket(id);
            write(id + ".intent", record);
            if (this.clientOperation != null) ConfigurationOperationStore.dispatched(this.directory,
                    this.clientOperation.request, digest(record));
            this.dispatchThread = Thread.currentThread(); return ticket;
        } catch (Exception e) { throw failure(e); }
    }

    final class Ticket implements AutoCloseable {
        private final String id;
        private boolean closed;
        private Ticket(String id) { this.id = id; }
        void complete() throws KuraException {
            synchronized (ConfigurationIntentJournal.this) {
                if (this.closed || dispatchThread != Thread.currentThread()) throw failure(null);
                writeDecision(this.id, "complete", null); pending.remove(this.id);
                  if (clientOperation != null && this.id.equals(ConfigurationOperationStore.uuid(clientOperation.request.id()))) {
                      clientOperation.committed = true;
                  }
            }
        }
        @Override public void close() {
            synchronized (ConfigurationIntentJournal.this) { this.closed = true; dispatchThread = null; }
        }
    }

    private void writeDecision(String id, String kind, ControlledRecovery.CompletionEvidence recovery) throws KuraException {
        try {
            var bytes = new ByteArrayOutputStream();
            try (var output = new DataOutputStream(bytes)) {
                output.writeInt(MAGIC); output.writeUTF(id); output.writeUTF(kind); output.write(this.pending.get(id).hash());
                if (recovery != null) {
                    output.writeUTF(recovery.completionId()); output.writeUTF(recovery.snapshotSha256()); output.writeUTF(recovery.decisionSha256());
                }
            }
            write(id + "." + kind, bytes.toByteArray());
        } catch (Exception e) { throw failure(e); }
    }

    private void write(String name, byte[] bytes) throws Exception {
        if (bytes.length > LIMIT) throw new IOException("journal record too large");
        try (var channel = FileChannel.open(this.directory.resolve(name), Set.of(StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS), PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
            var buffer = java.nio.ByteBuffer.wrap(bytes); while (buffer.hasRemaining()) channel.write(buffer); channel.force(true);
        }
        forceDirectory(this.directory);
    }
    private static byte[] read(Path path) throws IOException {
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) || Files.size(path) > LIMIT) throw new IOException("invalid journal file");
        try (var input = Files.newInputStream(path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = input.readNBytes(LIMIT + 1); if (bytes.length > LIMIT) throw new IOException("journal too large"); return bytes;
        }
    }
    private static void validatePid(String pid) throws IOException {
        if (pid.isBlank() || pid.getBytes(java.nio.charset.StandardCharsets.UTF_8).length > 512
                || pid.codePoints().anyMatch(Character::isISOControl)) throw new IOException("invalid scope PID");
    }
    private static byte[] digest(byte[] bytes) throws NoSuchAlgorithmException { return MessageDigest.getInstance("SHA-256").digest(bytes); }
    private static void forceDirectory(Path directory) throws IOException { try (var channel = FileChannel.open(directory, StandardOpenOption.READ)) { channel.force(true); } }
    @Override public synchronized void close() throws IOException { try { this.lock.release(); } finally { this.lockChannel.close(); } }
    private static KuraException failure(Throwable cause) {
        return new KuraException(KuraErrorCode.CONFIGURATION_ERROR, cause,
                "Configuration dispatch journal requires explicit recovery; writes and ordinary snapshot startup are blocked");
    }
}
