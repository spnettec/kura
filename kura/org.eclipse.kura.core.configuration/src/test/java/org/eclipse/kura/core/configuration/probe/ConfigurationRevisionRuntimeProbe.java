/* Copyright (c) 2026 Contributors to the Eclipse Foundation. SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration.probe;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Hashtable;
import java.util.Map;
import java.util.Properties;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import org.eclipse.kura.configuration.ConfigurableComponent;
import org.eclipse.kura.configuration.ConfigurationRevisionService;
import org.eclipse.kura.configuration.ConfigurationRevisionService.Reason;
import org.eclipse.kura.configuration.ConfigurationRevisionService.Rejected;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.configuration.Password;
import org.osgi.framework.BundleActivator;
import org.osgi.framework.BundleContext;
import org.osgi.service.cm.ConfigurationAdmin;

/** One-use real CM/DS/snapshot probe; compiled only in test-classes, never in the product JAR. */
public final class ConfigurationRevisionRuntimeProbe implements BundleActivator {
    private static final String PID = "org.eclipse.kura.management.revisionFixture";
    private Thread worker;
    private int checks;

    public static final class Fixture implements ConfigurableComponent {
        public void updated(Map<String, Object> properties) { /* SCR must apply real CM changes. */ }
    }

    @Override public void start(BundleContext context) {
        this.worker = new Thread(() -> run(context), "configuration-revision-runtime-probe");
        this.worker.setDaemon(true); this.worker.start();
    }
    @Override public void stop(BundleContext context) { this.worker.interrupt(); }

    private void run(BundleContext context) {
        String phase = System.getProperty("kura.revision.probe.phase");
        Path root = Path.of(System.getProperty("kura.revision.probe.root"));
        String step = "startup";
        String result;
        try {
            Path home = Path.of(System.getProperty("kura.home")).toRealPath();
            check(home.startsWith(root.toRealPath()) && !home.equals(root.toRealPath()), "isolated home");
            check(Files.isRegularFile(root.resolve(".configuration-revision-owned")), "fixture ownership");
            var revisionRef = await(context, ConfigurationRevisionService.class);
            var configurationRef = await(context, ConfigurationService.class);
            var adminRef = await(context, ConfigurationAdmin.class);
            try {
                var revisions = context.getService(revisionRef);
                var configurations = context.getService(configurationRef);
                var admin = context.getService(adminRef);
                check("org.eclipse.kura.core.configuration".equals(revisionRef.getBundle().getSymbolicName()), "provider");
                check(revisions == configurations, "one DS provider instance");
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(45);
                while (!configurations.getConfigurableComponentPids().contains(PID) && System.nanoTime() < deadline) {
                    Thread.sleep(25);
                }
                check(configurations.getConfigurableComponentPids().contains(PID), "real DS registration");
                check(context.getBundles().length >= 280, "complete runtime");
                var cm = admin.getConfiguration(PID, "?");
                var saved = new Properties();
                Path proof = root.resolve("submission.properties");
                if ("write".equals(phase)) {
                    step = "initial";
                    check(!Files.exists(proof), "one-use write phase");
                    var first = revisions.readRevision(PID);
                    check(first.revision().matches("[0-9a-f]{64}"), "opaque revision");
                    check(secret(first.configuration().getConfigurationProperties().get("password"), "fixture-initial"), "initial password");
                    long beforeCount = cm.getChangeCount();
                    String token = first.revision();
                    step = "concurrent";
                    var start = new CountDownLatch(1);
                    try (var pool = Executors.newFixedThreadPool(2)) {
                        var a = pool.submit(() -> attempt(revisions, token, 21L, start));
                        var b = pool.submit(() -> attempt(revisions, token, 22L, start));
                        start.countDown();
                        check(a.get(15, TimeUnit.SECONDS) != b.get(15, TimeUnit.SECONDS), "one concurrent winner");
                    }
                    check(cm.getChangeCount() == beforeCount + 1, "one real CM update");
                    var after = revisions.readRevision(PID);
                    check(!token.equals(after.revision()), "token invalidation");
                    check(secret(after.configuration().getConfigurationProperties().get("password"), "fixture-initial"), "omitted password preserved");
                    reject(() -> revisions.updateRevision(PID, token, Map.of("count", 23L)), Reason.CONFLICT);
                    step = "typed update";
                    revisions.updateRevision(PID, after.revision(), Map.of("count", Long.MAX_VALUE,
                            "password", new Password("fixture-replaced"), "enabled", true,
                            "labels", new String[] { "中文", "English" }));
                    var typed = revisions.readRevision(PID);
                    check(Long.valueOf(Long.MAX_VALUE).equals(typed.configuration().getConfigurationProperties().get("count")), "long precision");
                    check(secret(typed.configuration().getConfigurationProperties().get("password"), "fixture-replaced"), "explicit password set");
                    check(Arrays.equals(new String[] {"中文", "English"}, (String[]) typed.configuration().getConfigurationProperties().get("labels")), "typed array");
                    long unchanged = cm.getChangeCount();
                    reject(() -> revisions.updateRevision(PID, typed.revision(), Map.of("service.pid", "forbidden")), Reason.INVALID_ARGUMENT);
                    reject(() -> revisions.updateRevision(PID, typed.revision(), Map.of("count", "wrong type")), Reason.INVALID_ARGUMENT);
                    check(cm.getChangeCount() == unchanged, "invalid patches did not write CM");
                    step = "snapshot";
                    long snapshot = configurations.getSnapshots().stream().mapToLong(Long::longValue).max().orElseThrow();
                    var snapshotConfiguration = configurations.getSnapshot(snapshot).stream().filter(c -> PID.equals(c.getPid())).findFirst().orElseThrow();
                    check(Long.valueOf(Long.MAX_VALUE).equals(snapshotConfiguration.getConfigurationProperties().get("count")), "real snapshot parse");
                    Path snapshotFile = home.resolve("user/snapshots/snapshot_" + snapshot + ".xml");
                    check(Files.isRegularFile(snapshotFile) && Files.size(snapshotFile) > 0, "snapshot persisted");
                    String bytes = new String(Files.readAllBytes(snapshotFile), java.nio.charset.StandardCharsets.ISO_8859_1);
                    check(!bytes.contains("fixture-initial") && !bytes.contains("fixture-replaced"), "no plaintext fixture password on disk");
                    check(Files.getPosixFilePermissions(snapshotFile).equals(java.nio.file.attribute.PosixFilePermissions.fromString("rw-------")), "snapshot private mode");
                    step = "legacy ABA";
                    var oldProperties = cm.getProperties();
                    var temporary = new Hashtable<String, Object>();
                    for (var keys = oldProperties.keys(); keys.hasMoreElements();) {
                        String key = keys.nextElement(); temporary.put(key, oldProperties.get(key));
                    }
                    temporary.put("count", 2L); cm.update(temporary); cm.update(oldProperties);
                    reject(() -> revisions.updateRevision(PID, typed.revision(), Map.of("count", 3L)), Reason.CONFLICT);
                    check(Long.valueOf(Long.MAX_VALUE).equals(revisions.readRevision(PID).configuration().getConfigurationProperties().get("count")), "ABA restored CM value");
                    saved.setProperty("oldRevision", revisions.readRevision(PID).revision());
                    saved.setProperty("snapshot", Long.toString(snapshot));
                    try (var out = Files.newOutputStream(proof, java.nio.file.StandardOpenOption.CREATE_NEW)) { saved.store(out, "opaque probe evidence only"); }
                } else {
                    step = "restart";
                    check("restart".equals(phase) && Files.isRegularFile(proof), "restart proof exists");
                    try (var in = Files.newInputStream(proof)) { saved.load(in); }
                    var current = revisions.readRevision(PID);
                    check(Long.valueOf(Long.MAX_VALUE).equals(current.configuration().getConfigurationProperties().get("count")), "restart loaded persisted count");
                    check(secret(current.configuration().getConfigurationProperties().get("password"), "fixture-replaced"), "restart loaded persisted password");
                    long unchanged = cm.getChangeCount();
                    reject(() -> revisions.updateRevision(PID, saved.getProperty("oldRevision"), Map.of("count", 4L)), Reason.CONFLICT);
                    check(cm.getChangeCount() == unchanged, "pre-restart token did not write");
                    check(!current.revision().equals(saved.getProperty("oldRevision")), "new provider token");
                }
                result = "{\"status\":\"passed\",\"phase\":\"" + phase + "\",\"checks\":" + this.checks
                        + ",\"fixtureOnly\":true,\"bundleCount\":" + context.getBundles().length
                        + ",\"realConfigurationAdmin\":true,\"remoteWriteValidated\":false}";
            } finally {
                context.ungetService(revisionRef); context.ungetService(configurationRef); context.ungetService(adminRef);
            }
        } catch (Throwable e) {
            // Fixed step/class only. Never print exceptions with configuration values.
            result = "{\"status\":\"failed\",\"phase\":\"" + phase + "\",\"checks\":" + this.checks
                    + ",\"step\":\"" + step + "\",\"errorClass\":\"" + e.getClass().getSimpleName() + "\"}";
        }
        try { Files.writeString(root.resolve(phase + "-result.json"), result + "\n", java.nio.file.StandardOpenOption.CREATE_NEW); }
        catch (Exception e) { System.out.println("ConfigurationRevisionRuntimeProbe result write failed"); }
        System.out.println("ConfigurationRevisionRuntimeProbe " + result);
    }

    private static <T> org.osgi.framework.ServiceReference<T> await(BundleContext context, Class<T> type) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(45);
        do {
            var ref = context.getServiceReference(type); if (ref != null) { return ref; }
            Thread.sleep(25);
        } while (System.nanoTime() < deadline);
        throw new IllegalStateException("missing service");
    }
    private static boolean secret(Object value, String expected) {
        return value instanceof Password password && Arrays.equals(password.getPassword(), expected.toCharArray());
    }
    private boolean attempt(ConfigurationRevisionService service, String revision, long value, CountDownLatch start) throws Exception {
        if (!start.await(5, TimeUnit.SECONDS)) { throw new IllegalStateException("latch"); }
        try { service.updateRevision(PID, revision, Map.of("count", value)); return true; }
        catch (Rejected e) { if (e.getReason() != Reason.CONFLICT) { throw e; } return false; }
    }
    private void check(boolean condition, String label) { if (!condition) { throw new IllegalStateException(label); } this.checks++; }
    private void reject(Fallible call, Reason reason) throws Exception {
        try { call.run(); } catch (Rejected e) { check(e.getReason() == reason, "rejection reason"); return; }
        throw new IllegalStateException("missing rejection");
    }
    @FunctionalInterface private interface Fallible { void run() throws Exception; }
}
