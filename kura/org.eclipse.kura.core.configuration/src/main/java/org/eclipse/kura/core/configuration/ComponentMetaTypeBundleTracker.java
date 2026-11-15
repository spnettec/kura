/*******************************************************************************
 * Copyright (c) 2011, 2026 Eurotech and/or its affiliates and others
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicBoolean;

import org.eclipse.kura.configuration.metatype.Designate;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.eclipse.kura.core.configuration.util.ComponentUtil;
import org.osgi.framework.Bundle;
import org.osgi.framework.BundleContext;
import org.osgi.framework.BundleEvent;
import org.osgi.framework.Constants;
import org.osgi.framework.InvalidSyntaxException;
import org.osgi.framework.ServiceReference;
import org.osgi.service.cm.ManagedService;
import org.osgi.service.cm.ManagedServiceFactory;
import org.osgi.service.metatype.MetaTypeProvider;
import org.osgi.util.tracker.BundleTracker;
import org.osgi.util.tracker.ServiceTracker;
import org.osgi.util.tracker.ServiceTrackerCustomizer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** Bundle XML and live providers share one removable metadata registration. */
public class ComponentMetaTypeBundleTracker extends BundleTracker<Bundle> {
    private static final Logger LOG = LoggerFactory.getLogger(ComponentMetaTypeBundleTracker.class);
    private final BundleContext context;
    private final ConfigurationServiceImpl configuration;
    private final Map<ServiceReference<Object>, Entry> entries = new ConcurrentHashMap<>();
    private final Set<Bundle> pending = ConcurrentHashMap.newKeySet();
    private final AtomicBoolean scheduled = new AtomicBoolean();
    private final ExecutorService refresh = Executors.newSingleThreadExecutor(task -> {
        Thread thread = new Thread(task, "kura-metatype-refresh"); thread.setDaemon(true); return thread;
    });
    private final ServiceTracker<Object, Entry> providers;
    private volatile boolean closed;
    private record Entry(Bundle bundle, ProviderDefinition.Source source, Map<String, Boolean> pids,
            boolean explicit, int ranking, long id) { }

    public ComponentMetaTypeBundleTracker(BundleContext context, ConfigurationServiceImpl configuration)
            throws InvalidSyntaxException {
        super(context, Bundle.ACTIVE, null); this.context = context; this.configuration = configuration;
        var filter = context.createFilter("(|(objectClass=" + MetaTypeProvider.class.getName()
                + ")(objectClass=" + ManagedService.class.getName() + ")(objectClass=" + ManagedServiceFactory.class.getName() + "))");
        this.providers = new ServiceTracker<>(context, filter, new ServiceTrackerCustomizer<Object, Entry>() {
            @Override public Entry addingService(ServiceReference<Object> reference) {
                Object service = context.getService(reference);
                if (!(service instanceof MetaTypeProvider provider) || reference.getBundle() == null) {
                    if (service != null) { context.ungetService(reference); } return null;
                }
                Entry entry = entry(reference, provider); entries.put(reference, entry); enqueue(entry.bundle()); return entry;
            }
            @Override public void modifiedService(ServiceReference<Object> reference, Entry tracked) {
                Entry old = entries.get(reference);
                if (old == null) { return; }
                old.source().invalidate();
                Entry next = entry(reference, old.source().provider); entries.put(reference, next); enqueue(old.bundle());
            }
            @Override public void removedService(ServiceReference<Object> reference, Entry tracked) {
                Entry old = entries.remove(reference);
                if (old != null) { old.source().invalidate(); enqueue(old.bundle()); }
                context.ungetService(reference);
            }
        });
    }

    @Override public void open() { this.providers.open(); super.open(); }
    @Override public void close() {
        this.closed = true; this.providers.close(); this.refresh.shutdownNow(); this.pending.clear(); super.close();
    }
    @Override public Bundle addingBundle(Bundle bundle, BundleEvent event) {
        Bundle result = super.addingBundle(bundle, event); processBundleMetaType(bundle); return result;
    }
    @Override public void removedBundle(Bundle bundle, BundleEvent event, Bundle object) {
        this.entries.values().stream().filter(entry -> entry.bundle().equals(bundle)).forEach(entry -> entry.source().invalidate());
        super.removedBundle(bundle, event, object); this.configuration.onBundleRemoved(bundle);
    }

    private Entry entry(ServiceReference<Object> reference, MetaTypeProvider provider) {
        Bundle bundle = reference.getBundle();
        Map<String, Boolean> pids = new LinkedHashMap<>(); boolean explicit = false;
        try {
            List<String> singleton = strings(reference.getProperty(MetaTypeProvider.METATYPE_PID));
            List<String> factory = strings(reference.getProperty(MetaTypeProvider.METATYPE_FACTORY_PID));
            explicit = !singleton.isEmpty() || !factory.isEmpty();
            if (explicit) {
                for (String pid : singleton) { pids.put(pid, false); }
                for (String pid : factory) { if (pids.put(pid, true) != null) { throw new IllegalArgumentException(); } }
            } else {
                boolean isFactory = strings(reference.getProperty(Constants.OBJECTCLASS)).contains(ManagedServiceFactory.class.getName());
                boolean isManaged = isFactory || strings(reference.getProperty(Constants.OBJECTCLASS)).contains(ManagedService.class.getName());
                if (isManaged) { for (String pid : strings(reference.getProperty(Constants.SERVICE_PID))) { pids.put(pid, isFactory); } }
            }
        } catch (IllegalArgumentException e) {
            pids.clear(); LOG.warn("Invalid MetaTypeProvider service properties");
        }
        Object rank = reference.getProperty(Constants.SERVICE_RANKING); Object id = reference.getProperty(Constants.SERVICE_ID);
        return new Entry(bundle, new ProviderDefinition.Source(provider, () -> bundle != null && bundle.getState() == Bundle.ACTIVE),
                Map.copyOf(pids), explicit, rank instanceof Integer value ? value : 0, id instanceof Long value ? value : Long.MAX_VALUE);
    }

    private static List<String> strings(Object value) {
        if (value == null) { return List.of(); }
        Collection<?> values;
        if (value instanceof String string) { values = List.of(string); }
        else if (value instanceof String[] array) { values = java.util.Arrays.asList(array); }
        else if (value instanceof Collection<?> collection) { values = collection; }
        else { throw new IllegalArgumentException(); }
        if (values.size() > 512) { throw new IllegalArgumentException(); }
        List<String> result = new ArrayList<>();
        for (Object item : values) {
            if (!(item instanceof String string) || string.isBlank() || string.getBytes(StandardCharsets.UTF_8).length > 512
                    || string.codePoints().anyMatch(Character::isISOControl)) { throw new IllegalArgumentException(); }
            result.add(string);
        }
        return result;
    }

    private void enqueue(Bundle bundle) {
        if (this.closed || bundle == null) { return; }
        this.pending.add(bundle);
        if (this.scheduled.compareAndSet(false, true)) {
            try { this.refresh.execute(this::drain); }
            catch (RejectedExecutionException e) { this.scheduled.set(false); }
        }
    }
    private void drain() {
        try {
            while (!this.closed && !this.pending.isEmpty()) {
                Bundle bundle = this.pending.iterator().next(); this.pending.remove(bundle);
                if (bundle.getState() == Bundle.ACTIVE) { processBundleMetaType(bundle); }
            }
        } finally {
            this.scheduled.set(false);
            if (!this.closed && !this.pending.isEmpty()) { enqueue(this.pending.iterator().next()); }
        }
    }

    private synchronized void processBundleMetaType(Bundle bundle) {
        if (this.closed) { return; }
        Map<String, MetadataDefinition> definitions = new HashMap<>();
        var xml = ComponentUtil.getXmlMetadata(bundle);
        xml.forEach((pid, metadata) -> {
            Designate designate = ComponentUtil.getDesignate(metadata, pid);
            Tocd definition = (Tocd) ComponentUtil.getOCD(metadata, pid);
            definitions.put(pid, new MetadataDefinition(definition, designate.getFactoryPid() != null && !designate.getFactoryPid().isEmpty()));
        });
        List<Entry> candidates = this.entries.values().stream().filter(entry -> entry.bundle().equals(bundle))
                .filter(entry -> entry.explicit() || xml.isEmpty()).sorted((left, right) -> {
                    if (left.explicit() != right.explicit()) { return left.explicit() ? -1 : 1; }
                    int rank = Integer.compare(right.ranking(), left.ranking()); return rank != 0 ? rank : Long.compare(left.id(), right.id());
                }).toList();
        Set<String> selected = new java.util.HashSet<>();
        for (Entry entry : candidates) {
            for (var role : entry.pids().entrySet()) {
                if (!selected.add(role.getKey())) { continue; }
                definitions.remove(role.getKey());
                try {
                    definitions.put(role.getKey(), new MetadataDefinition(new ProviderDefinition(entry.source(), role.getKey()), role.getValue()));
                } catch (RuntimeException e) {
                    LOG.warn("Unavailable MetaTypeProvider definition for pid {}", role.getKey());
                }
            }
        }
        if (!this.closed) { this.configuration.replaceBundleMetadata(bundle, definitions); }
    }
}
