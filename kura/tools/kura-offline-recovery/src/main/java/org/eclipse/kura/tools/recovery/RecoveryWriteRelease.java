/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.TreeMap;
import java.util.concurrent.atomic.AtomicBoolean;
import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.RecoveryCompletionService;
import org.eclipse.kura.core.configuration.ControlledRecovery;

/** A one-attempt release in the admitted JVM. Receipt paths never come from the bridge caller. */
final class RecoveryWriteRelease implements RecoveryCompletionService {
    private final RecoveryVerifier verifier;
    private final Path receipt;
    private final AtomicBoolean attempted = new AtomicBoolean();

    RecoveryWriteRelease(RecoveryVerifier verifier, Path normalReceipt) {
        this.verifier = verifier;
        this.receipt = normalReceipt.resolveSibling(normalReceipt.getFileName() + ".write-release.properties");
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
            require(this.attempted.compareAndSet(false, true));
            var admission = ControlledRecovery.evidence().orElseThrow();
            var health = this.verifier.verify(request.challenge());
            var bounds = request.bounds();
            require(health.normalLoad() && health.ordinaryWritesBlocked() && health.cmMatched()
                    && health.frameworkStartLevel() == 5 && health.configurationServiceAvailable()
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
            return new Report(1, request.completionId(), health.recoveryId(), health.snapshotSha256(),
                    request.decisionSha256(), hash(bytes), health.processId(), true, false, health);
        } catch (Exception ignored) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR,
                    "Write release unproven; preserve evidence and never resend");
        }
    }
    private static String namesHash(List<String> names) throws Exception {
        return hash(String.join("\0", names).getBytes(StandardCharsets.UTF_8));
    }
    private static String hash(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }
    private static void require(boolean condition) { if (!condition) { throw new IllegalStateException(); } }
}
