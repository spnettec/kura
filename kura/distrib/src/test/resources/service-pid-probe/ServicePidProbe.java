/*
 * Copyright (c) 2026 YOFC IOT and others
 *
 * SPDX-License-Identifier: EPL-2.0
 */
package org.eclipse.kura.testing.pid;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Duration;
import java.util.Arrays;
import java.util.Hashtable;
import java.util.List;
import java.util.Map;

import org.osgi.framework.BundleActivator;
import org.osgi.framework.BundleContext;
import org.osgi.framework.Constants;
import org.osgi.framework.ServiceReference;
import org.osgi.service.cm.Configuration;
import org.osgi.service.cm.ConfigurationAdmin;

/** Observes the actual registry and Configuration Admin of an isolated Kura Main. */
public final class ServicePidProbe implements BundleActivator {

    private static final int WAIT_SECONDS = 45;
    private static final String MARKER_KEY = "yofc.fixture.service.pid";
    private static final String MARKER_VALUE = "present";
    private static final Path WORK = Path.of("/opt/eclipse/kura/data/service-pid-probe");
    private Thread runner;

    private record Contract(String bundle, String component, String type, String pid, boolean testConfiguration) {

        private static Contract parse(String line) {
            String[] fields = line.split("\t", -1);
            if (fields.length != 5 || !Arrays.stream(fields).limit(4).allMatch(value -> value.matches("[A-Za-z0-9_.-]+"))
                    || !List.of("observe", "cycle").contains(fields[4])) {
                throw new IllegalArgumentException("Invalid service PID contract");
            }
            return new Contract(fields[0], fields[1], fields[2], fields[3], fields[4].equals("cycle"));
        }
    }

    @Override
    public void start(BundleContext context) {
        this.runner = new Thread(() -> run(context), "service-pid-probe");
        this.runner.setDaemon(true);
        this.runner.start();
    }

    @Override
    public void stop(BundleContext context) throws InterruptedException {
        this.runner.interrupt();
        this.runner.join(2500);
    }

    private static void run(BundleContext context) {
        ServiceReference<ConfigurationAdmin> reference = null;
        try {
            var contracts = Files.readAllLines(WORK.resolve("contracts.tsv")).stream().map(Contract::parse).toList();
            reference = await(() -> context.getServiceReference(ConfigurationAdmin.class));
            ConfigurationAdmin admin = context.getService(reference);
            awaitRegistrations(context, contracts);
            var survey = new StringBuilder();
            for (Contract row : contracts) {
                ServiceReference<?> match = byPid(context, row, "");
                Configuration[] configurations = admin.listConfigurations(pidFilter(row.pid()));
                boolean configured = configurations != null && configurations.length != 0;
                if (match == null) {
                    survey.append(row.pid()).append("\tMISSING\t").append(configured).append('\n');
                    continue;
                }
                survey.append(evidence(row, match)).append('\t').append(configured).append('\n');
            }
            publish("survey.tsv", survey.toString());
            await(() -> Files.exists(WORK.resolve("cycle.request")) ? Boolean.TRUE : null, Duration.ofMinutes(8));
            var transitions = new StringBuilder();
            for (Contract row : contracts.stream().filter(Contract::testConfiguration).toList()) {
                transitions.append(cycle(context, admin, row));
            }
            publish("transitions.tsv", transitions.toString());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } catch (Exception e) {
            try {
                publish("failure", e.getClass().getName() + ": " + e.getMessage() + "\n");
            } catch (Exception writeFailure) {
                e.addSuppressed(writeFailure);
                e.printStackTrace();
            }
        } finally {
            if (reference != null) {
                context.ungetService(reference);
            }
        }
    }

    private static String cycle(BundleContext context, ConfigurationAdmin admin, Contract row) throws Exception {
        requireAbsent(admin, row.pid());
        String withoutConfiguration = "(!(" + MARKER_KEY + "=*))";
        String before = evidence(row, await(() -> byPid(context, row, withoutConfiguration)));
        Configuration newConfiguration = admin.getConfiguration(row.pid(), "?");
        String configured;
        try {
            newConfiguration.update(new Hashtable<>(Map.of(MARKER_KEY, MARKER_VALUE)));
            configured = evidence(row, await(() -> byPid(context, row, "(" + MARKER_KEY + "=" + MARKER_VALUE + ")")));
            if (admin.listConfigurations(pidFilter(row.pid())).length != 1) {
                throw new IllegalStateException("Expected one matching CM configuration: " + row.pid());
            }
        } finally {
            newConfiguration.delete();
        }
        String after = evidence(row, await(() -> byPid(context, row, withoutConfiguration)));
        requireAbsent(admin, row.pid());
        return before + "\tabsent\n" + configured + "\tpresent\n" + after + "\tremoved\n";
    }

    private static void requireAbsent(ConfigurationAdmin admin, String pid) throws Exception {
        if (admin.listConfigurations(pidFilter(pid)) != null) {
            throw new IllegalStateException("Matching CM configuration already exists: " + pid);
        }
    }

    private static void awaitRegistrations(BundleContext context, List<Contract> contracts) throws Exception {
        long end = System.nanoTime() + Duration.ofSeconds(WAIT_SECONDS).toNanos();
        do {
            boolean complete = true;
            for (Contract row : contracts) {
                complete &= provider(context, row, "(component.name=" + row.component() + ")") != null;
            }
            if (complete) {
                return;
            }
            Thread.sleep(100);
        } while (System.nanoTime() < end);
    }

    private static ServiceReference<?> byPid(BundleContext context, Contract row, String additional) throws Exception {
        String filter = pidFilter(row.pid());
        ServiceReference<?> ref = provider(context, row, additional.isEmpty() ? filter : "(&" + filter + additional + ")");
        if (ref != null && !row.pid().equals(ref.getProperty(Constants.SERVICE_PID))) {
            throw new IllegalStateException("service.pid is not the expected String: " + row.pid());
        }
        return ref;
    }

    private static ServiceReference<?> provider(BundleContext context, Contract row, String filter) throws Exception {
        ServiceReference<?> match = null;
        ServiceReference<?>[] refs = context.getAllServiceReferences(row.type(), filter);
        if (refs == null) {
            return null;
        }
        for (ServiceReference<?> ref : refs) {
            var bundle = ref.getBundle();
            if (bundle != null && row.bundle().equals(bundle.getSymbolicName())
                    && row.component().equals(ref.getProperty("component.name"))) {
                if (match != null) {
                    throw new IllegalStateException("Ambiguous PID registration: " + row.pid());
                }
                match = ref;
            }
        }
        return match;
    }

    private static String evidence(Contract row, ServiceReference<?> ref) {
        return String.join("\t", row.pid(), row.bundle(), row.type(), String.valueOf(ref.getProperty(Constants.SERVICE_ID)),
                ref.getProperty(Constants.SERVICE_PID).getClass().getSimpleName());
    }

    private static String pidFilter(String pid) {
        return "(" + Constants.SERVICE_PID + "=" + pid + ")";
    }

    private static <T> T await(Check<T> check) throws Exception {
        return await(check, Duration.ofSeconds(WAIT_SECONDS));
    }

    private static <T> T await(Check<T> check, Duration timeout) throws Exception {
        long end = System.nanoTime() + timeout.toNanos();
        do {
            T result = check.get();
            if (result != null) {
                return result;
            }
            Thread.sleep(100);
        } while (System.nanoTime() < end);
        throw new IllegalStateException("Timed out waiting for service PID observation");
    }

    private static void publish(String label, String evidence) throws Exception {
        Path pending = Files.createTempFile(WORK, "." + label, ".tmp");
        Files.writeString(pending, evidence);
        Files.move(pending, WORK.resolve(label), StandardCopyOption.ATOMIC_MOVE);
    }

    @FunctionalInterface
    private interface Check<T> {
        T get() throws Exception;
    }
}
