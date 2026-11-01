/* Copyright (c) 2026 Contributors to the Eclipse Foundation. SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration.probe;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.util.Arrays;
import java.util.Set;
import org.eclipse.kura.configuration.ConfigurationRevisionService;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.configuration.Password;
import org.osgi.framework.BundleActivator;
import org.osgi.framework.BundleContext;
import org.osgi.service.cm.ConfigurationAdmin;

/** Test-only observer: never calls any configuration writer. */
public final class ConfigurationRemoteProbe implements BundleActivator {
    private static final String PID = "org.eclipse.kura.management.revisionFixture";
    private Thread worker;
    @Override public void start(BundleContext context) {
        this.worker = new Thread(() -> observe(context), "remote-configuration-observer");
        this.worker.setDaemon(true); this.worker.start();
    }
    @Override public void stop(BundleContext context) { this.worker.interrupt(); }
    private void observe(BundleContext context) {
        Path root = Path.of(System.getProperty("kura.configuration.remote.probe.root"));
        try {
            if (!Files.isRegularFile(root.resolve(".configuration-update-owned"))
                    && !Files.isRegularFile(root.resolve(".outcome-snapshot-owned"))) { throw new IllegalStateException(); }
            while (!Thread.currentThread().isInterrupted()) {
                String stage = Files.readString(root.resolve("stage")).trim();
                if (!Set.of("initial", "keep", "set", "rejected", "restart").contains(stage)) { throw new IllegalStateException(); }
                Path output = root.resolve(stage + "-proof.json");
                var ref = context.getServiceReference(ConfigurationRevisionService.class);
                var configRef = context.getServiceReference(ConfigurationService.class);
                var adminRef = context.getServiceReference(ConfigurationAdmin.class);
                if (!Files.exists(output) && ref != null && configRef != null && adminRef != null) {
                    var revisions = context.getService(ref); var configurations = context.getService(configRef);
                    var admin = context.getService(adminRef);
                    try {
                        if (configurations.getConfigurableComponentPids().contains(PID)) {
                            var read = revisions.readRevision(PID); var values = read.configuration().getConfigurationProperties();
                            boolean initial = stage.equals("initial");
                            String expected = stage.equals("initial") || stage.equals("keep") ? "fixture-initial" : "fixture-remote-set";
                            Object secret = values.get("password");
                            if (Long.valueOf(initial ? 1 : Long.MAX_VALUE).equals(values.get("count"))
                                    && secret instanceof Password password && Arrays.equals(expected.toCharArray(), password.getPassword())
                                    && Boolean.FALSE.equals(values.get("enabled"))) {
                                Path home = Path.of(System.getProperty("kura.home")).toRealPath();
                                if (!home.startsWith(root.toRealPath()) || revisions != configurations
                                        || !ref.getBundle().getSymbolicName().equals("org.eclipse.kura.core.configuration")) { throw new IllegalStateException(); }
                                var snapshots = configurations.getSnapshots();
                                if (!initial && snapshots.isEmpty()) { throw new IllegalStateException(); }
                                for (Long id : snapshots) {
                                    Path snapshot = home.resolve("user/snapshots/snapshot_" + id + ".xml");
                                    byte[] bytes = Files.readAllBytes(snapshot);
                                    String text = new String(bytes, java.nio.charset.StandardCharsets.UTF_8);
                                    if (text.contains("fixture-initial") || text.contains("fixture-remote-set")
                                            || !Files.getPosixFilePermissions(snapshot).equals(Set.of(
                                                java.nio.file.attribute.PosixFilePermission.OWNER_READ,
                                                java.nio.file.attribute.PosixFilePermission.OWNER_WRITE))) { throw new IllegalStateException(); }
                                }
                                String result = "{\"status\":\"passed\",\"stage\":\"" + stage
                                        + "\",\"checks\":9,\"passwordMatchesExpected\":true,\"countMatchesExpected\":true,"
                                        + "\"readOnlyObserver\":true,\"snapshotSecretAbsent\":true,\"snapshotMode600\":true,"
                                        + "\"revision\":\"" + read.revision() + "\",\"cmChangeCount\":"
                                        + admin.getConfiguration(PID, "?").getChangeCount() + ",\"bundleCount\":" + context.getBundles().length + "}\n";
                                Path temporary = root.resolve(stage + "-proof.tmp");
                                Files.writeString(temporary, result, StandardOpenOption.CREATE_NEW);
                                Files.move(temporary, output, StandardCopyOption.ATOMIC_MOVE);
                            }
                        }
                    } finally { context.ungetService(ref); context.ungetService(configRef); context.ungetService(adminRef); }
                }
                Thread.sleep(100);
            }
        } catch (InterruptedException expected) { Thread.currentThread().interrupt(); }
        catch (Exception error) {
            try { Files.writeString(root.resolve("observer-error.json"), "{\"status\":\"failed\",\"errorClass\":\""
                    + error.getClass().getSimpleName() + "\"}\n", StandardOpenOption.CREATE_NEW); }
            catch (Exception ignored) { /* Preserve existing failure evidence. */ }
        }
    }
}
