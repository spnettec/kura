/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import java.io.InputStream;
import java.lang.reflect.Array;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.Password;

/** One admission per JVM. An explicit recovery boot cannot silently become an ordinary snapshot boot. */
public final class ControlledRecovery {
    public static final String REQUEST_PROPERTY = "kura.recovery.request";
    private static volatile Admission admission;
    private static volatile CompletionEvidence completion;
    private static final java.util.Set<ConfigurationIntentJournal> intentJournals =
            java.util.Collections.newSetFromMap(new java.util.IdentityHashMap<>());
    static synchronized void registerIntentJournal(ConfigurationIntentJournal journal) { intentJournals.add(journal); }
    static synchronized void unregisterIntentJournal(ConfigurationIntentJournal journal) { intentJournals.remove(journal); }
    private record Admission(String request, String id, Path snapshot, String sha256,
            List<ComponentConfiguration> configurations, boolean normalLoad) { }
    private ControlledRecovery() { }

    public static boolean requested() {
        return completion == null && System.getProperty(REQUEST_PROPERTY) != null;
    }

    public record CompletionEvidence(String recoveryId, String snapshotSha256, String completionId,
            String decisionSha256) { }
    @FunctionalInterface public interface ReleaseCommit { void publish() throws Exception; }
    /** Legacy publishers cannot release a live journal with unresolved dispatches. */
    public static synchronized void commitOrdinaryWriteRelease(Evidence expected, String completionId,
            String decisionSha256, ReleaseCommit publish) throws KuraException {
        commitOrdinaryWriteRelease(expected, completionId, decisionSha256, null, null, publish);
    }

    /** Journal release links are durable before the exact create-only release receipt is published. */
    public static synchronized void commitOrdinaryWriteRelease(Evidence expected, String completionId,
            String decisionSha256, Path receipt, String receiptSha256, ReleaseCommit publish) throws KuraException {
        if (completion != null || expected == null || !expected.normalLoad()
                || !completionId.matches("complete-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
                || !decisionSha256.matches("[0-9a-f]{64}")
                || !evidence().orElseThrow(ControlledRecovery::failure).equals(expected)) { throw failure(); }
        if ((receipt == null) != (receiptSha256 == null) || receipt != null
                && (!receipt.isAbsolute() || !receiptSha256.matches("[0-9a-f]{64}"))) { throw failure(); }
        CompletionEvidence candidate = new CompletionEvidence(expected.recoveryId(), expected.snapshotSha256(), completionId, decisionSha256);
        try {
            for (var journal : intentJournals) { journal.prepareRelease(candidate, receipt, receiptSha256); }
            publish.publish();
            if (receipt != null && !releasePublicationMatches(receipt, receiptSha256)) { throw failure(); }
            for (var journal : intentJournals) { journal.commitRelease(candidate); }
        } catch (Exception e) { throw failure(); }
        completion = candidate;
    }

    static boolean releasePublicationMatches(Path receipt, String sha256) throws Exception {
        if (!Files.exists(receipt, LinkOption.NOFOLLOW_LINKS)) { return false; }
        if (!receipt.isAbsolute() || !Files.isRegularFile(receipt, LinkOption.NOFOLLOW_LINKS)
                || Files.size(receipt) > 1 << 20) { throw failure(); }
        try (InputStream input = Files.newInputStream(receipt, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = input.readNBytes((1 << 20) + 1);
            if (bytes.length > 1 << 20 || !HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)).equals(sha256)) {
                throw failure();
            }
        }
        return true;
    }
    public static Optional<CompletionEvidence> completionEvidence() { return Optional.ofNullable(completion); }

    public record Evidence(String recoveryId, String snapshotSha256, boolean normalLoad) { }
    /** Validates the live admission without disclosing source paths or configuration values. */
    public static Optional<Evidence> evidence() throws KuraException {
        if (completion != null) { return Optional.empty(); }
        if (!requested() && admission == null) { return Optional.empty(); }
        Admission current = admission;
        if (current == null || !current.request.equals(System.getProperty(REQUEST_PROPERTY))) { throw failure(); }
        verify(current);
        return Optional.of(new Evidence(current.id, current.sha256, current.normalLoad));
    }

    public static synchronized void admit(String request, String id, Path snapshot, String sha256,
            List<ComponentConfiguration> configurations) throws KuraException {
        admit(request, id, snapshot, sha256, configurations, false);
    }

    /** Only the bootstrap's authenticated retained-CM inverse may admit an originally empty managed set. */
    public static synchronized void admitCompensation(String request, String id, Path snapshot, String sha256,
            List<ComponentConfiguration> configurations) throws KuraException {
        admit(request, id, snapshot, sha256, configurations, true);
    }

    private static void admit(String request, String id, Path snapshot, String sha256,
            List<ComponentConfiguration> configurations, boolean allowEmpty) throws KuraException {
        if (admission != null || !request.equals(System.getProperty(REQUEST_PROPERTY))
                || configurations == null || !allowEmpty && configurations.isEmpty()) {
            throw failure();
        }
        Admission next = new Admission(request, id, snapshot, sha256, copy(configurations), false);
        verify(next);
        admission = next;
    }

    /** Keep the write gate while exercising the ordinary snapshot/CM startup path. */
    public static synchronized void admitNormalLoad(String request, String id, Path snapshot, String sha256)
            throws KuraException {
        if (admission != null || !request.equals(System.getProperty(REQUEST_PROPERTY))) { throw failure(); }
        if (!snapshot.getFileName().toString().equals("snapshot_" + snapshotId(snapshot) + ".xml")) { throw failure(); }
        Admission next = new Admission(request, id, snapshot, sha256, List.of(), true);
        verify(next);
        admission = next;
    }

    /** Ordinary enumeration must use the admitted directory, never another system profile. */
    public static void verifySnapshotDirectory(Path directory) throws KuraException {
        if (completion != null) { return; }
        Admission current = admission;
        if (requested() || current != null) {
            if (current == null || !current.request.equals(System.getProperty(REQUEST_PROPERTY))) { throw failure(); }
            verify(current);
            if (current.normalLoad && !current.snapshot.getParent().equals(directory.toAbsolutePath().normalize())) {
                throw failure();
            }
        }
    }

    public static Optional<List<ComponentConfiguration>> configurations() throws KuraException {
        if (completion != null) { return Optional.empty(); }
        if (!requested()) {
            if (admission != null) {
                throw failure();
            }
            return Optional.empty();
        }
        Admission current = admission;
        if (current == null || !current.request.equals(System.getProperty(REQUEST_PROPERTY))) {
            throw failure();
        }
        verify(current);
        return current.normalLoad ? Optional.empty() : Optional.of(copy(current.configurations));
    }

    public static void requireOrdinaryWrite() throws KuraException {
        if (completion != null) { return; }
        if (requested() || admission != null) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR,
                    "Controlled recovery awaits explicit completion; configuration writes are blocked");
        }
    }

    public static void verifyArtifact(Path snapshot, String sha256) throws KuraException {
        verify(new Admission("", "", snapshot, sha256, List.of(), false));
    }

    private static void verify(Admission current) throws KuraException {
        try {
            if (!current.snapshot.isAbsolute() || !Files.isRegularFile(current.snapshot, LinkOption.NOFOLLOW_LINKS)) {
                throw failure();
            }
            try (InputStream input = Files.newInputStream(current.snapshot, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
                byte[] bytes = input.readNBytes((32 << 20) + 1);
                if (bytes.length > 32 << 20 || !current.sha256.equals(HexFormat.of().formatHex(
                        MessageDigest.getInstance("SHA-256").digest(bytes)))) {
                    throw failure();
                }
            }
            long expected = snapshotId(current.snapshot);
            try (var files = Files.newDirectoryStream(current.snapshot.getParent(), "snapshot_*.xml")) {
                for (Path file : files) {
                    if (snapshotId(file) > expected) {
                        throw failure();
                    }
                }
            }
        } catch (KuraException e) {
            throw e;
        } catch (Exception e) {
            throw failure();
        }
    }

    private static long snapshotId(Path path) {
        String name = path.getFileName().toString();
        if (!name.matches("snapshot_[0-9]+\\.xml")) {
            throw new IllegalArgumentException();
        }
        return Long.parseLong(name.substring(9, name.length() - 4));
    }

    private static List<ComponentConfiguration> copy(List<ComponentConfiguration> configurations) {
        List<ComponentConfiguration> result = new ArrayList<>();
        for (ComponentConfiguration configuration : configurations) {
            Map<String, Object> values = new HashMap<>();
            configuration.getConfigurationProperties().forEach((key, value) -> values.put(key, copyValue(value)));
            result.add(new ComponentConfigurationImpl(configuration.getPid(), null, values));
        }
        return result;
    }
    private static Object copyValue(Object value) {
        if (value instanceof Password password) {
            return new Password(password.getPassword().clone());
        }
        if (value != null && value.getClass().isArray()) {
            int length = Array.getLength(value);
            Object result = Array.newInstance(value.getClass().getComponentType(), length);
            for (int i = 0; i < length; i++) {
                Array.set(result, i, copyValue(Array.get(value, i)));
            }
            return result;
        }
        if (value instanceof java.util.Collection<?> collection) {
            java.util.Collection<Object> result = value instanceof java.util.Vector<?>
                    ? new java.util.Vector<>() : new ArrayList<>();
            for (Object item : collection) { result.add(copyValue(item)); }
            return result;
        }
        return value;
    }
    private static KuraException failure() {
        return new KuraException(KuraErrorCode.CONFIGURATION_ERROR,
                "Controlled recovery snapshot is not the admitted artifact; fallback is forbidden");
    }
}
