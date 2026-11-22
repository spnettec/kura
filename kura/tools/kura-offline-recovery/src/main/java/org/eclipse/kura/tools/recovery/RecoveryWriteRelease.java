/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.atomic.AtomicBoolean;
import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.RecoveryCompletionService;
import org.eclipse.kura.core.configuration.ControlledRecovery;

/** A one-attempt release in the admitted JVM. Receipt paths never come from the bridge caller. */
final class RecoveryWriteRelease implements RecoveryCompletionService {
    private final RecoveryVerifier verifier;
    private final Path normalReceipt;
    private final Path receipt;
    private final int frameworkTarget;
    private final boolean fixedGuarded;
    private final AtomicBoolean attempted = new AtomicBoolean();

    RecoveryWriteRelease(RecoveryVerifier verifier, Path normalReceipt, int frameworkTarget) {
        this(verifier, normalReceipt, frameworkTarget, false);
    }

    RecoveryWriteRelease(RecoveryVerifier verifier, Path normalReceipt, int frameworkTarget, boolean fixedGuarded) {
        this.verifier = verifier;
        this.normalReceipt = normalReceipt;
        this.receipt = normalReceipt.resolveSibling(normalReceipt.getFileName() + ".write-release.properties");
        this.frameworkTarget = frameworkTarget;
        this.fixedGuarded = fixedGuarded;
    }

    @Override public Report complete(Request request) throws KuraException {
        try {
            require(request != null && request.challenge() != null
                    && request.completionId().matches("complete-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"));
            for (String hash : List.of(request.decisionSha256(), request.healthReceiptSha256(), request.policySha256())) {
                require(hash.matches("[0-9a-f]{64}"));
            }
            long now = System.currentTimeMillis();
            require(request.notAfterUnixMillis() > now && request.notAfterUnixMillis() - now <= 600_000);
            var admission = ControlledRecovery.evidence().orElseThrow();
            if (this.fixedGuarded) {
                verifyFixedApproval(request, admission);
            }
            require(this.attempted.compareAndSet(false, true));
            var health = this.verifier.verify(request.challenge());
            var bounds = request.bounds();
            require(health.normalLoad() && health.ordinaryWritesBlocked() && health.cmMatched()
                    && health.frameworkStartLevel() == this.frameworkTarget && health.configurationServiceAvailable()
                    && health.components().stream().allMatch(c -> c.registered())
                    && health.checks().stream().allMatch(c -> c.passed()) && bounds != null
                    && bounds.sourceCount() == health.sourceConfigurationCount()
                    && bounds.managedCount() == health.managedConfigurationCount()
                    && bounds.propertyCount() == health.propertyCount()
                    && bounds.materializedSelfPids().equals(health.materializedSelfPids()));
            var fields = new TreeMap<String, String>();
            fields.put("schema", "yofc.kura.write-release.v1");
            fields.put("status", "ORDINARY_WRITES_RELEASE_COMMITTED");
            fields.put("scope", "administrator-selected-checks");
            fields.put("completion.id", request.completionId());
            fields.put("recovery.id", health.recoveryId());
            fields.put("snapshot.sha256", health.snapshotSha256());
            fields.put("decision.sha256", request.decisionSha256());
            fields.put("health.receipt.sha256", request.healthReceiptSha256());
            fields.put("policy.sha256", request.policySha256());
            fields.put("nonce", health.nonce());
            fields.put("process.id", Long.toString(health.processId()));
            fields.put("source.count", Integer.toString(health.sourceConfigurationCount()));
            fields.put("managed.count", Integer.toString(health.managedConfigurationCount()));
            fields.put("property.count", Integer.toString(health.propertyCount()));
            fields.put("components.sha256", namesHash(request.challenge().componentPids()));
            fields.put("checks.sha256", namesHash(request.challenge().checkIds()));
            fields.put("additional.grant.sha256", namesHash(request.challenge().additionalSelfPids()));
            fields.put("additional.observed.sha256", namesHash(health.materializedSelfPids()));
            fields.put("kuraRecoveryVerified", "false");
            var body = new StringBuilder(); fields.forEach((key, value) -> body.append(key).append('=').append(value).append('\n'));
            byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
            ControlledRecovery.commitOrdinaryWriteRelease(admission, request.completionId(), request.decisionSha256(), this.receipt, hash(bytes), () -> {
                require(System.currentTimeMillis() < request.notAfterUnixMillis());
                RecoveryBootstrap.publish(this.receipt, bytes);
            });
            if (this.fixedGuarded) {
                Path confirmed = this.receipt.resolveSibling(this.receipt.getFileName() + ".committed");
                RecoveryBootstrap.publish(confirmed, (hash(bytes) + "\n").getBytes(StandardCharsets.US_ASCII));
            }
            return new Report(1, request.completionId(), health.recoveryId(), health.snapshotSha256(),
                    request.decisionSha256(), hash(bytes), health.processId(), true, false, health);
        } catch (Exception ignored) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR,
                    "Write release unproven; preserve evidence and never resend");
        }
    }

    private void verifyFixedApproval(Request request, ControlledRecovery.Evidence admission) throws Exception {
        Path decision = this.normalReceipt.getParent().getParent().resolve("release-issued.properties");
        RecoveryBootstrap.projected(decision, false);
        byte[] raw = RecoveryBootstrap.read(decision, 8192);
        String sha = hash(raw);
        require(sha.equals(request.decisionSha256()) && sha.equals(request.policySha256()));
        byte[] normal = RecoveryBootstrap.read(this.normalReceipt, 8192);
        Map<String, String> original = RecoveryBootstrap.properties(normal);
        require(admission.normalLoad() && "NORMAL_BOOT_ADMITTED".equals(original.get("status"))
                && admission.recoveryId().equals(original.get("restore.id"))
                && admission.snapshotSha256().equals(original.get("snapshot.sha256")));
        var challenge = request.challenge();
        var expected = Map.ofEntries(
                Map.entry("schema", "yofc.kura.fixed-write-approval.v1"),
                Map.entry("completion.id", "complete-" + admission.recoveryId().substring(4)),
                Map.entry("restore.id", admission.recoveryId()),
                Map.entry("normal.receipt.sha256", hash(normal)),
                Map.entry("source.receipt.sha256", original.get("source.receipt.sha256")),
                Map.entry("snapshot.sha256", admission.snapshotSha256()),
                Map.entry("health.receipt.sha256", request.healthReceiptSha256()),
                Map.entry("nonce", challenge.nonce()),
                Map.entry("process.id", Long.toString(ProcessHandle.current().pid())),
                Map.entry("invocation.id", System.getenv("INVOCATION_ID")),
                Map.entry("not.after", Long.toString(request.notAfterUnixMillis())),
                Map.entry("components.sha256", namesHash(challenge.componentPids())),
                Map.entry("checks.sha256", namesHash(challenge.checkIds())),
                Map.entry("additional.grant.sha256", namesHash(challenge.additionalSelfPids())));
        require(request.completionId().equals(expected.get("completion.id"))
                && RecoveryBootstrap.properties(raw).equals(expected));
    }
    private static String namesHash(List<String> names) throws Exception {
        return hash(String.join("\0", names).getBytes(StandardCharsets.UTF_8));
    }
    private static String hash(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }
    private static void require(boolean condition) { if (!condition) { throw new IllegalStateException(); } }
}
