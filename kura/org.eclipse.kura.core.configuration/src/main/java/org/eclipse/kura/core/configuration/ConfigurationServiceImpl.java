/*******************************************************************************
 * Copyright (c) 2011, 2025 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 *  Red Hat Inc
 *******************************************************************************/
package org.eclipse.kura.core.configuration;

import static java.util.Objects.isNull;
import static java.util.Objects.requireNonNull;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.Collections;
import java.util.Date;
import java.util.Dictionary;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Map.Entry;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.SortedSet;
import java.util.TreeSet;
import java.util.function.Function;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.KuraIOException;
import org.eclipse.kura.KuraPartialSuccessException;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ConfigurableComponent;
import org.eclipse.kura.configuration.ConfigurationConstraints;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.configuration.ConfigurationRevisionService;
import org.eclipse.kura.configuration.ConfigurationRevisionService.Applicability;
import org.eclipse.kura.configuration.ConfigurationRevisionService.ComponentKind;
import org.eclipse.kura.configuration.ConfigurationRevisionService.Reason;
import org.eclipse.kura.configuration.ConfigurationRevisionService.Rejected;
import org.eclipse.kura.configuration.ExternalConfigurationHandler;
import org.eclipse.kura.configuration.ExternalConfigurationHandler.ChangeSource;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.configuration.SelfConfiguringComponent;
import org.eclipse.kura.configuration.metatype.AD;
import org.eclipse.kura.configuration.metatype.OCD;
import org.eclipse.kura.configuration.metatype.OCDService;
import org.eclipse.kura.configuration.metatype.Scalar;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.eclipse.kura.core.configuration.upgrade.ConfigurationUpgrade;
import org.eclipse.kura.core.configuration.util.CollectionsUtil;
import org.eclipse.kura.core.configuration.util.ComponentUtil;
import org.eclipse.kura.core.configuration.util.StringUtil;
import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.marshalling.Marshaller;
import org.eclipse.kura.marshalling.Unmarshaller;
import org.eclipse.kura.system.SystemService;
import org.osgi.framework.Bundle;
import org.osgi.framework.BundleContext;
import org.osgi.framework.Constants;
import org.osgi.framework.Filter;
import org.osgi.framework.FrameworkUtil;
import org.osgi.framework.InvalidSyntaxException;
import org.osgi.framework.ServiceReference;
import org.osgi.service.cm.Configuration;
import org.osgi.service.cm.ConfigurationAdmin;
import org.osgi.service.component.ComponentContext;
import org.osgi.service.component.ComponentException;
import org.osgi.service.component.runtime.ServiceComponentRuntime;
import org.osgi.service.component.runtime.dto.ComponentDescriptionDTO;
import org.osgi.service.event.EventAdmin;
import org.osgi.service.metatype.AttributeDefinition;
import org.osgi.service.metatype.MetaTypeService;
import org.osgi.service.metatype.ObjectClassDefinition;
import org.osgi.util.tracker.BundleTracker;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Implementation of ConfigurationService.
 */
public class ConfigurationServiceImpl implements ConfigurationService, ConfigurationRevisionService, OCDService {

    private static final String GETTING_CONFIGURATION_ERROR = "Error getting Configuration for component: {}. Ignoring it.";

    private static final Logger logger = LoggerFactory.getLogger(ConfigurationServiceImpl.class);
    private static final Pattern SNAPSHOT_FILENAME_PATTERN = Pattern.compile("snapshot_(\\d+)\\.xml");

    private ComponentContext ctx;
    private BundleContext bundleContext;

    private BundleTracker<Bundle> bundleTracker;

    @SuppressWarnings("unused")
    private MetaTypeService metaTypeService;
    private ConfigurationAdmin configurationAdmin;
    private SystemService systemService;
    private CryptoService cryptoService;
    private ServiceComponentRuntime scrService;
    private Marshaller xmlMarshaller;
    private Unmarshaller xmlUnmarshaller;
    protected EventAdmin eventAdmin;

    // contains all the PIDs (aka kura.service.pid) - both of configurable and self configuring components
    private final Set<String> allActivatedPids;
    private final Set<String> waittingForActivatedPids;
    // contains the self configuring components ONLY!
    private final Set<String> activatedSelfConfigComponents;

    // maps either service.pid or service.factoryPid to the related OCD
    private final Map<String, Tocd> ocds;
    private final Map<Bundle, Map<String, MetadataDefinition>> bundleMetadata = new HashMap<>();
    private boolean stopping;

    // contains the service.factoryPid of all Factory Components
    private final Set<TrackedComponentFactory> factoryPids;

    // maps the kura.service.pid to the associated service.factoryPid
    private final Map<String, String> factoryPidByPid;

    // contains all the pids (kura.service.pid) which have to be deleted
    private final Set<String> pendingDeletePids;

    // maps the kura.service.pid to the associated service.pid
    private final Map<String, String> servicePidByPid;

    // maps the kura.service.pid to the names of the properties known to be passwords, used to restore their type
    // while the metatype of the component has not been tracked yet
    private final Map<String, Set<String>> passwordPropertiesByPid;
    // SCC read workers can re-enter an ordinary CM read while their caller owns Core.
    // This cache must not make those reads acquire the caller-owned Core monitor.
    private final Object passwordPropertiesLock = new Object();

    private final ExternalConfigurations externalConfigurations = new ExternalConfigurations(
            System.getProperty(ExternalConfigurations.RESERVED_PIDS_PROPERTY, ""));
    private final ConfigurationRevision configurationRevision = new ConfigurationRevision();
    private final Map<String, Long> revisionAdmissions = new HashMap<>();
    private final Map<String, Map<String, Object>> revisionPending = new HashMap<>();
    private final Map<String, RollbackConvergence> rollbackConvergence = new HashMap<>();
    private final Set<String> revisionUncertain = new HashSet<>();
    private ConfigurationIntentJournal intentJournal;
    private final ProviderConfigurationReads providerReads = new ProviderConfigurationReads();

    // ----------------------------------------------------------------
    //
    // Dependencies
    //
    // ----------------------------------------------------------------

    public void setConfigurationAdmin(ConfigurationAdmin configAdmin) {
        this.configurationAdmin = configAdmin;
    }

    public void unsetConfigurationAdmin(ConfigurationAdmin configAdmin) {
        this.configurationAdmin = null;
    }

    public void setMetaTypeService(MetaTypeService metaTypeService) {
        this.metaTypeService = metaTypeService;
    }

    public void unsetMetaTypeService(MetaTypeService metaTypeService) {
        this.metaTypeService = null;
    }

    public void setSystemService(SystemService systemService) {
        this.systemService = systemService;
    }

    public void unsetSystemService(SystemService systemService) {
        this.systemService = null;
    }

    public void setCryptoService(CryptoService cryptoService) {
        this.cryptoService = cryptoService;
    }

    public void unsetCryptoService(CryptoService cryptoService) {
        this.cryptoService = null;
    }

    public void setScrService(ServiceComponentRuntime scrService) {
        this.scrService = scrService;
    }

    public void unsetScrService(ServiceComponentRuntime scrService) {
        this.scrService = null;
    }

    public void setXmlMarshaller(final Marshaller marshaller) {
        this.xmlMarshaller = marshaller;
    }

    public void unsetXmlMarshaller(final Marshaller marshaller) {
        this.xmlMarshaller = null;
    }

    public void setXmlUnmarshaller(final Unmarshaller unmarshaller) {
        this.xmlUnmarshaller = unmarshaller;
    }

    public void unsetXmlUnmarshaller(final Unmarshaller unmarshaller) {
        this.xmlUnmarshaller = null;
    }

    public void setEventAdmin(EventAdmin eventAdmin) {
        this.eventAdmin = eventAdmin;
    }

    public void unsetEventAdmin(EventAdmin eventAdmin) {
        if (this.eventAdmin == eventAdmin) {
            this.eventAdmin = null;
        }
    }

    public void addExternalConfigurationHandler(ExternalConfigurationHandler handler) {
        this.externalConfigurations.bind(handler);
    }

    public void removeExternalConfigurationHandler(ExternalConfigurationHandler handler) {
        this.externalConfigurations.unbind(handler);
    }

    public ConfigurationServiceImpl() {
        this.allActivatedPids = new HashSet<>();
        this.waittingForActivatedPids = new HashSet<>();
        this.activatedSelfConfigComponents = new HashSet<>();
        this.pendingDeletePids = new HashSet<>();
        this.ocds = new HashMap<>();
        this.factoryPids = new HashSet<>();
        this.factoryPidByPid = new HashMap<>();
        this.servicePidByPid = new HashMap<>();
        this.passwordPropertiesByPid = new HashMap<>();
    }

    // ----------------------------------------------------------------
    //
    // Activation APIs
    //
    // ----------------------------------------------------------------

    protected void activate(ComponentContext componentContext) throws InvalidSyntaxException {
        logger.info("activate...");
        this.stopping = false;

        // save the bundle context
        this.ctx = componentContext;
        this.bundleContext = componentContext.getBundleContext();

        // A crash after dispatch must never be hidden by replaying an older snapshot into CM.
        try {
            initializeIntentJournal(java.nio.file.Path.of(this.systemService.getKuraDataDirectory()));
            this.intentJournal.requireStartup();
            loadLatestSnapshotInConfigAdmin();
        } catch (Exception e) {
            closeIntentJournal();
            throw new ComponentException("Error loading latest snapshot or unresolved configuration dispatch", e);
        }

        this.bundleTracker = new ComponentMetaTypeBundleTracker(this.ctx.getBundleContext(), this);
        this.bundleTracker.open();
    }

    protected void addConfigurableComponent(final ServiceReference<ConfigurableComponent> reference) {
        final String servicePid = getServicePid(reference);
        if (servicePid == null) {
            return;
        }
        final String kuraPid = makeString(reference.getProperty(ConfigurationService.KURA_SERVICE_PID));
        final String factoryPid = makeString(reference.getProperty(ConfigurationAdmin.SERVICE_FACTORYPID));
        registerComponentConfiguration(kuraPid, servicePid, factoryPid);
    }

    protected void removeConfigurableComponent(final ServiceReference<ConfigurableComponent> reference) {
        // CM may already have removed the configuration;release the registered
        // logical component without resolving its former multi-value service PID.
        if (distinctValues(reference.getProperty(Constants.SERVICE_PID)).isEmpty()) {
            return;
        }
        final String kuraPid = makeString(reference.getProperty(ConfigurationService.KURA_SERVICE_PID));
        unregisterComponentConfiguration(kuraPid);
    }

    protected void addSelfConfiguringComponent(final ServiceReference<SelfConfiguringComponent> reference) {

        final String kuraPid = makeString(reference.getProperty(ConfigurationService.KURA_SERVICE_PID));
        final String servicePid = getServicePid(reference);

        // A SelfConfiguringComponent may not carry a service.pid at all; register it under its
        // kura.service.pid in that case so it still shows up in the configuration (#6384).
        registerSelfConfiguringComponent(kuraPid, servicePid != null ? servicePid : kuraPid);
    }

    protected void removeSelfConfiguringComponent(final ServiceReference<SelfConfiguringComponent> reference) {

        unregisterComponentConfiguration(makeString(reference.getProperty(ConfigurationService.KURA_SERVICE_PID)));

    }

    protected synchronized void deactivate() {
        logger.info("deactivate...");
        this.stopping = true;
        this.providerReads.close();
        closeIntentJournal();

        if (this.bundleTracker != null) {
            this.bundleTracker.close();
            this.bundleTracker = null;
        }
    }

    void initializeIntentJournal(java.nio.file.Path dataDirectory) throws KuraException {
        if (this.intentJournal != null) { throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR); }
        this.intentJournal = ConfigurationIntentJournal.open(dataDirectory.resolve("configuration-dispatch-journal-v1"));
        ControlledRecovery.registerIntentJournal(this.intentJournal);
    }

    private void closeIntentJournal() {
        if (this.intentJournal != null) {
            ControlledRecovery.unregisterIntentJournal(this.intentJournal);
            try { this.intentJournal.close(); }
            catch (java.io.IOException e) { logger.error("Cannot close configuration dispatch journal", e); }
            this.intentJournal = null;
        }
    }

    private void requireOrdinaryWrite() throws KuraException {
        ControlledRecovery.requireOrdinaryWrite();
        if (this.intentJournal != null) { this.intentJournal.requireOrdinaryWrite(); }
    }

    private ConfigurationIntentJournal.Ticket beginDispatch(String operation, Set<String> scope) throws KuraException {
        // A published DS service always initialized its journal in activate. Unactivated test subclasses have no store.
        return this.intentJournal == null ? null : this.intentJournal.begin(operation, scope);
    }

    private static void completeDispatch(ConfigurationIntentJournal.Ticket ticket) throws KuraException {
        if (ticket != null) { ticket.complete(); }
    }

    // ----------------------------------------------------------------
    //
    // Service APIs
    //
    // ----------------------------------------------------------------

    @Override
    public Set<String> getConfigurableComponentPids() {
        Set<String> result = new HashSet<>();
        result.addAll(this.allActivatedPids);
        result.addAll(this.waittingForActivatedPids);

        return Collections.unmodifiableSet(result);
    }

    // Don't perform internal calls to this method
    @Override
    public List<ComponentConfiguration> getComponentConfigurations() throws KuraException {
        return getComponentConfigurationsInternal();
    }

    @Override
    public List<ComponentConfiguration> getComponentConfigurations(final Filter filter) throws KuraException {
        try (ProviderConfigurationReads.Budget ignored = this.providerReads.budget()) {
            if (filter == null) {
                return getComponentConfigurationsInternal();
            }

            try {
                final ServiceReference<?>[] refs = this.bundleContext.getAllServiceReferences(null, null);
                if (refs == null) {
                    return Collections.emptyList();
                }
                final List<ComponentConfiguration> result = new ArrayList<>(refs.length);
                final Set<String> selectedPids = new HashSet<>();

                for (final ServiceReference<?> ref : refs) {

                    if (!filter.match(ref)) {
                        continue;
                    }

                    final Object kuraServicePid = ref.getProperty(KURA_SERVICE_PID);

                    // The filter applies to registrations; the result contains
                    // one configuration view per matching logical Kura PID.
                    if (kuraServicePid instanceof String && selectedPids.add((String) kuraServicePid)) {
                        final ComponentConfiguration config = getComponentConfigurationInternal((String) kuraServicePid);

                        if (config != null) {
                            result.add(config);
                        }
                    }
                }

                return result;
            } catch (final Exception e) {
                throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR, e);
            }
        }
    }

    // Don't perform internal calls to this method
    @Override
    public ComponentConfiguration getComponentConfiguration(String pid) throws KuraException {
        ComponentConfiguration tempConfig = getComponentConfigurationInternal(pid);
        if (!passwordValuesAreLogical(pid, tempConfig) && tempConfig != null
                && tempConfig.getConfigurationProperties() != null) {
            // Provider maps can be immutable or retained by NM/Asset: never decode them in place.
            if (tempConfig instanceof ComponentConfigurationImpl impl) {
                ComponentConfigurationImpl detached = new ComponentConfigurationImpl(pid, impl.getDefinition(),
                        new HashMap<>(impl.getConfigurationProperties()));
                decryptConfigurationProperties(detached.getConfigurationProperties());
                detached.setLogicalPasswords(true);
                tempConfig = detached;
            } else {
                decryptConfigurationProperties(tempConfig.getConfigurationProperties());
            }
        }
        return tempConfig;
    }

    private boolean passwordValuesAreLogical(String pid, ComponentConfiguration configuration) {
        if (configuration instanceof ComponentConfigurationImpl impl && impl.hasPasswordRepresentation()) {
            return impl.hasLogicalPasswords();
        }
        // Unmarked SCCs retain their legacy storage-decoding contract. A new logical producer opts in explicitly.
        return this.externalConfigurations.owns(pid);
    }

    @Override
    public synchronized ConfigurationRevisionService.Read readRevision(String pid) throws KuraException {
        if (pid == null || pid.isBlank() || pid.getBytes(java.nio.charset.StandardCharsets.UTF_8).length > 512
                || pid.codePoints().anyMatch(Character::isISOControl)) {
            throw new Rejected(Reason.INVALID_ARGUMENT);
        }
        if (this.intentJournal != null && this.intentJournal.revisionsBlocked()) { throw new Rejected(Reason.CONFLICT); }
        // A generic property update must never bypass the network owner's transaction protocol.
        if (this.externalConfigurations.owns(pid)) { throw new Rejected(Reason.UNSUPPORTED); }
        // A provider/snapshot failure can follow an actual CM write. Observation
        // alone cannot prove that submission completed; require explicit recovery.
        if (this.revisionUncertain.contains(pid)) { throw new Rejected(Reason.CONFLICT); }
        ComponentConfiguration current;
        try { current = getComponentConfiguration(pid); }
        catch (ProviderConfigurationReads.Unavailable unavailable) {
            // No writer has been dispatched: an unavailable provider cannot authorize a baseline.
            throw new Rejected(Reason.CONFLICT);
        }
        if (current == null || !pid.equals(current.getPid())) { throw new Rejected(Reason.NOT_FOUND); }
        Map<String, Object> pending = this.revisionPending.get(pid);
        if (pending != null) {
            Map<String, Object> values = current.getConfigurationProperties();
            if (values == null || pending.entrySet().stream()
                    .anyMatch(entry -> !ConfigurationRevision.sameValue(entry.getValue(), values.get(entry.getKey())))) {
                // SelfConfiguringComponent callbacks may still expose the pre-update state.
                // Do not issue a fresh write token for that stale state.
                throw new Rejected(Reason.CONFLICT);
            }
            this.revisionPending.remove(pid);
        }
        RollbackConvergence convergence = this.rollbackConvergence.get(pid);
        if (convergence != null) {
            if (!convergence.matches(current.getConfigurationProperties())) { throw new Rejected(Reason.CONFLICT); }
            this.rollbackConvergence.remove(pid);
        }
        long changes = -1;
        String servicePid = this.servicePidByPid.get(pid);
        if (servicePid != null && this.configurationAdmin != null) {
            try { changes = this.configurationAdmin.getConfiguration(servicePid, "?").getChangeCount(); }
            catch (IOException e) { throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR, e); }
        }
        return new ConfigurationRevisionService.Read(current, this.configurationRevision.token(current, changes,
                this.revisionAdmissions.getOrDefault(pid, 0L)));
    }

    @Override
    public synchronized ComponentConfiguration readExternalConfirmedConfiguration(String pid) throws KuraException {
        if (pid == null || pid.isBlank() || pid.getBytes(java.nio.charset.StandardCharsets.UTF_8).length > 512
                || pid.codePoints().anyMatch(Character::isISOControl)) {
            throw new Rejected(Reason.INVALID_ARGUMENT);
        }
        if (!this.externalConfigurations.owns(pid)) { throw new Rejected(Reason.UNSUPPORTED); }
        ComponentConfiguration confirmed = this.externalConfigurations.confirmed(pid);
        Map<String,Object> properties = ConfigurationRevision.copyEditProperties(confirmed.getConfigurationProperties());
        return new ComponentConfiguration() {
            @Override public String getPid() { return pid; }
            @Override public OCD getDefinition() { return confirmed.getDefinition(); }
            @Override public OCD getLocalizedDefinition(String locale) { return confirmed.getLocalizedDefinition(locale); }
            @Override public Map<String,Object> getConfigurationProperties() { return properties; }
            @Override public String toString() { return "ExternalConfirmedConfiguration[redacted]"; }
        };
    }

    @Override
    public synchronized Map<String, ConfigurationRevisionService.StoredReadView> readStoredRevisionViews(Set<String> pids)
            throws KuraException {
        if (pids == null || pids.isEmpty() || pids.size() > 16) { throw new Rejected(Reason.INVALID_ARGUMENT); }
        Set<String> selected = new TreeSet<>();
        for (String pid : pids) {
            if (pid == null || pid.isBlank() || pid.getBytes(java.nio.charset.StandardCharsets.UTF_8).length > 512
                    || pid.codePoints().anyMatch(Character::isISOControl)) { throw new Rejected(Reason.INVALID_ARGUMENT); }
            selected.add(pid);
        }
        if (this.configurationAdmin == null) { throw new Rejected(Reason.UNSUPPORTED); }
        if (this.intentJournal != null && this.intentJournal.revisionsBlocked()) { throw new Rejected(Reason.CONFLICT); }
        for (String pid : selected) {
            if (this.externalConfigurations.owns(pid) || !this.allActivatedPids.contains(pid)
                    || !pid.equals(this.servicePidByPid.get(pid)) || this.factoryPidByPid.containsKey(pid)) {
                throw new Rejected(Reason.UNSUPPORTED);
            }
            if (this.revisionUncertain.contains(pid) || this.revisionPending.containsKey(pid)
                    || this.rollbackConvergence.containsKey(pid)) { throw new Rejected(Reason.CONFLICT); }
        }
        Map<String, ConfigurationRevisionService.StoredReadView> result = new LinkedHashMap<>();
        for (String pid : selected) { result.put(pid, storedRevisionView(pid)); }
        // No SCC callbacks or CM creations occur in either pass. Independent CM
        // writers cannot silently substitute a different member of this cohort.
        for (String pid : selected) {
            var after = storedRevisionView(pid);
            if (!result.get(pid).revision().equals(after.revision()) || result.get(pid).present() != after.present()) {
                throw new Rejected(Reason.CONFLICT);
            }
        }
        return Collections.unmodifiableMap(result);
    }

    private ConfigurationRevisionService.StoredReadView storedRevisionView(String pid) throws KuraException {
        StringBuilder escaped = new StringBuilder();
        for (char ch : pid.toCharArray()) {
            switch (ch) {
                case '*' -> escaped.append("\\2a");
                case '(' -> escaped.append("\\28");
                case ')' -> escaped.append("\\29");
                case '\\' -> escaped.append("\\5c");
                default -> escaped.append(ch);
            }
        }
        try {
            Configuration[] entries = this.configurationAdmin.listConfigurations("(service.pid=" + escaped + ")");
            if (entries != null && entries.length > 1) { throw new Rejected(Reason.CONFLICT); }
            long changes = -1;
            boolean present = false;
            Map<String, Object> properties = new HashMap<>();
            if (entries != null && entries.length == 1) {
                Configuration entry = entries[0];
                if (entry == null || !pid.equals(entry.getPid()) || entry.getFactoryPid() != null) {
                    throw new Rejected(Reason.CONFLICT);
                }
                long before = entry.getChangeCount();
                Dictionary<String, Object> dictionary = entry.getProperties();
                if (dictionary != null) {
                    for (Enumeration<String> names = dictionary.keys(); names.hasMoreElements();) {
                        String name = names.nextElement();
                        if (name == null) { throw new Rejected(Reason.UNSUPPORTED); }
                        properties.put(name, dictionary.get(name));
                    }
                    properties = ConfigurationRevision.copyEditProperties(properties);
                    present = true;
                }
                changes = entry.getChangeCount();
                if (before != changes || changes < 0) { throw new Rejected(Reason.CONFLICT); }
            }
            ComponentConfiguration detached = new ComponentConfigurationImpl(pid, null,
                    Collections.unmodifiableMap(properties));
            // Separate domain:these original-storage observations grant no
            // generic configuration update admission,even for identical values.
            String revision = this.configurationRevision.storedToken(pid, present, properties, changes,
                    this.revisionAdmissions.getOrDefault(pid, 0L));
            return new ConfigurationRevisionService.StoredRead(detached, revision, present);
        } catch (IOException | org.osgi.framework.InvalidSyntaxException e) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR, e);
        }
    }

    @Override
    public synchronized ConfigurationRevisionService.ReadView readLogicalRevisionView(String pid) throws KuraException {
        // readRevision uses the existing explicit CM/SCC password-source rules.
        var original = readRevision(pid);
        var configuration = original.configuration();
        Map<String,Object> properties = ConfigurationRevision.copyEditProperties(configuration.getConfigurationProperties());
        ComponentConfiguration detached = new ComponentConfiguration() {
            @Override public String getPid() { return pid; }
            @Override public OCD getDefinition() { return configuration.getDefinition(); }
            @Override public OCD getLocalizedDefinition(String locale) { return configuration.getLocalizedDefinition(locale); }
            @Override public Map<String,Object> getConfigurationProperties() { return properties; }
            @Override public String toString() { return "LogicalRevisionExport[redacted]"; }
        };
        long changes = -1;
        String servicePid = this.servicePidByPid.get(pid);
        if (servicePid != null && this.configurationAdmin != null) {
            try { changes = this.configurationAdmin.getConfiguration(servicePid, "?").getChangeCount(); }
            catch (IOException e) { throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR, e); }
        }
        if (!original.revision().equals(this.configurationRevision.token(detached, changes,
                this.revisionAdmissions.getOrDefault(pid,0L)))) { throw new Rejected(Reason.CONFLICT); }
        return new ConfigurationRevisionService.Read(detached, original.revision());
    }

    @Override
    public synchronized Map<String, ComponentConfiguration> readExternalConfirmedConfigurations(Set<String> pids)
            throws KuraException {
        if (pids == null || pids.isEmpty() || pids.size() > 16) {
            throw new Rejected(Reason.INVALID_ARGUMENT);
        }
        Set<String> selected = new TreeSet<>();
        for (String pid : pids) {
            if (pid == null || pid.isBlank() || pid.getBytes(java.nio.charset.StandardCharsets.UTF_8).length > 512
                    || pid.codePoints().anyMatch(Character::isISOControl)) {
                throw new Rejected(Reason.INVALID_ARGUMENT);
            }
            selected.add(pid);
        }
        for (String pid : selected) {
            if (!this.externalConfigurations.owns(pid)) {
                throw new Rejected(Reason.UNSUPPORTED);
            }
        }
        return this.externalConfigurations.confirmedBatch(selected);
    }

    @Override
    public synchronized Applicability applicability(String pid) throws KuraException {
        if (pid == null || pid.isBlank() || pid.getBytes(java.nio.charset.StandardCharsets.UTF_8).length > 512
                || pid.codePoints().anyMatch(Character::isISOControl)) {
            throw new Rejected(Reason.INVALID_ARGUMENT);
        }
        if (this.externalConfigurations.owns(pid)) { throw new Rejected(Reason.UNSUPPORTED); }
        if (this.activatedSelfConfigComponents.contains(pid)) {
            return new Applicability(ComponentKind.SELF_CONFIGURING, true);
        }
        if (this.allActivatedPids.contains(pid) || this.servicePidByPid.containsKey(pid)) {
            return new Applicability(ComponentKind.CONFIGURABLE, false);
        }
        throw new Rejected(Reason.NOT_FOUND);
    }

    @Override
    public synchronized void updateConfigurationsIfUnchanged(List<ComponentConfiguration> configurations,
            Map<String, String> expectedRevisions) throws KuraException {
        requireOrdinaryWrite();
        if (configurations == null || configurations.isEmpty() || configurations.size() > 512
                || expectedRevisions == null || expectedRevisions.size() != configurations.size()) {
            throw new Rejected(Reason.INVALID_ARGUMENT);
        }
        List<ComponentConfiguration> submissions = new ArrayList<>();
        Map<String, Map<String, Object>> pending = new HashMap<>();
        try (ProviderConfigurationReads.Budget ignored = this.providerReads.budget()) {
            for (ComponentConfiguration candidate : configurations) {
                if (candidate == null || candidate.getPid() == null || pending.containsKey(candidate.getPid())) {
                    throw new Rejected(Reason.INVALID_ARGUMENT);
                }
                String pid = candidate.getPid();
                String expected = expectedRevisions.get(pid);
                if (expected == null || !expected.matches("[0-9a-f]{64}")) {
                    throw new Rejected(Reason.INVALID_ARGUMENT);
                }
                ConfigurationRevisionService.Read before = readRevision(pid);
                if (!java.security.MessageDigest.isEqual(expected.getBytes(java.nio.charset.StandardCharsets.US_ASCII),
                        before.revision().getBytes(java.nio.charset.StandardCharsets.US_ASCII))) {
                    throw new Rejected(Reason.CONFLICT);
                }
                if (!revisionTargetTracked(pid)) { throw new Rejected(Reason.UNSUPPORTED); }
                Map<String, Object> patch = ConfigurationRevision.copyEditProperties(candidate.getConfigurationProperties());
                for (String name : Set.of(ConfigurationService.KURA_SERVICE_PID, Constants.SERVICE_PID,
                        ConfigurationAdmin.SERVICE_FACTORYPID, "service.bundleLocation", "component.id", "component.name")) {
                    if (patch.containsKey(name) && !ConfigurationRevision.sameValue(patch.get(name),
                            before.configuration().getConfigurationProperties().get(name))) {
                        throw new Rejected(Reason.INVALID_ARGUMENT);
                    }
                }
                pending.put(pid, ConfigurationRevision.copyEditProperties(patch));
                Map<String, Object> submission = this.activatedSelfConfigComponents.contains(pid)
                        ? ConfigurationRevision.overlay(before.configuration().getConfigurationProperties(), patch) : patch;
                submissions.add(new ComponentConfigurationImpl(pid, null, submission));
            }
        }
        withProviderValidation(submissions, 0, () -> {
            for (String pid : pending.keySet()) { this.revisionAdmissions.merge(pid, 1L, Long::sum); }
            try (var dispatch = beginDispatch("batch", pending.keySet())) {
                updateConfigurations(submissions, true); completeDispatch(dispatch);
            } catch (KuraException | RuntimeException e) {
                this.revisionUncertain.addAll(pending.keySet());
                // A rejection coming back from a dispatched writer cannot be advertised
                // as a pre-submission rejection of the entire batch.
                throw new KuraException(KuraErrorCode.CONFIGURATION_UPDATE, e);
            } catch (Error e) {
                this.revisionUncertain.addAll(pending.keySet());
                throw e;
            }
            this.rollbackConvergence.keySet().removeAll(pending.keySet());
            this.revisionPending.putAll(pending);
        });
    }

    @Override
    public synchronized Map<String, ConfigurationRevisionService.ReadView> readRevisionViews(Set<String> pids)
            throws KuraException {
        try (ProviderConfigurationReads.Budget ignored = this.providerReads.budget()) {
            if (pids == null || pids.size() > 512) { throw new Rejected(Reason.INVALID_ARGUMENT); }
            Map<String, ConfigurationRevisionService.ReadView> result = new HashMap<>();
            for (String pid : new HashSet<>(pids)) {
                ConfigurationRevisionService.Read read = readRevision(pid);
                ComponentConfiguration config = read.configuration();
                OCD definition = config.getDefinition();
                Map<String, Object> properties = ConfigurationRevision.copyEditProperties(config.getConfigurationProperties());
                ComponentConfiguration detached = new ComponentConfiguration() {
                    @Override public String getPid() { return pid; }
                    @Override public OCD getDefinition() { return definition; }
                    @Override public OCD getLocalizedDefinition(String locale) { return config.getLocalizedDefinition(locale); }
                    @Override public Map<String, Object> getConfigurationProperties() { return properties; }
                    @Override public String toString() { return "ConfigurationRevisionService.DetachedConfiguration[redacted]"; }
                };
                result.put(pid, new ConfigurationRevisionService.Read(detached, read.revision()));
            }
            return Collections.unmodifiableMap(result);
        }
    }

    @Override
    public synchronized void applyConfigurationPlanIfUnchanged(List<ComponentConfiguration> updates,
            List<ConfigurationRevisionService.Creation> creations, Set<String> deletions,
            Map<String, String> expectedRevisions) throws KuraException {
        applyConfigurationPlan(updates, creations, deletions, expectedRevisions, null);
    }

    @Override
    public synchronized void applyConfigurationPlanIfUnchanged(List<ComponentConfiguration> updates,
            List<ConfigurationRevisionService.Creation> creations, Set<String> deletions,
            Map<String, String> expectedRevisions, ConfigurationRevisionService.DeletionGuard deletionGuard)
            throws KuraException {
        if (deletionGuard == null) { throw new Rejected(Reason.INVALID_ARGUMENT); }
        applyConfigurationPlan(updates, creations, deletions, expectedRevisions, deletionGuard);
    }

    private void applyConfigurationPlan(List<ComponentConfiguration> updates,
            List<ConfigurationRevisionService.Creation> creations, Set<String> deletions,
            Map<String, String> expectedRevisions, ConfigurationRevisionService.DeletionGuard deletionGuard)
            throws KuraException {
        requireOrdinaryWrite();
        if (updates == null || creations == null || deletions == null || expectedRevisions == null
                || updates.size() + creations.size() + deletions.size() == 0
                || updates.size() + creations.size() + deletions.size() > 512 || expectedRevisions.size() > 512) {
            throw new Rejected(Reason.INVALID_ARGUMENT);
        }
        // Snapshot caller-owned collections before checking or performing any mutation.
        Map<String, String> guards = new HashMap<>(expectedRevisions);
        Set<String> removed = new HashSet<>(deletions);
        Map<String, ComponentConfiguration> before = new HashMap<>();
        try (ProviderConfigurationReads.Budget ignored = this.providerReads.budget()) {
            for (var entry : guards.entrySet()) {
                requirePlanPid(entry.getKey());
                String revision = entry.getValue();
                if (revision == null || !revision.matches("[0-9a-f]{64}")) { throw new Rejected(Reason.INVALID_ARGUMENT); }
                ConfigurationRevisionService.Read read = readRevision(entry.getKey());
                if (!java.security.MessageDigest.isEqual(revision.getBytes(java.nio.charset.StandardCharsets.US_ASCII),
                        read.revision().getBytes(java.nio.charset.StandardCharsets.US_ASCII))) {
                    throw new Rejected(Reason.CONFLICT);
                }
                if (!revisionTargetTracked(entry.getKey())) { throw new Rejected(Reason.UNSUPPORTED); }
                before.put(entry.getKey(), read.configuration());
            }
        }
        for (String pid : removed) {
            requirePlanPid(pid);
            if (!before.containsKey(pid)) { throw new Rejected(Reason.INVALID_ARGUMENT); }
            if (!this.factoryPidByPid.containsKey(pid)) { throw new Rejected(Reason.UNSUPPORTED); }
            this.externalConfigurations.rejectFactoryOperation(pid);
        }
        List<ComponentConfiguration> submissions = new ArrayList<>();
        Map<String, Map<String, Object>> pending = new HashMap<>();
        for (ComponentConfiguration update : new ArrayList<>(updates)) {
            if (update == null) { throw new Rejected(Reason.INVALID_ARGUMENT); }
            String pid = update.getPid(); requirePlanPid(pid);
            if (!before.containsKey(pid) || removed.contains(pid) || pending.containsKey(pid)) {
                throw new Rejected(Reason.INVALID_ARGUMENT);
            }
            Map<String, Object> patch = ConfigurationRevision.copyEditProperties(update.getConfigurationProperties());
            requireUnchangedIdentity(patch, before.get(pid).getConfigurationProperties());
            Map<String, Object> submission = this.activatedSelfConfigComponents.contains(pid)
                    ? ConfigurationRevision.overlay(before.get(pid).getConfigurationProperties(), patch) : patch;
            submissions.add(new ComponentConfigurationImpl(pid, null, submission));
            pending.put(pid, ConfigurationRevision.copyEditProperties(patch));
        }
        List<ConfigurationRevisionService.Creation> copiedCreations = new ArrayList<>();
        Set<String> created = new HashSet<>();
        Set<String> factories = getFactoryComponentPids();
        for (ConfigurationRevisionService.Creation creation : new ArrayList<>(creations)) {
            if (creation == null) { throw new Rejected(Reason.INVALID_ARGUMENT); }
            String pid = creation.pid(); requirePlanPid(pid); requirePlanPid(creation.factoryPid());
            if (!created.add(pid) || pending.containsKey(pid)) { throw new Rejected(Reason.INVALID_ARGUMENT); }
            if (!factories.contains(creation.factoryPid())) { throw new Rejected(Reason.UNSUPPORTED); }
            this.externalConfigurations.rejectFactoryOperation(pid);
            if (!removed.contains(pid)) { requirePlanPidAbsent(pid); }
            Map<String, Object> properties = ConfigurationRevision.copyEditProperties(creation.properties());
            for (String name : Set.of(Constants.SERVICE_PID, "service.bundleLocation", "component.id", "component.name")) {
                if (properties.containsKey(name)) { throw new Rejected(Reason.INVALID_ARGUMENT); }
            }
            if (properties.containsKey(KURA_SERVICE_PID) && !pid.equals(properties.get(KURA_SERVICE_PID))
                    || properties.containsKey(ConfigurationAdmin.SERVICE_FACTORYPID)
                        && !creation.factoryPid().equals(properties.get(ConfigurationAdmin.SERVICE_FACTORYPID))) {
                throw new Rejected(Reason.INVALID_ARGUMENT);
            }
            Map<String, Object> expectedProperties = ConfigurationRevision.copyEditProperties(properties);
            // Factory identity is owned by ConfigurationService; a self-configuring
            // component's public view need not repeat the synthesized CM identity.
            expectedProperties.remove(KURA_SERVICE_PID);
            expectedProperties.remove(ConfigurationAdmin.SERVICE_FACTORYPID);
            properties.put(ConfigurationAdmin.SERVICE_FACTORYPID, creation.factoryPid());
            copiedCreations.add(new ConfigurationRevisionService.Creation(creation.factoryPid(), pid, properties));
            pending.put(pid, expectedProperties);
        }
        List<ComponentConfiguration> validation = new ArrayList<>(submissions);
        for (ConfigurationRevisionService.Creation creation : copiedCreations) {
            validation.add(new ComponentConfigurationImpl(creation.pid(), null, creation.properties()));
        }
        // Replacement creations must validate against the new factory definition and
        // defaults, not the metadata or self-configured values of the deleted instance.
        withProviderValidation(validation, created, 0, () -> {
            if (deletionGuard != null) {
                requireDeletionClosure(deletionGuard, removed, before, validation);
                // Native validation/public-view callbacks can re-enter Core. Check
                // displayed guards again at the final admission boundary.
                try (ProviderConfigurationReads.Budget ignored = this.providerReads.budget()) {
                    for (var entry : guards.entrySet()) {
                        String current = readRevision(entry.getKey()).revision();
                        if (!java.security.MessageDigest.isEqual(entry.getValue().getBytes(java.nio.charset.StandardCharsets.US_ASCII),
                                current.getBytes(java.nio.charset.StandardCharsets.US_ASCII))) { throw new Rejected(Reason.CONFLICT); }
                    }
                }
            }
            Set<String> admitted = new HashSet<>(guards.keySet()); admitted.addAll(created);
            for (String pid : admitted) { this.revisionAdmissions.merge(pid, 1L, Long::sum); }
            try (var dispatch = beginDispatch("plan", admitted)) {
                for (String pid : removed) { deleteFactoryConfiguration(pid, false); }
                for (ConfigurationRevisionService.Creation creation : copiedCreations) {
                    createFactoryConfiguration(creation.factoryPid(), creation.pid(), creation.properties(), false);
                }
                if (submissions.isEmpty()) {
                    // The ordinary batch updater skips snapshots for an empty current
                    // set. A deletion-only plan must persist that empty state too.
                    snapshot();
                } else {
                    updateConfigurations(submissions, true);
                }
                completeDispatch(dispatch);
            } catch (KuraException | RuntimeException e) {
                this.revisionUncertain.addAll(admitted);
                throw new KuraException(KuraErrorCode.CONFIGURATION_UPDATE, e);
            } catch (Error e) {
                this.revisionUncertain.addAll(admitted);
                throw e;
            }
            for (String pid : removed) { this.revisionPending.remove(pid); this.rollbackConvergence.remove(pid); }
            this.rollbackConvergence.keySet().removeAll(pending.keySet());
            this.revisionPending.putAll(pending);
        });
    }

    @Override
    public synchronized void applyConfigurationPlanIfUnchanged(String operationId,
            List<ComponentConfiguration> updates, List<ConfigurationRevisionService.Creation> creations,
            Set<String> deletions, Map<String,String> expectedRevisions) throws KuraException {
        applyRecordedConfigurationPlan(operationId, updates, creations, deletions, expectedRevisions, null);
    }

    @Override
    public synchronized void applyConfigurationPlanIfUnchanged(String operationId,
            List<ComponentConfiguration> updates, List<ConfigurationRevisionService.Creation> creations,
            Set<String> deletions, Map<String,String> expectedRevisions,
            ConfigurationRevisionService.DeletionGuard deletionGuard) throws KuraException {
        if (deletionGuard == null) throw new Rejected(Reason.INVALID_ARGUMENT);
        applyRecordedConfigurationPlan(operationId, updates, creations, deletions, expectedRevisions, deletionGuard);
    }

    private void applyRecordedConfigurationPlan(String operationId, List<ComponentConfiguration> updates,
            List<ConfigurationRevisionService.Creation> creations, Set<String> deletions,
            Map<String,String> expectedRevisions, ConfigurationRevisionService.DeletionGuard deletionGuard)
            throws KuraException {
        ConfigurationOperationStore.uuid(operationId);
        requireOrdinaryWrite();
        if (this.intentJournal == null) throw new Rejected(Reason.UNSUPPORTED);
        var plan = new RecordedConfigurationPlan(updates, creations, deletions, expectedRevisions, deletionGuard);
        try (var operation = this.intentJournal.clientOperation(operationId, plan)) {
            try {
                applyConfigurationPlan(plan.updates, plan.creations, plan.deletions, plan.guards, plan.deletionGuard);
                operation.requireCommitted();
            } catch (KuraException | RuntimeException | Error failure) {
                try { operation.rejectIfUndispatched(failure); }
                catch (KuraException receiptFailure) { failure.addSuppressed(receiptFailure); }
                throw failure;
            }
        }
    }

    private static void requirePlanPid(String pid) throws Rejected {
        if (pid == null || pid.isBlank() || pid.getBytes(java.nio.charset.StandardCharsets.UTF_8).length > 512
                || pid.codePoints().anyMatch(Character::isISOControl)) {
            throw new Rejected(Reason.INVALID_ARGUMENT);
        }
    }

    private void requireDeletionClosure(ConfigurationRevisionService.DeletionGuard guard, Set<String> removed,
            Map<String, ComponentConfiguration> before, List<ComponentConfiguration> proposed) throws KuraException {
        Map<String, String> factories = guard.factoryPids();
        Set<String> pidProperties = guard.pidReferenceProperties();
        if (removed.isEmpty() || factories == null || !factories.keySet().equals(removed)
                || pidProperties == null || pidProperties.size() > 64) { throw new Rejected(Reason.INVALID_ARGUMENT); }
        for (String property : pidProperties) {
            if (property == null || property.isBlank() || property.length() > 256) {
                throw new Rejected(Reason.INVALID_ARGUMENT);
            }
        }
        for (String pid : removed) {
            requirePlanPid(factories.get(pid));
            if (!factories.get(pid).equals(this.factoryPidByPid.get(pid))) { throw new Rejected(Reason.CONFLICT); }
        }
        if (this.configurationAdmin == null || this.bundleContext == null || this.scrService == null) {
            throw new Rejected(Reason.UNSUPPORTED);
        }
        Map<String, List<Map<String, Object>>> targetProperties = new HashMap<>();
        Set<String> registeredTargets = new HashSet<>();
        Set<Long> targetServiceIds = new HashSet<>();
        for (String pid : removed) {
            Map<String, Object> properties = new HashMap<>(before.get(pid).getConfigurationProperties());
            properties.put(KURA_SERVICE_PID, pid); properties.put(ConfigurationAdmin.SERVICE_FACTORYPID, factories.get(pid));
            targetProperties.put(pid, new ArrayList<>(List.of(properties)));
        }
        try (ProviderConfigurationReads.Budget ignored = this.providerReads.budget()) {
            ServiceReference<?>[] references = this.bundleContext.getAllServiceReferences(null, null);
            if (references != null) {
                if (references.length > 16384) { throw new Rejected(Reason.UNSUPPORTED); }
                for (ServiceReference<?> reference : references) {
                    Object pid = reference.getProperty(KURA_SERVICE_PID);
                    if (!(pid instanceof String) || !removed.contains(pid)) { continue; }
                    Map<String, Object> properties = new HashMap<>();
                    for (String key : reference.getPropertyKeys()) {
                        Object value = reference.getProperty(key);
                        if (value != null) { properties.put(key, value); }
                    }
                    targetProperties.get(pid).add(properties); registeredTargets.add((String) pid);
                    Object id = reference.getProperty(Constants.SERVICE_ID);
                    if (id instanceof Number number) { targetServiceIds.add(number.longValue()); }
                }
            }
            Configuration[] configurations = this.configurationAdmin.listConfigurations(null);
            if (configurations != null) {
                if (configurations.length > 16384) { throw new Rejected(Reason.UNSUPPORTED); }
                for (Configuration configuration : configurations) {
                    Dictionary<String, Object> properties = configuration.getProperties();
                    if (properties == null || removed.contains(properties.get(KURA_SERVICE_PID))) { continue; }
                    Map<String, Object> values = new HashMap<>();
                    for (var keys = properties.keys(); keys.hasMoreElements();) {
                        String key = keys.nextElement(); values.put(key, properties.get(key));
                    }
                    requireNoDeletionReferences(values, pidProperties, targetProperties, registeredTargets);
                }
            }
            // Component-owned public views may contain references not repeated in CM.
            for (String pid : new HashSet<>(this.allActivatedPids)) {
                if (removed.contains(pid)) { continue; }
                ComponentConfiguration configuration = getComponentConfiguration(pid);
                if (configuration == null || configuration.getConfigurationProperties() == null) {
                    throw new Rejected(Reason.UNSUPPORTED);
                }
                requireNoDeletionReferences(configuration.getConfigurationProperties(), pidProperties,
                        targetProperties, registeredTargets);
            }
            for (ComponentConfiguration configuration : proposed) {
                if (!removed.contains(configuration.getPid())) {
                    requireNoDeletionReferences(configuration.getConfigurationProperties(), pidProperties,
                            targetProperties, registeredTargets);
                }
            }
            for (var description : this.scrService.getComponentDescriptionDTOs()) {
                for (var component : this.scrService.getComponentConfigurationDTOs(description)) {
                    Object pid = component.properties == null ? null : component.properties.get(KURA_SERVICE_PID);
                    if (removed.contains(pid)) { continue; }
                    if (component.satisfiedReferences != null) {
                        for (var reference : component.satisfiedReferences) {
                            if (isOwnConfigurationObserver(component.id, reference.name)
                                    || isDeclaredDeletionObserver(description, reference.name, reference.target)) { continue; }
                            if (reference.boundServices != null) {
                                for (var bound : reference.boundServices) {
                                    if (targetServiceIds.contains(bound.id)) { throw new Rejected(Reason.CONFLICT); }
                                }
                            }
                            if (reference.target != null) {
                                requireNoDeletionFilter(reference.target, targetProperties, registeredTargets);
                            }
                        }
                    }
                    if (component.unsatisfiedReferences != null) {
                        for (var reference : component.unsatisfiedReferences) {
                            if (reference.target != null) {
                                requireNoDeletionFilter(reference.target, targetProperties, registeredTargets);
                            }
                        }
                    }
                }
            }
        } catch (Rejected e) { throw e; }
        catch (ProviderConfigurationReads.Unavailable e) { throw new Rejected(Reason.CONFLICT); }
        catch (Exception e) { throw new Rejected(Reason.UNSUPPORTED); }
    }

    private static boolean isDeclaredDeletionObserver(
            org.osgi.service.component.runtime.dto.ComponentDescriptionDTO description,
            String referenceName, String runtimeTarget) {
        if (description == null || description.properties == null || description.references == null
                || referenceName == null || runtimeTarget != null) { return false; }
        Object declaration = description.properties.get(ConfigurationRevisionService.DELETION_OBSERVER_REFERENCES);
        String[] names = declaration instanceof String name ? new String[] { name }
                : declaration instanceof String[] array ? array : new String[0];
        if (names.length == 0 || names.length > 64 || !java.util.Arrays.asList(names).contains(referenceName)) {
            return false;
        }
        for (var reference : description.references) {
            if (referenceName.equals(reference.name) && "0..n".equals(reference.cardinality)
                    && "dynamic".equals(reference.policy) && reference.target == null
                    && reference.unbind != null && !reference.unbind.isBlank()) { return true; }
        }
        return false;
    }

    private boolean isOwnConfigurationObserver(long componentId, String referenceName) {
        if (this.ctx == null || this.ctx.getProperties() == null) { return false; }
        Object id = this.ctx.getProperties().get("component.id");
        return id instanceof Number number && number.longValue() == componentId
                && ("ConfigurableComponent".equals(referenceName) || "SelfConfiguringComponent".equals(referenceName));
    }

    private void requireNoDeletionReferences(Map<String, Object> values, Set<String> pidProperties,
            Map<String, List<Map<String, Object>>> targets, Set<String> registeredTargets) throws Rejected {
        if (values.size() > 4096) { throw new Rejected(Reason.UNSUPPORTED); }
        for (var entry : values.entrySet()) {
            if (entry.getValue() == null) { continue; }
            if (pidProperties.contains(entry.getKey())) {
                if (!(entry.getValue() instanceof String)) { throw new Rejected(Reason.UNSUPPORTED); }
                if (targets.containsKey(entry.getValue())) { throw new Rejected(Reason.CONFLICT); }
            }
            if (entry.getKey().endsWith(".target")) {
                if (!(entry.getValue() instanceof String filter)) { throw new Rejected(Reason.UNSUPPORTED); }
                requireNoDeletionFilter(filter, targets, registeredTargets);
            }
        }
    }

    private void requireNoDeletionFilter(String expression, Map<String, List<Map<String, Object>>> targets,
            Set<String> registeredTargets) throws Rejected {
        if (expression.length() > 8192) { throw new Rejected(Reason.UNSUPPORTED); }
        final Filter filter;
        try { filter = FrameworkUtil.createFilter(expression); }
        catch (InvalidSyntaxException e) { throw new Rejected(Reason.UNSUPPORTED); }
        boolean pidOnly = expression.matches("\\(kura\\.service\\.pid=(?:\\\\.|[^()])*\\)");
        for (var target : targets.entrySet()) {
            for (Map<String, Object> properties : target.getValue()) {
                if (filter.matches(properties)) { throw new Rejected(Reason.CONFLICT); }
            }
            // Without an actual service dictionary, arbitrary filters can depend on
            // metadata missing from CM. A literal PID filter is still decidable.
            if (!pidOnly && !registeredTargets.contains(target.getKey())) { throw new Rejected(Reason.UNSUPPORTED); }
        }
    }

    private void requirePlanPidAbsent(String pid) throws KuraException {
        if (this.revisionUncertain.contains(pid) || this.revisionPending.containsKey(pid) || this.rollbackConvergence.containsKey(pid)
                || this.allActivatedPids.contains(pid) || this.waittingForActivatedPids.contains(pid)
                || this.servicePidByPid.containsKey(pid) || this.factoryPidByPid.containsKey(pid)) {
            throw new Rejected(Reason.CONFLICT);
        }
        // listConfigurations is read-only; getConfiguration would create a dormant entry.
        if (this.configurationAdmin == null) { throw new Rejected(Reason.UNSUPPORTED); }
        try {
            Configuration[] configurations = this.configurationAdmin.listConfigurations(null);
            if (configurations == null) { return; }
            for (Configuration configuration : configurations) {
                Dictionary<String, Object> properties = configuration.getProperties();
                if (pid.equals(configuration.getPid()) || properties != null
                        && (pid.equals(properties.get(KURA_SERVICE_PID)) || pid.equals(properties.get(Constants.SERVICE_PID)))) {
                    throw new Rejected(Reason.CONFLICT);
                }
            }
        } catch (IOException | org.osgi.framework.InvalidSyntaxException e) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR, e);
        }
    }

    private static void requireUnchangedIdentity(Map<String, Object> patch, Map<String, Object> before) throws Rejected {
        for (String name : Set.of(KURA_SERVICE_PID, Constants.SERVICE_PID, ConfigurationAdmin.SERVICE_FACTORYPID,
                "service.bundleLocation", "component.id", "component.name")) {
            if (patch.containsKey(name) && !ConfigurationRevision.sameValue(patch.get(name), before.get(name))) {
                throw new Rejected(Reason.INVALID_ARGUMENT);
            }
        }
    }

    @Override
    public synchronized void updateRevision(String pid, String expectedRevision, Map<String, Object> properties)
            throws KuraException {
        requireOrdinaryWrite();
        if (expectedRevision == null || !expectedRevision.matches("[0-9a-f]{64}")) {
            throw new Rejected(Reason.INVALID_ARGUMENT);
        }
        Map<String, Object> patch = ConfigurationRevision.copyPatch(properties);
        ConfigurationRevisionService.Read before = readRevision(pid);
        if (!java.security.MessageDigest.isEqual(expectedRevision.getBytes(java.nio.charset.StandardCharsets.US_ASCII),
                before.revision().getBytes(java.nio.charset.StandardCharsets.US_ASCII))) {
            throw new Rejected(Reason.CONFLICT);
        }
        var attributes = ConfigurationRevision.attributes(before.configuration().getDefinition());
        for (var entry : patch.entrySet()) {
            AD attribute = attributes.get(entry.getKey());
            if (Set.of(ConfigurationService.KURA_SERVICE_PID, Constants.SERVICE_PID,
                    ConfigurationAdmin.SERVICE_FACTORYPID, "service.bundleLocation", "component.id", "component.name")
                        .contains(entry.getKey()) || attribute == null || !ConfigurationRevision.accepts(attribute, entry.getValue())) {
                throw new Rejected(Reason.INVALID_ARGUMENT);
            }
                if (Math.abs((long) attribute.getCardinality()) == 1
                        && ConfigurationConstraints.isScalarValue(attribute,
                                before.configuration().getConfigurationProperties().get(entry.getKey()))
                        != ConfigurationConstraints.isScalarValue(attribute, entry.getValue())) {
                    throw new Rejected(Reason.INVALID_ARGUMENT);
                }
            var constraint = ConfigurationConstraints.value(attribute, entry.getValue());
            if (constraint == ConfigurationConstraints.Status.UNSUPPORTED) { throw new Rejected(Reason.UNSUPPORTED); }
            if (constraint != ConfigurationConstraints.Status.SATISFIED) { throw new Rejected(Reason.INVALID_ARGUMENT); }
        }
        if (!revisionTargetTracked(pid)) { throw new Rejected(Reason.UNSUPPORTED); }
        Map<String, Object> submission = this.activatedSelfConfigComponents.contains(pid)
                ? ConfigurationRevision.overlay(before.configuration().getConfigurationProperties(), patch)
                : ConfigurationRevision.copyPatch(patch);
        withProviderValidation(List.of(new ComponentConfigurationImpl(pid, null, submission)), 0, () -> {
            // Invalidate admission even if the legacy update later reports a partial failure.
            this.revisionAdmissions.merge(pid, 1L, Long::sum);
            try (var dispatch = beginDispatch("single", Set.of(pid))) {
                updateConfiguration(pid, submission, true); completeDispatch(dispatch);
            } catch (KuraException | RuntimeException e) {
                this.revisionUncertain.add(pid);
                // Entering the writer can already have changed CM. A downstream
                // Rejected must not masquerade as a pre-admission rejection.
                throw new KuraException(KuraErrorCode.CONFIGURATION_UPDATE, e);
            } catch (Error e) {
                this.revisionUncertain.add(pid);
                throw e;
            }
            this.rollbackConvergence.remove(pid);
            this.revisionPending.put(pid, patch);
        });
    }

    protected boolean revisionTargetTracked(String pid) throws KuraException {
        try { return this.allActivatedPids.contains(pid) && getRegisteredOCD(pid) != null; }
        catch (ProviderConfigurationReads.Unavailable unavailable) {
            throw new Rejected(Reason.CONFLICT);
        }
    }

    @Override
    public synchronized void updateConfiguration(String pidToUpdate, Map<String, Object> propertiesToUpdate)
            throws KuraException { // don't call this method internally
        updateConfiguration(pidToUpdate, propertiesToUpdate, true);
    }

    @Override
    public synchronized void updateConfiguration(String pidToUpdate, Map<String, Object> propertiesToUpdate,
            boolean takeSnapshot) throws KuraException { // don't call this method internally
        List<ComponentConfiguration> configs = new ArrayList<>();
        ComponentConfigurationImpl cci = new ComponentConfigurationImpl(pidToUpdate, null, propertiesToUpdate);
        configs.add(cci);
        updateConfigurations(configs, takeSnapshot);
    }

    // Don't perform internal calls to this method
    @Override
    public synchronized void updateConfigurations(List<ComponentConfiguration> configsToUpdate) throws KuraException {
        updateConfigurations(configsToUpdate, true);
    }

    @Override
    public synchronized void updateConfigurations(List<ComponentConfiguration> configsToUpdate, boolean takeSnapshot)
            throws KuraException {
        requireOrdinaryWrite(); // don't call this method internally
        this.externalConfigurations.validate(configsToUpdate, ChangeSource.CONFIGURATION_UPDATE);
        withProviderValidation(configsToUpdate, 0, () -> {
            for (ComponentConfiguration config : configsToUpdate) {
                if (config != null) {
                    ComponentUtil.encryptConfigurationProperties(config.getConfigurationProperties(), this.cryptoService);
                }
            }
            // only encrypted properties are passed to internal methods
            updateConfigurationsInternal(configsToUpdate, takeSnapshot);
            // An explicit legacy update may supersede a submitted conditional update.
            for (ComponentConfiguration config : configsToUpdate) {
                if (config != null) {
                    this.revisionPending.remove(config.getPid()); this.rollbackConvergence.remove(config.getPid()); this.revisionUncertain.remove(config.getPid());
                }
            }
        });
    }

    private void withProviderValidation(List<ComponentConfiguration> configurations, int index,
            ProviderDefinition.Write write) throws KuraException {
        withProviderValidation(configurations, Collections.emptySet(), index, write);
    }

    private void withProviderValidation(List<ComponentConfiguration> configurations, Set<String> creatingPids, int index,
            ProviderDefinition.Write write) throws KuraException {
        try (ProviderConfigurationReads.Budget budget = this.providerReads.budget()) {
            validateProviders(configurations, creatingPids, index, () -> {
                // The writer and its snapshot start their own read phase. Expiry
                // during validation must never be inherited as a dispatched failure.
                budget.close();
                write.run();
            });
        }
    }

    private void validateProviders(List<ComponentConfiguration> configurations, Set<String> creatingPids, int index,
            ProviderDefinition.Write write) throws KuraException {
        for (int i = index; i < configurations.size(); i++) {
            ComponentConfiguration proposed = configurations.get(i);
            OCD definition = proposed == null || creatingPids.contains(proposed.getPid()) ? null : getOCDForPid(proposed.getPid());
            if (definition == null && proposed != null && proposed.getConfigurationProperties() != null) {
                Object factory = proposed.getConfigurationProperties().get(ConfigurationAdmin.SERVICE_FACTORYPID);
                if (factory instanceof String factoryPid) { definition = this.ocds.get(factoryPid); }
            }
            if (definition instanceof ProviderDefinition provider) {
                int next = i + 1;
                provider.withSource(() -> {
                    Map<String, Object> values = provider.defaultProperties(this.ctx);
                    decryptConfigurationProperties(values);
                    if (!creatingPids.contains(proposed.getPid()) && this.allActivatedPids.contains(proposed.getPid())) {
                        ComponentConfiguration current;
                        try { current = getComponentConfiguration(proposed.getPid()); }
                        catch (ProviderConfigurationReads.Unavailable unavailable) { throw new Rejected(Reason.CONFLICT); }
                        if (current != null && current.getConfigurationProperties() != null) {
                            values.putAll(current.getConfigurationProperties());
                        }
                    }
                    if (proposed.getConfigurationProperties() != null) { values.putAll(proposed.getConfigurationProperties()); }
                    provider.withValidatedProperties(values, () -> validateProviders(configurations, creatingPids, next, write));
                });
                return;
            }
        }
        write.run();
    }

    // ----------------------------------------------------------------
    //
    // Service APIs: Factory Management
    //
    // ----------------------------------------------------------------
    @Override
    public Set<String> getFactoryComponentPids() {
        return Collections.unmodifiableSet(
                this.factoryPids.stream().map(TrackedComponentFactory::getFactoryPid).collect(Collectors.toSet()));
    }

    @Override
    public ComponentConfiguration getDefaultComponentConfiguration(String pid) throws KuraException {
        Tocd ocd = getOCDForPid(pid);
        if (this.activatedSelfConfigComponents.contains(pid)) {
            ComponentConfiguration configuration = getSelfConfiguringComponentConfiguration(pid);
            if (configuration == null) {
                return null;
            }
            ocd = (Tocd) configuration.getDefinition();
        }
        Map<String, Object> props = ComponentUtil.getDefaultProperties(ocd, this.ctx);
        decryptConfigurationProperties(props);
        return new ComponentConfigurationImpl(pid, ocd, props);
    }

    @Override
    public synchronized void createFactoryConfiguration(String factoryPid, String pid, Map<String, Object> properties,
            boolean takeSnapshot) throws KuraException {
        requireOrdinaryWrite();
        Map<String, Object> candidate = properties == null ? new HashMap<>() : new HashMap<>(properties);
        candidate.put(ConfigurationAdmin.SERVICE_FACTORYPID, factoryPid);
        withProviderValidation(List.of(new ComponentConfigurationImpl(pid, null, candidate)), 0, () ->
                createFactoryConfigurationInternal(factoryPid, pid,
                        ComponentUtil.encryptConfigurationProperties(properties, this.cryptoService, true), takeSnapshot));
    }

    private synchronized void createFactoryConfigurationInternal(String factoryPid, String pid,
            Map<String, Object> properties, boolean takeSnapshot) throws KuraException {
        this.externalConfigurations.rejectFactoryOperation(pid);
        if (pid == null) {
            throw new KuraException(KuraErrorCode.INVALID_PARAMETER, "pid cannot be null");
        } else if (this.servicePidByPid.containsKey(pid)) {
            throw new KuraException(KuraErrorCode.INVALID_PARAMETER, "pid " + pid + " already exists");
        }

        try {
            // Second argument in createFactoryConfiguration is a bundle location. If left null the new bundle location
            // will be bound to the location of the first bundle that registers a Managed Service Factory with a
            // corresponding PID
            logger.info("Creating new configuration for factory pid {} and pid {}", factoryPid, pid);
            Configuration config = this.configurationAdmin.createFactoryConfiguration(factoryPid, null);
            String servicePid = config.getPid();

            logger.info("Updating newly created configuration for pid {}", pid);

            Map<String, Object> mergedProperties = new HashMap<>();
            if (properties != null) {
                mergedProperties.putAll(properties);
            }

            OCD ocd = this.ocds.get(factoryPid);
            mergeWithDefaults(ocd, mergedProperties);

            mergedProperties.put(ConfigurationService.KURA_SERVICE_PID, pid);

            trackPasswordProperties(pid, mergedProperties);

            Dictionary<String, Object> dict = CollectionsUtil.mapToDictionary(mergedProperties);
            config.updateIfDifferent(dict);

            registerNewFactoryComponentConfiguration(pid, servicePid, factoryPid);

            this.pendingDeletePids.remove(pid);

            if (takeSnapshot) {
                snapshot();
            }
        } catch (Exception e) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR, e,
                    "Cannot create component instance for factory " + factoryPid);
        }
    }

    @Override
    public synchronized void deleteFactoryConfiguration(String pid, boolean takeSnapshot) throws KuraException {
        requireOrdinaryWrite();
        this.externalConfigurations.rejectFactoryOperation(pid);
        if (pid == null) {
            throw new KuraException(KuraErrorCode.INVALID_PARAMETER, "pid cannot be null");
        }

        try {
            final Configuration[] configurations = this.configurationAdmin.listConfigurations(null);

            if (configurations == null) {
                logger.warn("ConfigurationAdmin has no configurations");
                return;
            }

            final Optional<Configuration> config = Arrays.stream(configurations).filter(c -> {
                final Object kuraServicePid = c.getProperties().get(KURA_SERVICE_PID);
                final String factoryPid = c.getFactoryPid();
                return pid.equals(kuraServicePid) && factoryPid != null;
            }).findAny();

            if (!config.isPresent()) {
                logger.warn("The component with kura.service.pid {} does not exist or it is not a Factory Component",
                        pid);
                return;
            }

            logger.info("Deleting factory configuration for component with pid {}...", pid);

            config.get().delete();

            unregisterComponentConfiguration(pid);

            this.pendingDeletePids.add(pid);

            if (takeSnapshot) {
                snapshot();
            }
            logger.info("Deleting factory configuration for component with pid {}...done", pid);
        } catch (Exception e) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR, e, "Cannot delete component instance " + pid);
        }
    }

    // ----------------------------------------------------------------
    //
    // Service APIs: Snapshot Management
    //
    // ----------------------------------------------------------------

    @Override
    public synchronized long snapshot() throws KuraException {
        requireOrdinaryWrite();
        logger.info("Writing snapshot - Getting component configurations...");

        List<ComponentConfiguration> configs = buildCurrentConfiguration(null);

        return saveSnapshot(configs);
    }

    @Override
    public long rollback() throws KuraException {
        requireOrdinaryWrite();
        // get the second-last most recent snapshot
        // and rollback to that one.
        Set<Long> ids = getSnapshots();
        if (ids.size() < 2) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_SNAPSHOT_NOT_FOUND, null, "No Snapshot Available");
        }

        // rollback to the second last snapshot
        Long[] snapshots = ids.toArray(new Long[] {});
        Long id = snapshots[ids.size() - 2];

        rollback(id);
        return id;
    }

    @Override
    public synchronized void rollback(long id) throws KuraException {
        requireOrdinaryWrite();
        logger.info("Rolling back to snapshot {}...", id);
        final Map<String, ComponentConfiguration> snapshotConfigs = getSnapshotConfigs(id);
        final Map<String, Configuration> currentConfigs = getCurrentConfigs();
        this.externalConfigurations.validate(snapshotConfigs.values(), ChangeSource.SNAPSHOT_ROLLBACK);
        final RollbackPreparation prepared = prepareRollback(snapshotConfigs, currentConfigs);
        withRollbackSources(prepared.sources(), 0, () -> {
            // Only a completely prepared rollback enters its mutation phase. Keep
            // the scope closed on every failure, including owner apply and Errors.
            for (String pid : prepared.affected()) { this.revisionAdmissions.merge(pid, 1L, Long::sum); }
            this.revisionUncertain.addAll(prepared.affected());
            try (var dispatch = beginDispatch("rollback", prepared.affected())) {
                this.externalConfigurations.apply(prepared.snapshots().values(), ChangeSource.SNAPSHOT_ROLLBACK);
                List<Throwable> causes = new ArrayList<>();
                Iterator<Entry<String, Configuration>> current = currentConfigs.entrySet().iterator();
                while (current.hasNext()) {
                    manageCurrentConfigs(causes, prepared.defaults(), prepared.deletions(), current);
                }
                for (ComponentConfiguration configuration : prepared.snapshots().values()) {
                    manageSnapshotConfigs(causes, currentConfigs, configuration);
                }
                if (!causes.isEmpty()) { throw new KuraPartialSuccessException("Rollback", causes); }
                final SortedSet<Long> snapshotIds = getSnapshotsInternal();
                if (snapshotIds.isEmpty() || id != snapshotIds.last()) {
                    List<ComponentConfiguration> logical = prepared.snapshots().values().stream().map(config -> {
                        RollbackConvergence convergence = prepared.convergence().get(config.getPid());
                        return (ComponentConfiguration) new ComponentConfigurationImpl(config.getPid(), null,
                                convergence == null ? config.getConfigurationProperties() : convergence.snapshotProperties());
                    }).collect(Collectors.toList());
                    for (ComponentConfiguration configuration : logical) {
                        ((ComponentConfigurationImpl) configuration).setLogicalPasswords(true);
                    }
                    saveSnapshot(logical);
                }
                completeDispatch(dispatch);
                this.pendingDeletePids.removeAll(prepared.affected());
                this.revisionPending.keySet().removeAll(prepared.affected());
                this.rollbackConvergence.keySet().removeAll(prepared.affected());
                this.rollbackConvergence.putAll(prepared.convergence());
                this.revisionUncertain.removeAll(prepared.affected());
            } catch (Rejected | RuntimeException failure) {
                throw new KuraException(KuraErrorCode.CONFIGURATION_UPDATE, failure);
            }
        });
    }

    private record RollbackPreparation(Map<String, ComponentConfiguration> snapshots,
            Map<String, ComponentConfiguration> defaults, Set<String> deletions,
            List<ProviderDefinition> sources, Set<String> affected, Map<String, RollbackConvergence> convergence) { }

    private RollbackPreparation prepareRollback(Map<String, ComponentConfiguration> snapshots,
            Map<String, Configuration> current) throws KuraException {
        Map<String, ComponentConfiguration> preparedSnapshots = new HashMap<>();
        Map<String, ComponentConfiguration> defaults = new HashMap<>();
        Map<String, ProviderDefinition> sources = new LinkedHashMap<>();
        Map<String, RollbackConvergence> convergence = new HashMap<>();
        Set<String> deletions = new HashSet<>(), affected = new HashSet<>();
        try (ProviderConfigurationReads.Budget ignored = this.providerReads.budget()) {
            for (ComponentConfiguration configuration : snapshots.values()) {
                String pid = configuration.getPid();
                if (this.externalConfigurations.owns(pid)) { preparedSnapshots.put(pid, configuration); continue; }
                preparedSnapshots.put(pid, prepareRollbackConfiguration(configuration,
                        Optional.ofNullable(current.get(pid)), sources, convergence));
                affected.add(pid);
            }
            for (Entry<String, Configuration> entry : current.entrySet()) {
                String pid = entry.getKey();
                if (this.externalConfigurations.owns(pid)) { continue; }
                ComponentConfiguration snapshot = snapshots.get(pid);
                if (!isFactoryComponent(entry)) {
                    if (snapshot == null && this.allActivatedPids.contains(pid)) {
                        defaults.put(pid, prepareRollbackConfiguration(
                                new ComponentConfigurationImpl(pid, null, new HashMap<>()),
                                Optional.of(entry.getValue()), sources, convergence));
                        affected.add(pid);
                    }
                } else if (snapshot == null || !Objects.equals(entry.getValue().getFactoryPid(),
                        snapshot.getConfigurationProperties().get(ConfigurationAdmin.SERVICE_FACTORYPID))) {
                    deletions.add(pid); affected.add(pid);
                }
            }
        } catch (ProviderConfigurationReads.Unavailable unavailable) { throw new Rejected(Reason.CONFLICT); }
        return new RollbackPreparation(preparedSnapshots, defaults, deletions,
                new ArrayList<>(sources.values()), affected, convergence);
    }

    private ComponentConfiguration prepareRollbackConfiguration(ComponentConfiguration configuration,
            Optional<Configuration> existing, Map<String, ProviderDefinition> sources,
            Map<String, RollbackConvergence> convergence) throws KuraException {
        Map<String, Object> values = new HashMap<>(configuration.getConfigurationProperties());
        String factory = Optional.ofNullable(values.get(ConfigurationAdmin.SERVICE_FACTORYPID))
                .filter(String.class::isInstance).map(String.class::cast).orElse(null);
        OCD definition;
        // Replacing a factory must not merge defaults from the old instance.
        if (factory != null && (existing.isEmpty() || existing.get().getFactoryPid() != null
                && !factory.equals(existing.get().getFactoryPid()))) {
            definition = this.ocds.get(factory);
        } else if (factory == null && existing.isPresent() && existing.get().getFactoryPid() != null) {
            definition = this.ocds.get(configuration.getPid());
        } else { definition = getRegisteredOCD(configuration.getPid()); }
        Map<String, Object> defaults = definition == null ? Map.of() : getDefaultProperties(definition);
        Set<String> passwords = definition == null || definition.getAD() == null ? Set.of()
                : definition.getAD().stream().filter(ad -> ad.getType() == Scalar.PASSWORD)
                        .map(AD::getId).collect(Collectors.toSet());
        RollbackConvergence.Prepared prepared = RollbackConvergence.prepare(values, defaults, passwords, this.cryptoService);
        convergence.put(configuration.getPid(), prepared.convergence());
        if (definition instanceof ProviderDefinition provider) { sources.putIfAbsent(provider.generation(), provider); }
        return new ComponentConfigurationImpl(configuration.getPid(), null, prepared.stored());
    }

    private void withRollbackSources(List<ProviderDefinition> sources, int index,
            ProviderDefinition.Write write) throws KuraException {
        if (index == sources.size()) { write.run(); return; }
        sources.get(index).withSource(() -> withRollbackSources(sources, index + 1, write));
    }

    @Override
    public Set<Long> getSnapshots() throws KuraException {
        return getSnapshotsInternal();
    }

    @Override
    public List<ComponentConfiguration> getSnapshot(long sid) throws KuraException {
        List<ComponentConfiguration> returnConfigs = new ArrayList<>();

        XmlComponentConfigurations xmlConfigs = loadEncryptedSnapshotFileContent(sid);
        if (xmlConfigs != null) {
            List<ComponentConfiguration> configs = xmlConfigs.getConfigurations();
            if (!xmlConfigs.hasLogicalPasswords()) {
                for (ComponentConfiguration config : configs) {
                    if (config != null && config.getConfigurationProperties() != null) {
                        decryptConfigurationProperties(config.getConfigurationProperties());
                    }
                }
            }

            returnConfigs.addAll(xmlConfigs.getConfigurations());
        }

        return returnConfigs;
    }

    // ----------------------------------------------------------------
    //
    // Package APIs
    //
    // ----------------------------------------------------------------
    synchronized void registerComponentOCD(String metatypePid, Tocd ocd, boolean isFactory, final Bundle provider)
            throws KuraException {
        // metatypePid is either the 'pid' or 'factoryPid' attribute of the MetaType Designate element
        // 'pid' matches a service.pid, not a kura.service.pid
        logger.info("Registering metatype pid: {} ...", metatypePid);

        rememberPasswordMetadata(metatypePid, this.ocds.get(metatypePid));
        this.ocds.put(metatypePid, ocd);
        rememberPasswordMetadata(metatypePid, ocd);
        this.factoryPids.removeIf(factory -> metatypePid.equals(factory.getFactoryPid()));

        if (ocd instanceof ProviderDefinition dynamic) {
            dynamic.withSource(() -> seedComponentDefaults(metatypePid, ocd, isFactory, provider));
        } else { seedComponentDefaults(metatypePid, ocd, isFactory, provider); }
    }

    private void seedComponentDefaults(String metatypePid, Tocd ocd, boolean isFactory, Bundle provider)
            throws KuraException {
        if (isFactory) {
            registerFactoryComponentOCD(metatypePid, ocd, provider);
        } else {
            try {
                updateWithDefaultConfigurationForNonFactoryInstance(metatypePid, ocd);
            } catch (IOException e) {
                throw KuraException.internalError(e);
            }
        }
    }

    synchronized void onBundleRemoved(final Bundle bundle) {
        Map<String, MetadataDefinition> previous = this.bundleMetadata.remove(bundle);
        if (previous != null) { reconcileMetadata(previous.keySet()); }
        this.factoryPids.removeIf(factory -> java.util.Objects.equals(factory.getProviderBundle(), bundle));
    }

    synchronized void replaceBundleMetadata(Bundle bundle, Map<String, MetadataDefinition> definitions) {
        if (this.stopping) { return; }
        Map<String, MetadataDefinition> previous = this.bundleMetadata.put(bundle, Map.copyOf(definitions));
        Set<String> affected = new HashSet<>(definitions.keySet());
        if (previous != null) { affected.addAll(previous.keySet()); }
        reconcileMetadata(affected);
    }

    private void reconcileMetadata(Set<String> pids) {
        for (String pid : pids) {
            rememberPasswordMetadata(pid, this.ocds.get(pid));
            var candidates = this.bundleMetadata.entrySet().stream().filter(entry -> entry.getValue().containsKey(pid)).toList();
            this.factoryPids.removeIf(factory -> pid.equals(factory.getFactoryPid()));
            if (candidates.size() != 1) {
                this.ocds.remove(pid);
                if (candidates.size() > 1) { logger.warn("Ambiguous metadata owner for pid {}", pid); }
                continue;
            }
            var owner = candidates.get(0); MetadataDefinition metadata = owner.getValue().get(pid);
            try { registerComponentOCD(pid, metadata.definition(), metadata.factory(), owner.getKey()); }
            catch (KuraException | RuntimeException e) { logger.warn("Metadata default refresh unavailable for pid {}", pid); }
        }
    }

    private void rememberPasswordMetadata(String metatypePid, Tocd definition) {
        if (definition == null) { return; }
        Set<String> names = definition.getAD().stream().filter(attribute -> attribute.getType() == Scalar.PASSWORD)
                .map(AD::getId).collect(java.util.stream.Collectors.toSet());
        if (names.isEmpty()) { return; }
        Set<String> pids = new HashSet<>(); pids.add(metatypePid);
        this.servicePidByPid.forEach((pid, servicePid) -> {
            if (metatypePid.equals(servicePid) || metatypePid.equals(this.factoryPidByPid.get(pid))) { pids.add(pid); }
        });
        synchronized (this.passwordPropertiesLock) {
            for (String pid : pids) {
                this.passwordPropertiesByPid.computeIfAbsent(pid, ignored -> new HashSet<>()).addAll(names);
            }
        }
    }

    synchronized void registerComponentConfiguration(String pid, final String servicePid, final String factoryPid) {
        if (factoryPid != null) {// factory instance
            if (pid == null || servicePid == null) {
                logger.error("Either PID (kura.service.pid) {} or Service PID (service.pid) {} is null", pid,
                        servicePid);
                return;
            }
        } else // non factory instance
        {
            if (servicePid == null) {
                return;
            } else if (pid == null) {
                pid = servicePid;
            }
        }

        if (this.waittingForActivatedPids.contains(pid)) {
            this.waittingForActivatedPids.remove(pid);
        }
        if (this.allActivatedPids.contains(pid)) {
            logger.error("Error create component, have doublic pid:{}", pid);
            try {
                Configuration config = this.configurationAdmin.getConfiguration(servicePid, "?");
                config.delete();
            } catch (IOException e) {
                logger.error("delete service component error,servicePid:{}", servicePid);
            }
            unregisterComponentConfiguration(pid);
            return;
        }
        logger.info("Registering ConfigurableComponent - pid:{},servicePid:{},factoryPid:{} ....", pid, servicePid,
                factoryPid);
        if (factoryPid != null) {
            if (!this.factoryPidByPid.containsKey(pid)) {
                if (this.servicePidByPid.containsKey(pid)) {
                    logger.error("servicePid:{} did not deleted,PID is:{},factoryPid is:{}", servicePid, pid,
                            factoryPid);
                }
                logger.info("factoryPidByPid:{} reCreated,PID is:{}", factoryPid, pid);
                this.factoryPidByPid.put(pid, factoryPid);
            }
        } else if (this.servicePidByPid.containsKey(pid)) {
            logger.error("non factory conponent is already created,servicePidByPid is:{},PID is:{}", servicePid, pid);
            logger.error("exsit non factory conponent servicePidByPid is:{},PID is:{}", this.servicePidByPid.get(pid),
                    pid);
        }
        this.servicePidByPid.put(pid, servicePid);
        this.allActivatedPids.add(pid);
        logger.info("Registering ConfigurableComponent - {}....Done", pid);
    }

    synchronized void registerNewFactoryComponentConfiguration(final String pid, final String servicePid,
            final String factoryPid) throws KuraException {
        if (pid == null || servicePid == null) {
            logger.warn("Either PID (kura.service.pid) {} or Service PID (service.pid) {} is null", pid, servicePid);
            return;
        }
        if (this.allActivatedPids.contains(pid)) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR, null,
                    "Error create factory configuration for component " + pid);
        }
        logger.info("Registering New Factory ConfigurableComponent - {}....", pid);
        if (this.servicePidByPid.containsKey(pid)) {
            logger.error("servicePid:{} is already created,PID is:{}", servicePid, pid);
        }
        this.servicePidByPid.put(pid, servicePid);
        if (factoryPid == null) {
            logger.error("factoryPid can not be null, servicePid is:{},pid is:{}", servicePid, pid);
            return;
        }
        this.factoryPidByPid.put(pid, factoryPid);
        this.waittingForActivatedPids.add(pid);
        Tocd factoryOCD = this.ocds.get(factoryPid);

        if (factoryOCD != null) {
            try {
                updateWithDefaultConfigurationForNewFactoryInstance(pid, factoryOCD);
            } catch (KuraException | IOException e) {
                logger.info("Error seeding updated configuration for pid: {}", pid);
            }
        }
        logger.info("Registering New Factory ConfigurableComponent - {}....Done", pid);

    }

    synchronized void registerSelfConfiguringComponent(final String pid, final String servicePid) {
        if (pid == null) {
            logger.warn("PID (kura.service.pid) is null");
            return;
        }
        if (this.waittingForActivatedPids.contains(pid)) {
            this.waittingForActivatedPids.remove(pid);
        }
        logger.info("Registering SelfConfiguringComponent - {}....", pid);
        this.servicePidByPid.putIfAbsent(pid, servicePid);

        if (this.allActivatedPids.contains(pid)) {
            logger.error("pid:{} is already actived, servicePid is:{}", pid, servicePid);
        } else {
            this.allActivatedPids.add(pid);
        }
        if (this.activatedSelfConfigComponents.contains(pid)) {
            logger.error("pid:{} is already in SelfConfigComponents, servicePid is:{}", pid, servicePid);
        } else {
            this.activatedSelfConfigComponents.add(pid);
        }
        logger.info("Registering SelfConfiguringComponent - {}....Done", pid);
    }

    synchronized void unregisterComponentConfiguration(String pid) {
        if (pid == null) {
            logger.warn("pid is null");
            return;
        }
        logger.info("Removing component configuration for pid {}", pid);
        this.servicePidByPid.remove(pid);
        this.factoryPidByPid.remove(pid);
        this.activatedSelfConfigComponents.remove(pid);
        this.allActivatedPids.remove(pid);
        synchronized (this.passwordPropertiesLock) { this.passwordPropertiesByPid.remove(pid); }
    }

    boolean mergeWithDefaults(OCD ocd, Map<String, Object> properties) {
        boolean changed = false;
        Set<String> keys = properties.keySet();

        Map<String, Object> defaults = getDefaultProperties(ocd);
        Set<String> defaultsKeys = defaults.keySet();

        defaultsKeys.removeAll(keys);
        if (!defaultsKeys.isEmpty()) {

            changed = true;
            logger.info("Merging configuration for pid: {}", ocd.getId());
            for (String key : defaultsKeys) {

                Object value = defaults.get(key);
                properties.put(key, value);
                logger.debug("Merged configuration properties with property with name: {} and default value {}", key,
                        value);
            }
        }
        return changed;
    }

    Map<String, Object> getDefaultProperties(OCD ocd) {
        return ComponentUtil.getDefaultProperties(ocd, this.ctx);
    }

    void decryptConfigurationProperties(Map<String, Object> configProperties) {
        for (Entry<String, Object> property : configProperties.entrySet()) {
            Object configValue = property.getValue();

            if (configValue instanceof Password || configValue instanceof Password[]
                    || CollectionsUtil.isPasswordCollection(configValue)) {
                try {
                    Object decryptedValue = decryptPasswordProperties(configValue);
                    configProperties.put(property.getKey(), decryptedValue);
                } catch (Exception e) {
                }
            }
        }

    }

    private Object decryptPasswordProperties(Object encryptedValue) throws KuraException {
        Object decryptedValue = null;
        if (encryptedValue instanceof Password) {
            decryptedValue = decryptPassword((Password) encryptedValue);
        } else if (encryptedValue instanceof Password[]) {
            Password[] encryptedPasswords = (Password[]) encryptedValue;
            Password[] decryptedPasswords = new Password[encryptedPasswords.length];
            for (int i = 0; i < encryptedPasswords.length; i++) {
                decryptedPasswords[i] = decryptPassword(encryptedPasswords[i]);
            }
            decryptedValue = decryptedPasswords;
        } else if (CollectionsUtil.isPasswordCollection(encryptedValue)) {
            Collection<?> passwords = (Collection<?>) encryptedValue;
            Collection<Password> decryptedPasswords = CollectionsUtil.newCollectionLike(passwords);
            for (Object password : passwords) { decryptedPasswords.add(decryptPassword((Password) password)); }
            decryptedValue = decryptedPasswords;
        }
        return decryptedValue;
    }

    private Password decryptPassword(Password encryptedPassword) throws KuraException {
        return new Password(this.cryptoService.decryptAes(encryptedPassword.getPassword()));
    }

    // ----------------------------------------------------------------
    //
    // Private APIs
    //
    // ----------------------------------------------------------------

    private synchronized void updateConfigurationsInternal(List<ComponentConfiguration> configsToUpdate,
            boolean takeSnapshot) throws KuraException {
        boolean snapshotOnConfirmation = false;
        List<Throwable> causes = new ArrayList<>();

        List<ComponentConfiguration> configs = buildCurrentConfiguration(configsToUpdate);

        this.externalConfigurations.apply(configsToUpdate, ChangeSource.CONFIGURATION_UPDATE);

        for (ComponentConfiguration config : configs) {
            if (this.externalConfigurations.owns(config.getPid())) {
                continue;
            }
            for (ComponentConfiguration configToUpdate : configsToUpdate) {
                if (config.getPid().equals(configToUpdate.getPid())) {
                    try {
                        updateConfigurationInternal(config.getPid(), config.getConfigurationProperties(),
                                snapshotOnConfirmation);
                    } catch (KuraException e) {
                        logger.warn("Error during updateConfigurations for component " + config.getPid(), e);
                        causes.add(e);
                    }
                    break;
                }
            }
        }

        // this step creates any not yet existing factory configuration present in configsToUpdate
        for (ComponentConfiguration config : configsToUpdate) {
            String factoryPid = null;
            final Map<String, Object> properties = config.getConfigurationProperties();
            if (properties != null) {
                factoryPid = (String) properties.get(ConfigurationAdmin.SERVICE_FACTORYPID);
            }
            if (factoryPid != null && !this.allActivatedPids.contains(config.getPid())) {
                ConfigurationUpgrade.upgrade(config, this.bundleContext);
                String pid = config.getPid();
                logger.info("Creating configuration with pid: {} and factory pid: {}", pid, factoryPid);
                try {
                    createFactoryConfigurationInternal(factoryPid, pid, properties, false);
                    configs.add(config);
                } catch (KuraException e) {
                    logger.warn("Error creating configuration with pid: {} and factory pid: {}", pid, factoryPid, e);
                }
            }
        }

        if (takeSnapshot && configs != null && (!configs.isEmpty() || this.externalConfigurations.hasReservations())) {
            saveSnapshot(configs, configsToUpdate);
        }

        if (!causes.isEmpty()) {
            throw new KuraPartialSuccessException("updateConfigurations", causes);
        }
    }

    // returns configurations with encrypted passwords
    private List<ComponentConfiguration> getComponentConfigurationsInternal() throws KuraException {
        List<ComponentConfiguration> configs = getComponentConfigurationsInternal(this.allActivatedPids);
        configs.addAll(getComponentConfigurationsInternal(this.waittingForActivatedPids));
        return configs;
    }

    private List<ComponentConfiguration> getComponentConfigurationsInternal(Set<String> pids) throws KuraException {
        try (ProviderConfigurationReads.Budget ignored = this.providerReads.budget()) {
            List<ComponentConfiguration> configs = new ArrayList<>();

            // assemble all the configurations we have
            // clone the list to avoid concurrent modifications
            List<String> allPids = new ArrayList<>(pids);
            for (String pid : allPids) {
                try {
                    ComponentConfiguration cc = getComponentConfigurationInternal(pid);
                    if (cc != null) {
                        configs.add(cc);
                    } else {
                        logger.warn("could not find ComponentConfiguration for pid:{}", pid);
                    }
                } catch (Exception e) {
                    logger.error("Error getting configuration for component {}", pid, e);
                    throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR, e,
                            "Error getting configuration for component " + pid);
                }
            }
            return configs;
        }
    }

    // returns configurations with encrypted passwords
    private ComponentConfiguration getComponentConfigurationInternal(String pid) throws KuraException {
        if (this.externalConfigurations.owns(pid)) {
            return this.externalConfigurations.confirmed(pid);
        }
        ComponentConfiguration cc;
        if (!this.activatedSelfConfigComponents.contains(pid)) {
            cc = getConfigurableComponentConfiguration(pid);
        } else {
            cc = getSelfConfiguringComponentConfiguration(pid);
        }
        return cc;
    }

    private void updateDefaultConfiguration(String pid, String servicePid, Tocd ocd) throws IOException {
        if (this.stopping) { return; }
        try { requireOrdinaryWrite(); }
        catch (KuraException e) { return; }
        Configuration config = this.configurationAdmin.getConfiguration(servicePid, "?");
        if (config != null) {
            // get the properties from ConfigurationAdmin if any are present
            Map<String, Object> props = new HashMap<>();
            if (config.getProperties() != null) {
                props.putAll(CollectionsUtil.dictionaryToMap(config.getProperties(), ocd));
            }

            boolean changed = false;
            if (!props.containsKey(ConfigurationService.KURA_SERVICE_PID)) {
                props.put(ConfigurationService.KURA_SERVICE_PID, pid);
                changed = true;
            }

            // merge the current properties, if any, with the defaults from metatype
            changed |= mergeWithDefaults(ocd, props);
            if (changed) {
                config.updateIfDifferent(CollectionsUtil.mapToDictionary(props));
                logger.info("Seeding updated configuration for pid: {}", pid);
            }
        }
    }

    private void updateWithDefaultConfigurationForNonFactoryInstance(String pid, Tocd ocd)
            throws KuraException, IOException {
        String servicePid = this.servicePidByPid.get(pid);
        if (servicePid == null) {
            servicePid = pid;
        } else {
            if (!this.allActivatedPids.contains(pid)) {
                logger.error("non factory instance (service.pid): {} is created error before OCD registed", servicePid);
            } else {
                logger.warn("non factory instance (service.pid): {} is created before OCD registed", servicePid);
            }
        }
        updateDefaultConfiguration(pid, servicePid, ocd);
    }

    private void updateWithDefaultConfigurationForNewFactoryInstance(String pid, Tocd ocd)
            throws KuraException, IOException {
        if (pid == null) {
            logger.error("New factory instance PID (kura.service.pid) is null");
            return;
        }
        String servicePid = this.servicePidByPid.get(pid);
        if (servicePid == null) {
            logger.error("New factory instance (service.pid) is null PID is {}", pid);
            return;
        }
        updateDefaultConfiguration(pid, servicePid, ocd);
    }

    private void updateWithDefaultConfigurationForFactorInstance(String pid, Tocd ocd) throws IOException {
        String servicePid = this.servicePidByPid.get(pid);
        if (servicePid == null) {
            servicePid = pid;
        } else if (!this.factoryPidByPid.containsKey(pid)) {
            logger.error("non factory instance (service.pid): {} is created before OCD registed", servicePid);
        }
        updateDefaultConfiguration(pid, servicePid, ocd);
    }

    private void registerFactoryComponentOCD(String metatypePid, Tocd ocd, final Bundle provider) throws KuraException {
        this.factoryPids.add(new TrackedComponentFactory(metatypePid, provider));

        for (Map.Entry<String, String> entry : this.factoryPidByPid.entrySet()) {
            if (entry.getValue().equals(metatypePid) && this.servicePidByPid.get(entry.getKey()) != null) {
                try {
                    updateWithDefaultConfigurationForFactorInstance(entry.getKey(), ocd);
                } catch (IOException e) {
                    throw KuraException.internalError(e);
                }
            }
        }
    }

    private boolean allSnapshotsUnencrypted() {
        try {
            Set<Long> snapshotIDs = getSnapshots();
            if (snapshotIDs == null || snapshotIDs.isEmpty()) {
                return false;
            }
            Long[] snapshots = snapshotIDs.toArray(new Long[] {});

            for (Long snapshot : snapshots) {

                try {
                    // Verify if the current snapshot is encrypted
                    if (testEncryptedSnapshotFileContent(snapshot)) {
                        return false;
                    }
                } catch (Exception e) {
                }
            }
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    private void encryptPlainSnapshots() throws KuraException {
        Set<Long> snapshotIDs = getSnapshots();
        if (snapshotIDs == null || snapshotIDs.isEmpty()) {
            return;
        }
        Long[] snapshots = snapshotIDs.toArray(new Long[] {});

        for (Long snapshot : snapshots) {
            File fSnapshot = getSnapshotFile(snapshot);
            if (fSnapshot == null || !fSnapshot.exists()) {
                throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR, snapshot);
            }

            final XmlComponentConfigurations xmlConfigs = unmarshal(fSnapshot, XmlComponentConfigurations.class);

            if (!xmlConfigs.hasLogicalPasswords()) {
                ComponentUtil.encryptConfigs(xmlConfigs.getConfigurations(), this.cryptoService);
            }

            // Writes an encrypted snapshot with encrypted passwords.
            writeSnapshot(snapshot, xmlConfigs);
        }
    }

    private synchronized long saveSnapshot(Collection<? extends ComponentConfiguration> configs) throws KuraException {
        return saveSnapshot(configs, List.of());
    }

    private synchronized long saveSnapshot(Collection<? extends ComponentConfiguration> configs,
            Collection<? extends ComponentConfiguration> encryptedUpdates) throws KuraException {
        Map<String, Set<String>> encryptedKeys = new HashMap<>();
        for (ComponentConfiguration update : encryptedUpdates) {
            if (update != null && update.getConfigurationProperties() != null) {
                encryptedKeys.computeIfAbsent(update.getPid(), ignored -> new HashSet<>())
                        .addAll(update.getConfigurationProperties().keySet());
            }
        }
        List<ComponentConfiguration> configsToSave = new ArrayList<>();
        for (ComponentConfiguration current : this.externalConfigurations.snapshot(configs)) {
            Map<String, Object> original = current.getConfigurationProperties();
            Map<String, Object> values = original == null ? null : new HashMap<>(original);
            boolean logical = passwordValuesAreLogical(current.getPid(), current);
            if (values != null) {
                Map<String, Object> stored = new HashMap<>();
                Map<String, Object> decodedUpdates = new HashMap<>();
                for (Entry<String, Object> entry : values.entrySet()) {
                    Object value = entry.getValue();
                    boolean submitted = encryptedKeys.getOrDefault(current.getPid(), Set.of()).contains(entry.getKey());
                    if (submitted && (value instanceof Password || value instanceof Password[]
                            || CollectionsUtil.isPasswordCollection(value))) {
                        // These values were just encrypted by this operation; decoder failure is not logical text.
                        decodedUpdates.put(entry.getKey(), decryptPasswordProperties(value));
                    } else if (!logical) { stored.put(entry.getKey(), value); }
                }
                // Preserve the established legacy CM decoding fallback, once, at its known source boundary.
                decryptConfigurationProperties(stored);
                values.putAll(stored);
                values.putAll(decodedUpdates);
            }
            ComponentConfigurationImpl copy = new ComponentConfigurationImpl(current.getPid(), null, values);
            copy.setLogicalPasswords(true);
            configsToSave.add(copy);
        }
        XmlComponentConfigurations conf = new XmlComponentConfigurations();
        conf.setPasswordEncoding(XmlComponentConfigurations.LOGICAL_PASSWORD_ENCODING);
        conf.setConfigurations(configsToSave);

        // Write it to disk: marshall
        long sid = new Date().getTime();

        // Do not save the snapshot in the past
        SortedSet<Long> snapshotIDs = (SortedSet<Long>) getSnapshots();
        if (snapshotIDs != null && !snapshotIDs.isEmpty()) {
            Long lastestID = snapshotIDs.last();

            if (lastestID != null && sid <= lastestID) {
                logger.warn("Snapshot ID: {} is in the past. Adjusting ID to: {} + 1", sid, lastestID);
                sid = lastestID + 1;
            }
        }

        // Write snapshot
        writeSnapshot(sid, conf);

        this.pendingDeletePids.clear();

        // Garbage Collector for number of Snapshots Saved
        garbageCollectionOldSnapshots();
        return sid;
    }

    private void writeSnapshot(long sid, XmlComponentConfigurations conf) throws KuraException {
        File fSnapshot = getSnapshotFile(sid);
        if (fSnapshot == null) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_SNAPSHOT_NOT_FOUND);
        }

        List<ComponentConfiguration> configImpls = new ArrayList<>();
        for (ComponentConfiguration config : conf.getConfigurations()) {
            configImpls.add(new ComponentConfigurationImpl(config.getPid(), null, config.getConfigurationProperties()));
        }
        XmlComponentConfigurations xmlConfigs = new XmlComponentConfigurations();
        xmlConfigs.setConfigurations(configImpls);
        xmlConfigs.setPasswordEncoding(conf.getPasswordEncoding());
        Boolean isEncrypt = Boolean
                .valueOf(this.systemService == null || this.systemService.getProperties() == null ? "true"
                        : this.systemService.getProperties().getProperty("kura.snapshots.encrypt", "true"));
        if (isEncrypt != null && !isEncrypt) {
            try (FileOutputStream outputfile = openPrivateSnapshotOutput(fSnapshot)) {
                marshal(outputfile, xmlConfigs);
            } catch (IOException e) {
                throw KuraException.internalError(e);
            }
            return;
        }
        File tempFile;
        try {
            tempFile = File.createTempFile("snapshot_write_" + sid + "_", ".temp");
        } catch (IOException e1) {
            throw KuraException.internalError(e1);
        }
        // Encrypt the XML
        try (FileOutputStream tempOutputfile = new FileOutputStream(tempFile)) {
            marshal(tempOutputfile, xmlConfigs);
        } catch (IOException e) {
            try {
                Files.delete(tempFile.toPath());
            } catch (IOException e1) {
                logger.warn("delete temporary fiel {} failed", tempFile.getName(), e);
            }
            throw new KuraIOException(e);
        }

        try (FileInputStream temInputFile = new FileInputStream(tempFile);
                FileOutputStream outputfile = openPrivateSnapshotOutput(fSnapshot)) {
            this.cryptoService.encryptAes(temInputFile, outputfile);

        } catch (IOException e) {
            throw new KuraIOException(e);
        } finally {
            try {
                Files.delete(tempFile.toPath());
            } catch (IOException e) {
                logger.warn("delete temporary fiel {} failed", tempFile.getName(), e);
            }
        }
    }

    private static FileOutputStream openPrivateSnapshotOutput(File snapshot) throws IOException {
        Path path = snapshot.toPath();
        boolean posix = path.getFileSystem().supportedFileAttributeViews().contains("posix");
        if (!Files.exists(path)) {
            if (posix) {
                Files.createFile(path, PosixFilePermissions.asFileAttribute(
                        PosixFilePermissions.fromString("rw-------")));
            } else {
                Files.createFile(path);
            }
        }
        if (!Files.isRegularFile(path)) {
            throw new IOException("Snapshot path is not a regular file: " + path);
        }
        if (posix) {
            Files.setPosixFilePermissions(path,
                    PosixFilePermissions.fromString("rw-------"));
        }
        return new FileOutputStream(snapshot);
    }

    private ComponentConfiguration getConfigurableComponentConfiguration(String pid) {
        ComponentConfiguration cc = null;
        try {

            Tocd ocd = getOCDForPid(pid);

            String servicePid = this.servicePidByPid.get(pid);

            if (servicePid != null) {
                Configuration cfg = this.configurationAdmin.getConfiguration(servicePid, "?");
                Map<String, Object> props = CollectionsUtil.dictionaryToMap(cfg.getProperties(), ocd,
                        getPasswordPropertiesForPid(pid));
                trackPasswordProperties(pid, props);

                cc = new ComponentConfigurationImpl(pid, ocd, props);
            }
        } catch (Exception e) {
            logger.error("Error getting Configuration for component: " + pid + ". Ignoring it.", e);
        }
        return cc;
    }

    private record SelfConfigurationRead(ComponentConfiguration configuration, boolean invalid, boolean fromSelfProvider) { }

    private ComponentConfiguration getSelfConfiguringComponentConfiguration(String pid) throws KuraException {
        ComponentConfiguration current = null;
        ComponentConfiguration fallback = null;
        try {
            BundleContext bundles = this.ctx.getBundleContext();
            ServiceReference<?>[] refs = bundles.getServiceReferences((String) null, "(" + KURA_SERVICE_PID + "=" + pid + ")");
            if (refs != null) {
                for (ServiceReference<?> ref : refs) {
                    if (!pid.equals(ref.getProperty(KURA_SERVICE_PID))) { continue; }
                    try {
                        SelfConfigurationRead read = this.providerReads.read(ref,
                                () -> readSelfConfiguration(bundles, ref, pid));
                        if (read.invalid()) { return null; }
                        // Several service registrations can share the Kura PID.
                        // A ManagedService or an unavailable registration must
                        // not replace a live self-owned view with null/stored CM.
                        if (read.fromSelfProvider()) {
                            current = read.configuration();
                        } else if (read.configuration() != null) {
                            fallback = read.configuration();
                        }
                    } catch (ProviderConfigurationReads.Unavailable unavailable) {
                        throw unavailable;
                    } catch (KuraException failure) {
                        logger.error(GETTING_CONFIGURATION_ERROR, pid, failure);
                    }
                }
            }
        } catch (InvalidSyntaxException invalid) {
            logger.error(GETTING_CONFIGURATION_ERROR, pid, invalid);
        }
        return current != null ? current : fallback;
    }

    private SelfConfigurationRead readSelfConfiguration(BundleContext bundles, ServiceReference<?> reference,
            String pid) throws KuraException {
        Object service = bundles.getService(reference);
        try {
            if (service instanceof SelfConfiguringComponent provider) {
                ComponentConfiguration configuration = provider.getConfiguration();
                return new SelfConfigurationRead(configuration, !isValidSelfConfiguringComponent(pid, configuration), true);
            }
            if (service == null) {
                ComponentConfiguration fallback = getConfigurableComponentConfiguration(pid);
                if (fallback == null) { logger.error("null ref object. properties:{}", reference.getProperties()); }
                return new SelfConfigurationRead(fallback, false, false);
            }
            logger.error("Component {}, pid: {} is not a SelfConfiguringComponent. Ignoring it.", service, pid);
            return new SelfConfigurationRead(null, false, false);
        } finally {
            // A timed-out caller must not release a service still executing its callback.
            bundles.ungetService(reference);
        }
    }

    private boolean isValidSelfConfiguringComponent(String pid, ComponentConfiguration cc) {

        if (isNull(cc) || cc.getPid() == null || !cc.getPid().equals(pid)) {
            logger.error(
                    "Invalid pid for returned Configuration of SelfConfiguringComponent with pid: {}. Ignoring it.",
                    pid);
            return false;
        }

        OCD ocd = cc.getDefinition();
        if (isNull(ocd) || isNull(ocd.getAD())) {
            return false;
        }

        List<AD> ads = ocd.getAD();

        for (AD ad : ads) {
            String adId = ad.getId();
            String adType = ad.getType().value();

            if (isNull(adId) || isNull(adType)) {
                logger.error(
                        "null required type for AD id: {} for returned Configuration of SelfConfiguringComponent with pid: {}",
                        adId, pid);
                return false;
            }

            Map<String, Object> props = cc.getConfigurationProperties();
            if (!isNull(props) && !isNull(props.get(adId)) && !isMatchingADType(pid, adId, adType, props.get(adId))) {
                return false;
            }
        }
        return true;
    }

    private boolean isMatchingADType(String pid, String adId, String adType, Object value) {
        try {
            Scalar expected = Scalar.fromValue(adType);
            if (value instanceof java.util.Collection<?> collection) {
                // An empty collection has no element type; the declared AD supplies it.
                for (Object item : collection) {
                    if (!isMatchingElement(expected, item)) { return false; }
                }
                return true;
            }
            if (value.getClass().isArray()) {
                int length = java.lang.reflect.Array.getLength(value);
                if (length == 0) { return scalarForClass(value.getClass().getComponentType()) == expected; }
                for (int index = 0; index < length; index++) {
                    if (!isMatchingElement(expected, java.lang.reflect.Array.get(value, index))) { return false; }
                }
                return true;
            }
            return isMatchingElement(expected, value);
        } catch (IllegalArgumentException e) {
            // Never log property values here: Password containers can hold logical secrets.
            logger.error("Invalid class for property named: {} for SelfConfiguringComponent with pid: {}", adId, pid);
            return false;
        }
    }

    private boolean isMatchingElement(Scalar expected, Object value) {
        return value != null && !(value instanceof java.util.Collection<?>) && !value.getClass().isArray()
                && scalarForClass(value.getClass()) == expected;
    }

    private Scalar scalarForClass(Class<?> type) {
        String name = switch (type.getName()) {
            case "boolean" -> "Boolean";
            case "byte" -> "Byte";
            case "short" -> "Short";
            case "int" -> "Integer";
            case "long" -> "Long";
            case "float" -> "Float";
            case "double" -> "Double";
            case "char" -> "Character";
            default -> type.getSimpleName();
        };
        return Scalar.fromValue(name);
    }

    private TreeSet<Long> getSnapshotsInternal() {
        // keeps the list of snapshots ordered
        TreeSet<Long> ids = new TreeSet<>();
        String configDir = getSnapshotsDirectory();
        if (configDir != null) {
            try { ControlledRecovery.verifySnapshotDirectory(java.nio.file.Path.of(configDir)); }
            catch (KuraException e) { throw new IllegalStateException("Guarded snapshot directory changed", e); }
            File fConfigDir = new File(configDir);
            File[] files = fConfigDir.listFiles();
            if (files != null) {

                for (File file : files) {
                    Matcher m = SNAPSHOT_FILENAME_PATTERN.matcher(file.getName());
                    if (m.matches()) {
                        if (file.length() > 0) {
                            ids.add(Long.parseLong(m.group(1)));
                        } else {
                            if (ControlledRecovery.requested()) {
                                throw new IllegalStateException("Guarded startup retains empty snapshot evidence");
                            }
                            logger.warn("error config file length. delete it");
                            try {
                                Files.delete(file.toPath());
                            } catch (IOException e) {

                            }
                        }
                    }
                }
            }
        }
        return ids;
    }

    String getSnapshotsDirectory() {
        return this.systemService.getKuraSnapshotsDirectory();
    }

    private File getSnapshotFile(long id) {
        String configDir = getSnapshotsDirectory();

        if (configDir == null) {
            return null;
        }

        StringBuilder sbSnapshot = new StringBuilder(configDir);
        sbSnapshot.append(File.separator).append("snapshot_").append(id).append(".xml");

        String snapshot = sbSnapshot.toString();
        return new File(snapshot);
    }

    private void garbageCollectionOldSnapshots() {
        // get the current snapshots and compared with the maximum number we
        // need to keep
        TreeSet<Long> sids = getSnapshotsInternal();

        int currCount = sids.size();
        int maxCount = this.systemService.getKuraSnapshotsCount();
        while (currCount > maxCount && !sids.isEmpty()) { // stop if count reached or no more snapshots remain

            // preserve snapshot ID 0 as this will be considered the seeding
            // one.
            long sid = sids.pollFirst();
            File fSnapshot = getSnapshotFile(sid);
            if (sid == 0 || fSnapshot == null) {
                continue;
            }

            Path fSnapshotPath = fSnapshot.toPath();
            try {
                if (Files.deleteIfExists(fSnapshotPath)) {
                    logger.info("Snapshots Garbage Collector. Deleted {}", fSnapshotPath);
                    currCount--;
                }
            } catch (IOException e) {
                logger.warn("Snapshots Garbage Collector. Deletion failed for {}", fSnapshotPath, e);
            }
        }
    }

    private void loadLatestSnapshotInConfigAdmin() throws KuraException {
        //
        // save away initial configuration
        Optional<List<ComponentConfiguration>> controlled = ControlledRecovery.configurations();
        List<ComponentConfiguration> configs = controlled.isPresent() ? controlled.get() : buildCurrentConfiguration(null, false);
        if (configs == null) {
            return;
        }
        boolean guardedNormal = ControlledRecovery.evidence().map(ControlledRecovery.Evidence::normalLoad).orElse(false);
        Map<String,Map<String,Object>> normalCm = guardedNormal
                ? StartupPasswordConvergence.capture(this.configurationAdmin) : Map.of();
        List<ComponentConfiguration> storedConfigs = new ArrayList<>();
        for (ComponentConfiguration configuration : configs) {
            if (configuration instanceof ComponentConfigurationImpl impl && impl.hasLogicalPasswords()
                    && configuration.getConfigurationProperties() != null
                    && !this.externalConfigurations.owns(configuration.getPid())) {
                // Decode provenance is explicit: encrypt logical snapshot Passwords before any startup CM write.
                Map<String, Object> stored = guardedNormal
                        ? StartupPasswordConvergence.preserve(configuration.getConfigurationProperties(),
                                normalCm.get(configuration.getPid()), this.cryptoService)
                        : RollbackConvergence.prepare(configuration.getConfigurationProperties(),
                                Map.of(), Set.of(), this.cryptoService).stored();
                storedConfigs.add(new ComponentConfigurationImpl(configuration.getPid(), null, stored));
            } else { storedConfigs.add(configuration); }
        }
        configs = storedConfigs;
        final Configuration[] persistedFactoryConfigs;
        try {
            persistedFactoryConfigs = this.configurationAdmin.listConfigurations("(" + KURA_SERVICE_PID + "=*)");
        } catch (IOException | InvalidSyntaxException e) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR, e);
        }
        for (ComponentConfiguration config : configs) {
            if (config != null) {
                if (this.externalConfigurations.owns(config.getPid())) {
                    logger.info("Skipping startup snapshot replay for externally managed PID {}", config.getPid());
                    continue;
                }
                Map<String, Object> props = config.getConfigurationProperties();
                if (props != null) {
                    String factoryPid = (String) props.get(ConfigurationAdmin.SERVICE_FACTORYPID);

                    if (factoryPid != null) {
                        String pid = config.getPid();
                        Configuration persisted = null;
                        if (persistedFactoryConfigs != null) {
                            for (Configuration candidate : persistedFactoryConfigs) {
                                Dictionary<String, Object> candidateProps = candidate.getProperties();
                                if (factoryPid.equals(candidate.getFactoryPid()) && candidateProps != null
                                        && pid.equals(candidateProps.get(KURA_SERVICE_PID))) {
                                    persisted = candidate;
                                    break;
                                }
                            }
                        }
                        try {
                            if (persisted == null) {
                                logger.info("Creating configuration with pid: {} and factory pid: {}", pid, factoryPid);
                                createFactoryConfigurationInternal(factoryPid, pid, props, false);
                            } else {
                                Map<String, Object> restoredProperties = new HashMap<>(props);
                                restoredProperties.put(KURA_SERVICE_PID, pid);
                                trackPasswordProperties(pid, restoredProperties);
                                persisted.updateIfDifferent(CollectionsUtil.mapToDictionary(restoredProperties));
                                if (!this.allActivatedPids.contains(pid)) {
                                    this.servicePidByPid.put(pid, persisted.getPid());
                                    this.factoryPidByPid.put(pid, factoryPid);
                                    this.waittingForActivatedPids.add(pid);
                                }
                            }
                        } catch (KuraException | IOException e) {
                            if (ControlledRecovery.requested()) { throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR, "Controlled factory seeding failed"); }
                              logger.warn("Error creating configuration with pid: {} and factory pid: {}", pid,
                                    factoryPid, e);
                        }
                    } else {
                        try {
                            logger.debug("Pushing config to config admin: {}", config.getPid());

                            // push it to the ConfigAdmin
                            Configuration cfg = this.configurationAdmin.getConfiguration(config.getPid(), "?");

                            // set kura.service.pid if missing
                            Map<String, Object> newProperties = new HashMap<>(props);
                            if (!newProperties.containsKey(ConfigurationService.KURA_SERVICE_PID)) {
                                newProperties.put(ConfigurationService.KURA_SERVICE_PID, config.getPid());
                            }

                            trackPasswordProperties(config.getPid(), newProperties);

                            if (controlled.isPresent() || guardedNormal) { cfg.updateIfDifferent(CollectionsUtil.mapToDictionary(newProperties)); }
                              else { cfg.update(CollectionsUtil.mapToDictionary(newProperties)); }

                        } catch (IOException e) {
                            if (ControlledRecovery.requested()) { throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR, "Controlled singleton seeding failed"); }
                              logger.warn("Error seeding initial properties to ConfigAdmin for pid: {}", config.getPid(),
                                    e);
                        }
                    }
                }
            }
        }
    }

    private List<ComponentConfiguration> loadLatestSnapshotConfigurations() throws KuraException {
        Optional<List<ComponentConfiguration>> controlled = ControlledRecovery.configurations();
        if (controlled.isPresent()) { return controlled.get(); }

        //
        // Get the latest snapshot file to use as initialization
        Set<Long> snapshotIDs = getSnapshots();
        if (snapshotIDs == null || snapshotIDs.isEmpty()) {
            return Collections.emptyList();
        }

        Long[] snapshots = snapshotIDs.toArray(new Long[] {});
        Long lastestID = snapshots[snapshotIDs.size() - 1];

        //
        // Unmarshall
        logger.info("Loading init configurations from: {}...", lastestID);

        List<ComponentConfiguration> configs = null;
        try {
            XmlComponentConfigurations xmlConfigs = loadEncryptedSnapshotFileContent(lastestID);
            if (xmlConfigs != null) {
                configs = xmlConfigs.getConfigurations();
            }
        } catch (Exception e) {
            if (ControlledRecovery.requested()) {
                throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR,
                        "Guarded normal startup cannot rename, encrypt or fall back from the admitted snapshot");
            }
            Boolean isEncrypt = Boolean
                    .valueOf(this.systemService == null || this.systemService.getProperties() == null ? "true"
                            : this.systemService.getProperties().getProperty("kura.snapshots.encrypt", "true"));
            if (isEncrypt != null && !isEncrypt) {
                if (e instanceof KuraException && ((KuraException) e).getCode() == KuraErrorCode.DECODER_ERROR) {
                    logger.error("error snapshot config file, id:{}. rename to .bad", lastestID, e);
                    renameSnapshotToBad(lastestID);
                    return loadLatestSnapshotConfigurations();
                }
                throw KuraException.internalError(e);
            }

            logger.info("Unable to decrypt snapshot! Fallback to unencrypted snapshots mode.");
            try {
                if (allSnapshotsUnencrypted()) {
                    encryptPlainSnapshots();
                    configs = loadEncryptLatestSnapshotConfigurations();
                }
            } catch (Exception ex) {
                if (ex instanceof KuraException && ((KuraException) ex).getCode() == KuraErrorCode.DECODER_ERROR) {
                    logger.error("error encrypt snapshot config file, id:{}. rename to .bad", lastestID, e);
                    renameSnapshotToBad(lastestID);
                    return loadLatestSnapshotConfigurations();
                }
                throw KuraException.internalError(e);
            }
        }

        return configs;
    }

    private List<ComponentConfiguration> loadEncryptLatestSnapshotConfigurations() throws KuraException {
        //
        // Get the latest snapshot file to use as initialization
        Set<Long> snapshotIDs = getSnapshots();
        if (snapshotIDs == null || snapshotIDs.isEmpty()) {
            return Collections.emptyList();
        }

        Long[] snapshots = snapshotIDs.toArray(new Long[] {});
        Long lastestID = snapshots[snapshotIDs.size() - 1];

        //
        // Unmarshall
        logger.info("Loading init configurations from: {}...", lastestID);

        List<ComponentConfiguration> configs = null;
        XmlComponentConfigurations xmlConfigs = loadEncryptedSnapshotFileContent(lastestID);
        if (xmlConfigs != null) {
            configs = xmlConfigs.getConfigurations();
        }

        return configs;
    }

    private void renameSnapshotToBad(long snapshotID) throws KuraException {
        String configDir = getSnapshotsDirectory();

        if (configDir == null) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_SNAPSHOT_NOT_FOUND,
                    configDir != null ? configDir : "null");
        }

        StringBuilder sbSnapshot = new StringBuilder(configDir);
        sbSnapshot.append(File.separator).append("snapshot_").append(snapshotID).append(".xml");

        File snapshot = new File(sbSnapshot.toString());
        File badFile = new File(sbSnapshot.append(".bad").toString());
        try {
            Files.move(snapshot.toPath(), badFile.toPath(), StandardCopyOption.REPLACE_EXISTING);
            logger.info("Renamed bad snapshot {} -> {}", snapshot.getAbsolutePath(), badFile.getAbsolutePath());
        } catch (IOException e) {
            logger.warn("Failed to rename snapshot {}, deleting instead", snapshot.getAbsolutePath());
            try {
                Files.deleteIfExists(snapshot.toPath());
            } catch (IOException ignored) {
            }
        }
    }

    private void deleteSnapshotId(long snapshotID) throws KuraException {
        String configDir = getSnapshotsDirectory();

        if (configDir == null) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_SNAPSHOT_NOT_FOUND,
                    configDir != null ? configDir : "null");
        }

        StringBuilder sbSnapshot = new StringBuilder(configDir);
        sbSnapshot.append(File.separator).append("snapshot_").append(snapshotID).append(".xml");

        String snapshot = sbSnapshot.toString();
        try {
            Files.deleteIfExists(new File(snapshot).toPath());
        } catch (IOException e) {

        }
    }

    XmlComponentConfigurations loadEncryptedSnapshotFileContent(long snapshotID) throws KuraException {
        String configDir = getSnapshotsDirectory();

        if (configDir == null) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_SNAPSHOT_NOT_FOUND,
                    configDir != null ? configDir : "null");
        }

        StringBuilder sbSnapshot = new StringBuilder(configDir);
        sbSnapshot.append(File.separator).append("snapshot_").append(snapshotID).append(".xml");

        String snapshot = sbSnapshot.toString();
        Boolean isEncrypt = Boolean
                .valueOf(this.systemService == null || this.systemService.getProperties() == null ? "true"
                        : this.systemService.getProperties().getProperty("kura.snapshots.encrypt", "true"));
        if (isEncrypt != null && !isEncrypt) {
            XmlComponentConfigurations xmlConfigs = null;

            try (FileInputStream snapInputStream = new FileInputStream(snapshot)) {
                xmlConfigs = this.xmlUnmarshaller.unmarshal(snapInputStream, XmlComponentConfigurations.class);
            } catch (FileNotFoundException e) {
                throw new KuraException(KuraErrorCode.CONFIGURATION_SNAPSHOT_NOT_FOUND, e);
            } catch (IOException e) {
                throw KuraException.internalError(e);
            }
            return xmlConfigs;
        }
        File tempFile;
        XmlComponentConfigurations xmlConfigs = null;
        try {
            tempFile = File.createTempFile("snapshot_read_" + snapshotID + "_", ".temp");
        } catch (IOException e1) {
            throw KuraException.internalError(e1);
        }
        try (FileInputStream snapInputStream = new FileInputStream(snapshot);
                FileOutputStream tmpOutputStream = new FileOutputStream(tempFile)) {
            this.cryptoService.decryptAes(snapInputStream, tmpOutputStream);
            xmlConfigs = unmarshal(tempFile, XmlComponentConfigurations.class);
        } catch (FileNotFoundException e) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_SNAPSHOT_NOT_FOUND, e);
        } catch (IOException e) {
            throw KuraException.internalError(e);
        } finally {
            try {
                Files.delete(tempFile.toPath());
            } catch (IOException e1) {
                logger.warn("delete temporary file {} failed", tempFile.getName(), e1);
            }
        }
        return xmlConfigs;
    }

    boolean testEncryptedSnapshotFileContent(long snapshotID) throws KuraException {
        String configDir = getSnapshotsDirectory();

        if (configDir == null) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_SNAPSHOT_NOT_FOUND,
                    configDir != null ? configDir : "null");
        }

        StringBuilder sbSnapshot = new StringBuilder(configDir);
        sbSnapshot.append(File.separator).append("snapshot_").append(snapshotID).append(".xml");

        String snapshot = sbSnapshot.toString();

        File tempFile;
        try {
            tempFile = File.createTempFile("snapshot_test_" + snapshotID + "_", ".temp");
        } catch (IOException e1) {
            throw KuraException.internalError(e1);
        }
        try (FileInputStream snapInputStream = new FileInputStream(snapshot);
                FileOutputStream tmpOutputStream = new FileOutputStream(tempFile)) {
            this.cryptoService.decryptAes(snapInputStream, tmpOutputStream);
        } catch (KuraException e) {
            return false;
        } catch (IOException e) {
            throw KuraException.internalError(e);
        } finally {
            try {
                Files.delete(tempFile.toPath());
            } catch (IOException e) {
                logger.warn("delete temporary fiel {} failed", tempFile.getName(), e);
            }
        }
        return true;
    }

    private void updateConfigurationInternal(String pid, Map<String, Object> properties, boolean snapshotOnConfirmation)
            throws KuraException {
        logger.debug("Attempting update configuration for {}", pid);

        if (!this.allActivatedPids.contains(pid)) {
            logger.info("UpdatingConfiguration ignored as ConfigurableComponent {} is NOT tracked.", pid);
            return;
        }
        if (properties == null) {
            logger.info("UpdatingConfiguration ignored as properties for ConfigurableComponent {} are NULL.", pid);
            return;
        }

        // get the OCD from the registered ConfigurableComponents
        OCD registerdOCD = getRegisteredOCD(pid);
        if (registerdOCD == null) {
            logger.info("UpdatingConfiguration ignored as OCD for pid {} cannot be found.", pid);
            return;
        }

        Map<String, Object> mergedProperties = new HashMap<>();
        mergeWithDefaults(registerdOCD, mergedProperties);

        if (!this.activatedSelfConfigComponents.contains(pid)) {
            try {
                // get the current running configuration for the selected component
                Configuration config = this.configurationAdmin.getConfiguration(this.servicePidByPid.get(pid), "?");
                Map<String, Object> runningProps = CollectionsUtil.dictionaryToMap(config.getProperties(),
                        registerdOCD, getPasswordPropertiesForPid(pid));

                mergedProperties.putAll(runningProps);
            } catch (IOException e) {
                logger.info("merge with running failed!");
                throw new KuraException(KuraErrorCode.CONFIGURATION_UPDATE, e, pid);
            }
        }

        mergedProperties.putAll(properties);

        if (!mergedProperties.containsKey(ConfigurationService.KURA_SERVICE_PID)) {
            mergedProperties.put(ConfigurationService.KURA_SERVICE_PID, pid);
        }

        try {
            updateComponentConfiguration(pid, mergedProperties, snapshotOnConfirmation);
            logger.info("Updating Configuration of ConfigurableComponent {} ... Done.", pid);
        } catch (IOException e) {
            logger.warn("Error updating Configuration of ConfigurableComponent with pid {}", pid, e);
            throw new KuraException(KuraErrorCode.CONFIGURATION_UPDATE, e, pid);
        }
    }

    private void updateComponentConfiguration(String pid, Map<String, Object> mergedProperties,
            boolean snapshotOnConfirmation) throws KuraException, IOException {
        OCD registered = getOCDForPid(pid);
        if (registered instanceof ProviderDefinition provider) {
            provider.withSource(() -> {
                Map<String, Object> clear = new HashMap<>(mergedProperties);
                decryptConfigurationProperties(clear);
                provider.withValidatedProperties(clear, () -> {
                    try { writeComponentConfiguration(pid, mergedProperties, snapshotOnConfirmation); }
                    catch (IOException e) { throw KuraException.internalError(e); }
                });
            });
            return;
        }
        if (!this.activatedSelfConfigComponents.contains(pid)) {

            // load the ocd to do the validation
            BundleContext bundleCtx = this.ctx.getBundleContext();
            // FIXME: why the returned ocd is always null?
            ObjectClassDefinition ocd = ComponentUtil.getObjectClassDefinition(bundleCtx,
                    this.servicePidByPid.get(pid));

            // Validate the properties to be applied and set them
            validateProperties(pid, ocd, mergedProperties);
        } else {
            // FIXME: validation of properties for self-configuring
            // components
        }

        writeComponentConfiguration(pid, mergedProperties, snapshotOnConfirmation);
    }

    private void writeComponentConfiguration(String pid, Map<String, Object> mergedProperties,
            boolean snapshotOnConfirmation) throws KuraException, IOException {
        // Update the new properties
        // use ConfigurationAdmin to do the update
        trackPasswordProperties(pid, mergedProperties);

        Configuration config = this.configurationAdmin.getConfiguration(this.servicePidByPid.get(pid), "?");
        config.update(CollectionsUtil.mapToDictionary(mergedProperties));

        if (snapshotOnConfirmation) {
            snapshot();
        }
    }

    private OCD getRegisteredOCD(String pid) throws KuraException {
        // try to get the OCD from the registered ConfigurableComponents
        OCD registeredOCD = getOCDForPid(pid);
        // otherwise try to get it from the registered SelfConfiguringComponents
        if (registeredOCD == null) {
            ComponentConfiguration config = getSelfConfiguringComponentConfiguration(pid);
            if (config != null) {
                registeredOCD = config.getDefinition();
            }
        }
        return registeredOCD;
    }

    private void validateProperties(String pid, ObjectClassDefinition ocd, Map<String, Object> updatedProps)
            throws KuraException {
        if (ocd == null) {
            return;
        }

        // build a map of all the attribute definitions
        List<AttributeDefinition> definitions = Arrays.asList(ocd.getAttributeDefinitions(ObjectClassDefinition.ALL));
        Map<String, AttributeDefinition> attributeDefinitions = definitions.stream()
                .collect(Collectors.toMap(AttributeDefinition::getID, Function.identity()));

        // loop over the proposed property values
        // and validate them against the definition
        for (Entry<String, Object> property : updatedProps.entrySet()) {

            String key = property.getKey();
            AttributeDefinition attributeDefinition = attributeDefinitions.get(key);

            if (attributeDefinition == null) {
                // For the attribute for which we do not have a definition, just accept them.
                continue;
            }

            validateAttribute(property, attributeDefinition);
        }

        // make sure all required properties are set
        OCD ocdFull = getOCDForPid(pid);
        if (ocdFull != null) {
            for (AD attrDef : ocdFull.getAD()) {
                // to the required attributes make sure a value is defined.
                if (attrDef.isRequired()) {
                    if (updatedProps.get(attrDef.getId()) == null) {
                        // if the default one is not defined, throw
                        // exception.
                        throw new KuraException(KuraErrorCode.CONFIGURATION_REQUIRED_ATTRIBUTE_MISSING,
                                attrDef.getId());
                    }
                }
            }
        }

    }

    private void validateAttribute(Entry<String, Object> property, AttributeDefinition attributeDefinition)
            throws KuraException {
        // validate the attribute value
        Object objectValue = property.getValue();
        String stringValue = StringUtil.valueToString(objectValue);
        if (attributeDefinition.getType() != AttributeDefinition.STRING && stringValue != null) {
            boolean required = true;
            if ("".equals(stringValue)) {
                try {
                    Method requiredMethod = attributeDefinition.getClass().getDeclaredMethod("isRequired");
                    requiredMethod.setAccessible(true);
                    required = (boolean) requiredMethod.invoke(attributeDefinition);
                } catch (Exception e) {
                }
            }
            if (!"".equals(stringValue) || required) {
                String result = attributeDefinition.validate(stringValue);
                if (result != null && !result.isEmpty()) {
                    throw new KuraException(KuraErrorCode.CONFIGURATION_ATTRIBUTE_INVALID, attributeDefinition.getID(),
                            stringValue, result);
                }
            }
        }
    }

    private synchronized List<ComponentConfiguration> buildCurrentConfiguration(
            List<ComponentConfiguration> configsToUpdate) throws KuraException {
        return buildCurrentConfiguration(configsToUpdate, true);
    }

    private synchronized List<ComponentConfiguration> buildCurrentConfiguration(
            List<ComponentConfiguration> configsToUpdate, boolean includeExternal) throws KuraException {
        List<ComponentConfiguration> result = new ArrayList<>();

        // Merge the current configuration of registered components with the provided configurations.
        // It is assumed that the PIDs in the provided configurations is a subset of the registered PIDs.
        List<ComponentConfiguration> currentConfigs;
        if (includeExternal || !this.externalConfigurations.hasReservations()) {
            currentConfigs = getComponentConfigurationsInternal();
        } else {
            // Bootstrap cannot depend on an external owner whose transport may
            // itself require ConfigurationService. Never read/replay these PIDs.
            Set<String> localPids = new HashSet<>(this.allActivatedPids);
            localPids.addAll(this.waittingForActivatedPids);
            localPids.removeIf(this.externalConfigurations::owns);
            currentConfigs = getComponentConfigurationsInternal(localPids);
        }
        if (currentConfigs != null) {
            for (ComponentConfiguration currentConfig : currentConfigs) {
                // either add this configuration or a new one obtained by merging its properties with the ones provided
                ComponentConfiguration cc = currentConfig;
                String pid = currentConfig.getPid();
                if (configsToUpdate != null) {
                    for (ComponentConfiguration configToUpdate : configsToUpdate) {
                        if (configToUpdate.getPid().equals(pid)) {
                            Map<String, Object> props = new HashMap<>();
                            if (currentConfig.getConfigurationProperties() != null) {
                                props.putAll(currentConfig.getConfigurationProperties());
                            }
                            if (configToUpdate.getConfigurationProperties() != null) {
                                props.putAll(configToUpdate.getConfigurationProperties());
                            }
                            cc = new ComponentConfigurationImpl(pid, (Tocd) configToUpdate.getDefinition(), props);
                            if (currentConfig instanceof ComponentConfigurationImpl impl && impl.hasPasswordRepresentation()) {
                                ((ComponentConfigurationImpl) cc).setLogicalPasswords(impl.hasLogicalPasswords());
                            }
                            break;
                        }
                    }
                }
                result.add(cc);
            }
        }

        // complete the returned configurations adding the snapshot configurations
        // of those components not yet in the list.
        List<ComponentConfiguration> snapshotConfigs = loadLatestSnapshotConfigurations();
        if (snapshotConfigs != null) {
            for (ComponentConfiguration snapshotConfig : snapshotConfigs) {
                if (!includeExternal && this.externalConfigurations.owns(snapshotConfig.getPid())) {
                    continue;
                }
                boolean found = false;
                for (ComponentConfiguration config : result) {
                    if (config.getPid().equals(snapshotConfig.getPid())) {
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    // Add old configurations (or not yet tracked ones) present
                    result.add(snapshotConfig);
                }
            }
        }

        // remove configurations being deleted
        for (String deletedPid : this.pendingDeletePids) {
            for (ComponentConfiguration config : result) {
                if (config.getPid().equals(deletedPid)) {
                    result.remove(config);
                    break;
                }
            }
        }

        for (final ComponentConfiguration config : result) {
            ConfigurationUpgrade.upgrade(config, this.bundleContext);
        }

        return result;

    }

    private Tocd getOCDForPid(String pid) {
        Tocd ocd = this.ocds.get(this.factoryPidByPid.get(pid));
        if (ocd == null) {
            ocd = this.ocds.get(pid);
        }
        return ocd;
    }

    /**
     * Convert property value to string
     *
     * @param value
     *                  the input value
     * @return the string property value, or {@code null}
     */
    private static String makeString(Object value) {
        return singleValue(distinctValues(value));
    }

    private String getServicePid(final ServiceReference<?> reference) {
        final Set<String> servicePids = distinctValues(reference.getProperty(Constants.SERVICE_PID));
        if (servicePids.size() > 1) {
            servicePids.remove(makeString(reference.getProperty(ConfigurationAdmin.SERVICE_FACTORYPID)));
        }
        if (servicePids.size() > 1) {
            final Set<String> configurationPids = getConfigurationPids();
            configurationPids.retainAll(servicePids);
            if (configurationPids.size() == 1) {
                return configurationPids.iterator().next();
            }
        }
        return singleValue(servicePids);
    }

    private Set<String> getConfigurationPids() {
        final Set<String> configurationPids = new HashSet<>();
        if (this.configurationAdmin == null) {
            return configurationPids;
        }
        try {
            final Configuration[] configurations = this.configurationAdmin.listConfigurations(null);
            if (configurations != null) {
                Arrays.stream(configurations).map(Configuration::getPid).forEach(configurationPids::add);
            }
        } catch (final IOException | InvalidSyntaxException e) {
            logger.warn("Failed to list the configurations", e);
        }
        return configurationPids;
    }

    private static Set<String> distinctValues(Object value) {
        final Set<String> values = new java.util.LinkedHashSet<>();
        if (value instanceof Collection) {
            ((Collection<?>) value).stream().filter(Objects::nonNull).map(Object::toString).forEach(values::add);
        } else if (value != null && value.getClass().isArray()) {
            for (int i = 0; i < java.lang.reflect.Array.getLength(value); i++) {
                final Object element = java.lang.reflect.Array.get(value, i);
                if (element != null) {
                    values.add(element.toString());
                }
            }
        } else if (value != null) {
            values.add(value.toString());
        }
        return values;
    }

    private static String singleValue(Set<String> values) {
        if (values.size() == 1) {
            return values.iterator().next();
        }
        if (!values.isEmpty()) {
            logger.warn("Expected a single property value, found {}. Ignoring it.", values);
        }
        return null;
    }

    @Override
    public List<ComponentConfiguration> getFactoryComponentOCDs() {
        return this.factoryPids.stream().map(factory -> {
            final String factoryPid = factory.getFactoryPid();
            return new ComponentConfigurationImpl(factoryPid, this.ocds.get(factoryPid), new HashMap<>());
        }).collect(Collectors.toList());
    }

    private ComponentConfiguration getComponentDefinition(String pid) {
        final Tocd ocd = this.ocds.get(pid);
        Map<String, Object> defaultProperties = new HashMap<>();
        if (ocd != null) {
            try {
                defaultProperties = ComponentUtil.getDefaultProperties(ocd, this.ctx);
            } catch (Exception e) {
                logger.warn("Failed to get default properties for component: {}", pid, e);
            }
        }
        return new ComponentConfigurationImpl(pid, ocd, defaultProperties);
    }

    @Override
    public ComponentConfiguration getFactoryComponentOCD(String factoryPid) {
        if (!this.factoryPids.contains(new TrackedComponentFactory(factoryPid, null))) {
            return null;
        }
        return getComponentDefinition(factoryPid);
    }

    private static boolean implementsAnyService(ComponentDescriptionDTO component, String[] classes) {
        final String[] services = component.serviceInterfaces;
        if (services == null) {
            return false;
        }
        for (String className : classes) {
            for (String s : services) {
                if (s.equals(className)) {
                    return true;
                }
            }
        }
        return false;
    }

    @Override
    public List<ComponentConfiguration> getServiceProviderOCDs(String... classNames) {
        return this.scrService.getComponentDescriptionDTOs().stream()
                .filter(component -> implementsAnyService(component, classNames)).map(c -> c.name)
                .map(this::getComponentDefinition).filter(Objects::nonNull).collect(Collectors.toList());
    }

    @Override
    public List<ComponentConfiguration> getServiceProviderOCDs(Class<?>... classes) {
        final String[] classNames = new String[classes.length];
        for (int i = 0; i < classes.length; i++) {
            classNames[i] = classes[i].getName();
        }
        return getServiceProviderOCDs(classNames);
    }
    
    private void trackPasswordProperties(String pid, Map<String, Object> properties) {
        Set<String> names = CollectionsUtil.passwordPropertyNames(properties);
        synchronized (this.passwordPropertiesLock) {
            if (names.isEmpty()) {
                this.passwordPropertiesByPid.remove(pid);
            } else {
                this.passwordPropertiesByPid.put(pid, names);
            }
        }
    }

    private Set<String> getPasswordPropertiesForPid(String pid) {
        synchronized (this.passwordPropertiesLock) {
            Set<String> names = this.passwordPropertiesByPid.get(pid);
            return names == null ? Collections.emptySet() : new HashSet<>(names);
        }
    }

    protected <T> T unmarshal(final InputStream input, final Class<T> clazz) throws KuraException {
        try {
            return requireNonNull(this.xmlUnmarshaller.unmarshal(input, clazz));
        } catch (final Exception e) {
            throw new KuraException(KuraErrorCode.DECODER_ERROR, "configuration", e);
        }
    }

    protected <T> T unmarshal(final File file, final Class<T> clazz) throws KuraException {
        if (file == null) {
            throw KuraException.internalError("file is null");
        }
        if (this.xmlUnmarshaller == null) {
            throw KuraException.internalError("xmlUnmarshaller is null");
        }
        // The stream has to be closed also on unmarshal failures - a leaked descriptor
        // pins the file on Windows and exhausts handles on long-running gateways (#6393).
        try (InputStream in = new FileInputStream(file)) {
            return requireNonNull(this.xmlUnmarshaller.unmarshal(in, clazz));
        } catch (final Exception e) {
            throw new KuraException(KuraErrorCode.DECODER_ERROR, e);
        }
    }

    private void manageSnapshotConfigs(List<Throwable> causes, final Map<String, Configuration> currentConfigs,
            final ComponentConfiguration snapshotConfig) {
        if (this.externalConfigurations.owns(snapshotConfig.getPid())) {
            return;
        }
        final Optional<Configuration> optionalCurrentConfig = Optional
                .ofNullable(currentConfigs.get(snapshotConfig.getPid()));

        try {
            logger.info("Processing configuration rollback for component with pid {}...", snapshotConfig.getPid());
            rollbackPreparedConfiguration(snapshotConfig, optionalCurrentConfig);
        } catch (IOException | KuraException e) {
            logger.warn("Failed to rollback configuration for pid {}", snapshotConfig.getPid(), e);
            causes.add(e);
        }
    }

    private void manageCurrentConfigs(List<Throwable> causes,
            Map<String, ComponentConfiguration> defaults, Set<String> deletions,
            Iterator<Entry<String, Configuration>> currentConfigsIterator) {
        Entry<String, Configuration> entry = currentConfigsIterator.next();
        try {
            ComponentConfiguration reset = defaults.get(entry.getKey());
            if (reset != null) { rollbackToDefaultConfig(entry, reset); }
            else if (deletions.contains(entry.getKey())) { deleteFactoryComponent(currentConfigsIterator, entry); }
        } catch (IOException | KuraException e) {
            logger.warn("Failed to rollback current configuration {}", entry.getKey(), e); causes.add(e);
        }
    }

    protected void marshal(OutputStream outputBuffer, Object object) throws KuraException {
        try {
            this.xmlMarshaller.marshal(outputBuffer, object);
        } catch (Exception e) {
            throw new KuraException(KuraErrorCode.ENCODE_ERROR, e);
        }
    }

    private void rollbackConfigurationInternal(final ComponentConfiguration snapshotConfig,
            final Optional<Configuration> existingConfig) throws IOException, KuraException {
        rollbackPreparedConfiguration(prepareRollbackConfiguration(snapshotConfig, existingConfig, new LinkedHashMap<>(), new HashMap<>()),
                existingConfig);
    }

    private void rollbackPreparedConfiguration(final ComponentConfiguration snapshotConfig,
            final Optional<Configuration> existingConfig) throws IOException, KuraException {
        final Optional<String> factoryPid = Optional
                .ofNullable(snapshotConfig.getConfigurationProperties().get(ConfigurationAdmin.SERVICE_FACTORYPID))
                .filter(String.class::isInstance).map(String.class::cast);

        final Map<String, Object> result = snapshotConfig.getConfigurationProperties();

        trackPasswordProperties(snapshotConfig.getPid(), result);

        final Dictionary<String, Object> resultAsDictionary = CollectionsUtil.mapToDictionary(result);

        resultAsDictionary.put(KURA_SERVICE_PID, snapshotConfig.getPid());
        resultAsDictionary.remove(Constants.SERVICE_PID);

        final Configuration target;

        if (existingConfig.isPresent()) {
            target = existingConfig.get();
        } else if (factoryPid.isPresent()) {
            logger.info("Creating new factory configuration for pid {} and factory pid {}", snapshotConfig.getPid(),
                    factoryPid.get());
            target = this.configurationAdmin.createFactoryConfiguration(factoryPid.get(), null);
        } else {
            logger.info("Creating new configuration for pid {}", snapshotConfig.getPid());
            target = this.configurationAdmin.getConfiguration(snapshotConfig.getPid());
        }

        final Dictionary<String, Object> currentProperties = target.getProperties();

        if (currentProperties != null) {
            currentProperties.remove(Constants.SERVICE_PID);
        }

        if (!CollectionsUtil.equals(resultAsDictionary, currentProperties)) {
            logger.info("Updating configuration for pid {}", snapshotConfig.getPid());
            if (factoryPid.isPresent() && !this.allActivatedPids.contains(snapshotConfig.getPid())) {
                // Creating/updating a CM configuration is not a service registration. Track it until SCR binds it.
                this.servicePidByPid.put(snapshotConfig.getPid(), target.getPid());
                this.factoryPidByPid.put(snapshotConfig.getPid(), factoryPid.get());
                this.waittingForActivatedPids.add(snapshotConfig.getPid());
            }
            target.update(resultAsDictionary);
        } else {
            logger.info("No need to update configuration for pid {}", snapshotConfig.getPid());
        }
    }

    private void deleteFactoryComponent(Iterator<Entry<String, Configuration>> currentConfigsIterator,
            final Entry<String, Configuration> currentConfigEntry) throws IOException {
        logger.info("Deleting factory configuration for component with pid {}...", currentConfigEntry.getKey());
        currentConfigEntry.getValue().delete();
        currentConfigsIterator.remove();
        unregisterComponentConfiguration(currentConfigEntry.getKey());
    }

    private void rollbackToDefaultConfig(Entry<String, Configuration> entry,
            ComponentConfiguration prepared) throws IOException, KuraException {
        logger.info("Rolling back to default configuration for component pid: '{}'", entry.getKey());
        rollbackPreparedConfiguration(prepared, Optional.of(entry.getValue()));
    }

    private boolean isFactoryComponent(final Entry<String, Configuration> currentConfigEntry) {
        return currentConfigEntry.getValue().getFactoryPid() != null;
    }

    private Map<String, Configuration> getCurrentConfigs() throws KuraException {

        Map<String, Configuration> currentConfigs = new HashMap<>();

        try {
            Configuration[] currentKuraServiceConfigs = this.configurationAdmin
                    .listConfigurations("(" + KURA_SERVICE_PID + "=*)");

            if (currentKuraServiceConfigs != null) {
                currentConfigs = Arrays.stream(currentKuraServiceConfigs).filter(this::isKuraServicePidString)
                        .collect(Collectors.toMap(this::getKuraServicePid, Function.identity()));
            }

        } catch (final IOException | InvalidSyntaxException e) {
            throw new KuraException(KuraErrorCode.IO_ERROR, e);
        }
        return currentConfigs;
    }

    private boolean isKuraServicePidString(Configuration config) {
        return config.getProperties().get(KURA_SERVICE_PID) instanceof String;
    }

    private String getKuraServicePid(Configuration config) {
        return (String) config.getProperties().get(KURA_SERVICE_PID);
    }

    private Map<String, ComponentConfiguration> getSnapshotConfigs(long id) throws KuraException {
        XmlComponentConfigurations xmlConfigs = loadEncryptedSnapshotFileContent(id);
        List<ComponentConfiguration> configs = xmlConfigs.getConfigurations();

        return ComponentUtil.toMap(configs);
    }

    private static final class TrackedComponentFactory {

        private final String factoryPid;
        private final Bundle provider;

        public TrackedComponentFactory(final String factoryPid, final Bundle provider) {
            this.factoryPid = factoryPid;
            this.provider = provider;
        }

        public String getFactoryPid() {
            return this.factoryPid;
        }

        public Bundle getProviderBundle() {
            return this.provider;
        }

        @Override
        public int hashCode() {
            final int prime = 31;
            int result = 1;
            result = prime * result + (this.factoryPid == null ? 0 : this.factoryPid.hashCode());
            return result;
        }

        @Override
        public boolean equals(Object obj) {
            if (this == obj) {
                return true;
            }
            if (obj == null || getClass() != obj.getClass()) {
                return false;
            }
            TrackedComponentFactory other = (TrackedComponentFactory) obj;
            if (this.factoryPid == null) {
                if (other.factoryPid != null) {
                    return false;
                }
            } else if (!this.factoryPid.equals(other.factoryPid)) {
                return false;
            }
            return true;
        }
    }

    class ByteBufferInputStream extends InputStream {

        private ByteBuffer byteBuffer;

        public ByteBufferInputStream() {
        }

        public ByteBufferInputStream(int bufferSize) {
            this(ByteBuffer.allocate(bufferSize));
            this.byteBuffer.flip();
        }

        public ByteBufferInputStream(ByteBuffer byteBuffer) {
            this.byteBuffer = byteBuffer;
        }

        public ByteBuffer getByteBuffer() {
            return this.byteBuffer;
        }

        public void setByteBuffer(ByteBuffer byteBuffer) {
            this.byteBuffer = byteBuffer;
        }

        @Override
        public int read() throws IOException {
            if (!this.byteBuffer.hasRemaining()) {
                return -1;
            }
            return this.byteBuffer.get() & 0xFF;
        }

        @Override
        public int read(byte[] bytes, int offset, int length) throws IOException {
            if (length == 0) {
                return 0;
            }
            int count = Math.min(this.byteBuffer.remaining(), length);
            if (count == 0) {
                return -1;
            }
            this.byteBuffer.get(bytes, offset, count);
            return count;
        }

        @Override
        public int available() throws IOException {
            return this.byteBuffer.remaining();
        }
    }
}
