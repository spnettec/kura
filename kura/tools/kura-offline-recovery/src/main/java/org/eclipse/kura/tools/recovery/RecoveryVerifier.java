/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.Future;
import java.util.concurrent.SynchronousQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.configuration.ConfigurationRevisionService;
import org.eclipse.kura.configuration.RecoveryHealthCheck;
import org.eclipse.kura.configuration.RecoveryVerificationService;
import org.eclipse.kura.core.configuration.ConfigurationRestore;
import org.eclipse.kura.core.configuration.ControlledRecovery;
import org.osgi.framework.BundleContext;
import org.osgi.framework.startlevel.FrameworkStartLevel;
import org.osgi.service.cm.ConfigurationAdmin;

/** Live evidence is separate from the bootstrap decision. Never applies CM or releases its guard. */
final class RecoveryVerifier implements RecoveryVerificationService, AutoCloseable {
    private final BundleContext context;
    private final List<ComponentConfiguration> expected;
    private final ThreadPoolExecutor checks = new ThreadPoolExecutor(1, 1, 0, TimeUnit.SECONDS,
            new SynchronousQueue<>(), task -> {
                Thread thread = new Thread(task, "recovery-business-check"); thread.setDaemon(true); return thread;
            });

    RecoveryVerifier(BundleContext context, List<ComponentConfiguration> expected) {
        this.context = context;
        this.expected = ConfigurationRestore.expected(expected);
    }

    @Override public Report verify(Challenge challenge) throws KuraException {
        try {
            var evidence = ControlledRecovery.evidence().orElseThrow();
            require(evidence.normalLoad() && evidence.recoveryId().equals(challenge.recoveryId())
                    && evidence.snapshotSha256().equals(challenge.snapshotSha256())
                    && challenge.nonce().matches("[0-9a-f]{64}"));
            var pids = names(challenge.componentPids());
            names(challenge.checkIds());
            names(challenge.additionalSelfPids());
            require(!pids.isEmpty() && !challenge.checkIds().isEmpty());
            Set<String> source = new HashSet<>();
            for (var configuration : this.expected) {
                source.add(configuration.getPid());
            }
            require(source.containsAll(pids));
            var beforeCm = matchesCm(challenge);
            boolean available = false;
            Set<String> registered = Set.of();
            var configReference = this.context.getServiceReference(ConfigurationService.class);
            if (configReference != null) {
                var service = this.context.getService(configReference);
                try {
                    if (service != null) { registered = Set.copyOf(service.getConfigurableComponentPids()); available = true; }
                } finally { this.context.ungetService(configReference); }
            }
            List<ComponentState> components = new ArrayList<>();
            for (String pid : challenge.componentPids()) { components.add(new ComponentState(pid, registered.contains(pid))); }
            List<CheckState> results = new ArrayList<>();
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(1);
            for (String id : challenge.checkIds()) {
                boolean passed = false;
                var providers = new ArrayList<org.osgi.framework.ServiceReference<RecoveryHealthCheck>>();
                for (var reference : this.context.getServiceReferences(RecoveryHealthCheck.class, null)) {
                    if (id.equals(reference.getProperty(RecoveryHealthCheck.ID_PROPERTY))) { providers.add(reference); }
                }
                if (providers.size() == 1 && System.nanoTime() < deadline) {
                    var reference = providers.getFirst(); var check = this.context.getService(reference);
                    Future<Boolean> future = null;
                    try {
                        if (check != null) {
                            future = this.checks.submit(() -> check.verify(new Context(evidence.recoveryId(), evidence.snapshotSha256())));
                            passed = Boolean.TRUE.equals(future.get(Math.max(1, deadline - System.nanoTime()), TimeUnit.NANOSECONDS));
                        }
                    } catch (Exception ignored) { /* No automatic retries; a hung check occupies the one bounded worker. */ }
                    finally {
                        if (future != null) { future.cancel(true); }
                        this.context.ungetService(reference);
                    }
                }
                results.add(new CheckState(id, passed));
            }
            var afterCm = matchesCm(challenge);
            boolean cmMatched = beforeCm.matched && afterCm.matched && beforeCm.count == afterCm.count
                    && beforeCm.properties == afterCm.properties && beforeCm.materialized.equals(afterCm.materialized);
            // Recheck the live admission after observing CM and business; no stale source can gain success.
            require(ControlledRecovery.evidence().orElseThrow().equals(evidence));
            return new Report(1, evidence.recoveryId(), evidence.snapshotSha256(), challenge.nonce(),
                    ProcessHandle.current().pid(), this.context.getBundle(0).adapt(FrameworkStartLevel.class).getStartLevel(),
                    true, true, cmMatched, afterCm.count, afterCm.properties, available, components, results,
                    this.expected.size(), afterCm.materialized);
        } catch (Exception ignored) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR, "Recovery verification unavailable; preserve the write guard");
        }
    }

    private record CmMatch(boolean matched, int count, int properties, List<String> materialized) { }
    private CmMatch matchesCm(Challenge challenge) {
        var reference = this.context.getServiceReference(ConfigurationAdmin.class);
        if(reference==null){return new CmMatch(false,0,0,List.of());}
        var cm=this.context.getService(reference);int count=0,properties=0;
        try {
            if(cm==null){return new CmMatch(false,0,0,List.of());}
            var current=ConfigurationRestore.expected(ConfigurationRestore.capture(cm));count=current.size();
            for(var value:current){properties+=value.getConfigurationProperties().size();}
            Set<String> original=new HashSet<>();for(var value:this.expected){original.add(value.getPid());}
            var additional=current.stream().map(ComponentConfiguration::getPid).filter(pid->!original.contains(pid)).sorted().toList();
            require(new HashSet<>(challenge.additionalSelfPids()).containsAll(additional));
            List<ComponentConfiguration> desired=new ArrayList<>(this.expected);
            if(!additional.isEmpty()) {
                var configRef=this.context.getServiceReference(ConfigurationService.class);
                var revisionRef=this.context.getServiceReference(ConfigurationRevisionService.class);
                require(configRef!=null && revisionRef!=null);
                var configuration=this.context.getService(configRef);var revisions=this.context.getService(revisionRef);
                try {
                    require(configuration!=null && revisions!=null);
                    for(String pid:additional) {
                        var applicability=revisions.applicability(pid);
                        require(applicability!=null && applicability.kind()==ConfigurationRevisionService.ComponentKind.SELF_CONFIGURING
                                && applicability.componentOwnsView());
                        var view=configuration.getComponentConfiguration(pid);
                        require(view!=null && pid.equals(view.getPid()) && view.getConfigurationProperties()!=null
                                && view.getConfigurationProperties().get(ConfigurationAdmin.SERVICE_FACTORYPID)==null);
                        desired.add(view);
                    }
                } finally {this.context.ungetService(configRef);this.context.ungetService(revisionRef);}
            }
            // All original values remain exact; additions must match an explicitly allowed, live self-owned singleton view.
            ConfigurationRestore.verify(cm,desired);
            return new CmMatch(true,count,properties,List.copyOf(additional));
        }catch(Exception ignored){return new CmMatch(false,count,properties,List.of());}
        finally{this.context.ungetService(reference);}
    }
    private static Set<String> names(List<String> names) {
        require(names != null && names.size() <= 32);
        Set<String> unique = new HashSet<>();
        for (String name : names) {
            require(name != null && !name.isBlank() && name.length() <= 512
                    && name.chars().noneMatch(Character::isISOControl) && unique.add(name));
        }
        return unique;
    }
    private static void require(boolean condition) { if (!condition) { throw new IllegalStateException(); } }
    @Override public void close() { this.checks.shutdownNow(); }
}
