package org.eclipse.kura.core.configuration.probe;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Hashtable;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.configuration.ExternalConfigurationHandler;
import org.eclipse.kura.configuration.SelfConfiguringComponent;
import org.eclipse.kura.core.configuration.metatype.Tad;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.eclipse.kura.core.configuration.metatype.Tscalar;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.osgi.framework.BundleActivator;
import org.osgi.framework.BundleContext;
import org.osgi.framework.ServiceRegistration;
import org.osgi.service.cm.ConfigurationAdmin;

/** Test-only activator for a complete isolated IDEA runtime. Never packaged in the product bundle. */
public final class ExternalConfigurationRuntimeProbe
        implements BundleActivator, ExternalConfigurationHandler, SelfConfiguringComponent {
    private static final String PID = "org.eclipse.kura.management.externalProbe";
    private volatile ServiceRegistration<?> registration;
    private Thread worker;
    private int accepted;
    private ChangeSource lastSource;

    @Override
    public void start(BundleContext context) {
        this.worker = new Thread(() -> runProbe(context), "external-configuration-runtime-probe");
        this.worker.setDaemon(true);
        this.worker.start();
    }

    @Override
    public void stop(BundleContext context) {
        this.worker.interrupt();
    }

    private void runProbe(BundleContext context) {
        String result;
        try {
            var serviceReference = context.getServiceReference(ConfigurationService.class);
            long readyDeadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(30);
            while (serviceReference == null && System.nanoTime() < readyDeadline) {
                Thread.sleep(20);
                serviceReference = context.getServiceReference(ConfigurationService.class);
            }
            if (serviceReference == null) { throw new IllegalStateException("ConfigurationService unavailable"); }
            var adminReference = context.getServiceReference(ConfigurationAdmin.class);
            if (adminReference == null) { throw new IllegalStateException("ConfigurationAdmin unavailable"); }
            try {
                var service = context.getService(serviceReference);
                var admin = context.getService(adminReference);
                var properties = new Hashtable<String, Object>();
                properties.put("service.pid", PID);
                properties.put(ConfigurationService.KURA_SERVICE_PID, PID);
                this.registration = context.registerService(new String[] {ExternalConfigurationHandler.class.getName(),
                        SelfConfiguringComponent.class.getName()}, this, properties);
                long end = System.nanoTime() + TimeUnit.SECONDS.toNanos(15);
                while (true) {
                    try {
                        check("confirmed".equals(service.getComponentConfiguration(PID)
                                .getConfigurationProperties().get("value")), "binding");
                        break;
                    } catch (KuraException e) {
                        if (System.nanoTime() >= end) { throw e; }
                        Thread.sleep(20);
                    }
                }
                String filter = "(kura.service.pid=" + PID + ")";
                check(admin.listConfigurations(filter) == null, "no ConfigAdmin mirror before update");
                service.updateConfiguration(PID, Map.of("value", "candidate"), true);
                check(this.accepted == 1 && this.lastSource == ChangeSource.CONFIGURATION_UPDATE, "update routed");
                check("confirmed".equals(service.getComponentConfiguration(PID)
                        .getConfigurationProperties().get("value")), "candidate hidden");
                long snapshot = service.getSnapshots().stream().mapToLong(Long::longValue).max().orElseThrow();
                var mirror = service.getSnapshot(snapshot).stream().filter(value -> PID.equals(value.getPid()))
                        .findFirst().orElseThrow();
                check("confirmed".equals(mirror.getConfigurationProperties().get("value")), "snapshot confirmed");
                check(admin.listConfigurations(filter) == null, "no ConfigAdmin update");
                service.rollback(snapshot);
                check(this.accepted == 2 && this.lastSource == ChangeSource.SNAPSHOT_ROLLBACK, "rollback routed");
                this.registration.unregister();
                this.registration = null;
                end = System.nanoTime() + TimeUnit.SECONDS.toNanos(15);
                while (true) {
                    try {
                        service.getComponentConfiguration(PID);
                        if (System.nanoTime() >= end) { throw new IllegalStateException("owner not unbound"); }
                        Thread.sleep(20);
                    } catch (KuraException e) { break; }
                }
                checkRejected(() -> service.updateConfiguration(PID, Map.of("value", "after-disconnect"), false));
                checkRejected(service::snapshot);
                check(this.accepted == 2, "no fallback application");
                result = "{\"status\":\"passed\",\"fixtureOnly\":true,\"checks\":10,\"accepted\":2,"
                        + "\"snapshot\":" + snapshot + ",\"networkProviderValidated\":false}";
            } finally {
                context.ungetService(serviceReference);
                context.ungetService(adminReference);
            }
        } catch (Throwable e) {
            result = "{\"status\":\"failed\",\"fixtureOnly\":true,\"errorClass\":\""
                    + e.getClass().getSimpleName() + "\"}";
            e.printStackTrace();
        } finally {
            if (this.registration != null) { this.registration.unregister(); this.registration = null; }
        }
        try { Files.writeString(Path.of(System.getProperty("kura.management.probe.output")), result + "\n"); }
        catch (Exception e) { e.printStackTrace(); }
        System.out.println("ExternalConfigurationRuntimeProbe " + result);
    }

    private static void check(boolean condition, String step) {
        if (!condition) { throw new IllegalStateException(step); }
    }

    private static void checkRejected(Fallible call) throws Exception {
        try { call.run(); } catch (KuraException expected) { return; }
        throw new IllegalStateException("unavailable owner did not reject request");
    }

    @FunctionalInterface
    private interface Fallible { void run() throws Exception; }

    @Override
    public String getPid() { return PID; }

    @Override
    public ComponentConfiguration getConfiguration() { return getConfirmedConfiguration(); }

    @Override
    public ComponentConfiguration getConfirmedConfiguration() {
        var definition = new Tocd(); definition.setId(PID); definition.setName("External configuration test probe");
        var value = new Tad(); value.setId("value"); value.setType(Tscalar.STRING); definition.addAD(value);
        return new ComponentConfigurationImpl(PID, definition, Map.of("value", "confirmed"));
    }

    @Override
    public void validateConfiguration(Map<String, Object> properties, ChangeSource source) {
        check(properties != null && properties.get("value") instanceof String, "invalid probe request");
    }

    @Override
    public void applyConfiguration(Map<String, Object> properties, ChangeSource source) {
        validateConfiguration(properties, source);
        this.accepted++;
        this.lastSource = source;
    }
}
