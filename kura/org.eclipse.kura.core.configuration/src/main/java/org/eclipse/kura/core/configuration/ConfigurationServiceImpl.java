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
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.Collections;
import java.util.Date;
import java.util.Dictionary;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
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
import org.eclipse.kura.configuration.ConfigurationService;
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
public class ConfigurationServiceImpl implements ConfigurationService, OCDService {

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

    // contains the service.factoryPid of all Factory Components
    private final Set<TrackedComponentFactory> factoryPids;

    // maps the kura.service.pid to the associated service.factoryPid
    private final Map<String, String> factoryPidByPid;

    // contains all the pids (kura.service.pid) which have to be deleted
    private final Set<String> pendingDeletePids;

    // maps the kura.service.pid to the associated service.pid
    private final Map<String, String> servicePidByPid;

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

    public ConfigurationServiceImpl() {
        this.allActivatedPids = new HashSet<>();
        this.waittingForActivatedPids = new HashSet<>();
        this.activatedSelfConfigComponents = new HashSet<>();
        this.pendingDeletePids = new HashSet<>();
        this.ocds = new HashMap<>();
        this.factoryPids = new HashSet<>();
        this.factoryPidByPid = new HashMap<>();
        this.servicePidByPid = new HashMap<>();
    }

    // ----------------------------------------------------------------
    //
    // Activation APIs
    //
    // ----------------------------------------------------------------

    protected void activate(ComponentContext componentContext) throws InvalidSyntaxException {
        logger.info("activate...");

        // save the bundle context
        this.ctx = componentContext;
        this.bundleContext = componentContext.getBundleContext();

        // Load the latest snapshot and push it to ConfigurationAdmin
        try {
            loadLatestSnapshotInConfigAdmin();
        } catch (Exception e) {
            throw new ComponentException("Error loading latest snapshot", e);
        }

        this.bundleTracker = new ComponentMetaTypeBundleTracker(this.ctx.getBundleContext(), this);
        this.bundleTracker.open();
    }

    protected void addConfigurableComponent(final ServiceReference<ConfigurableComponent> reference) {

        Object serviceIds = reference.getProperty(Constants.SERVICE_PID);
        String servicePid = makeString(serviceIds);
        if (serviceIds instanceof List) {
            @SuppressWarnings("unchecked")
            List<String> servicePids = (List<String>) serviceIds;
            if (!servicePids.isEmpty()) {
                logger.error("addConfigurableComponent have multiple servicePids:{}", servicePids);
                servicePid = servicePids.get(servicePids.size() - 1);
            } else {
                logger.error("addConfigurableComponent get null servicePids list");
            }
        }

        if (servicePid == null) {
            logger.error("addConfigurableComponent pid is null. properties:{}", reference.getProperties());
            return;
        }

        final String kuraPid = makeString(reference.getProperty(ConfigurationService.KURA_SERVICE_PID));
        final String factoryPid = makeString(reference.getProperty(ConfigurationAdmin.SERVICE_FACTORYPID));

        registerComponentConfiguration(kuraPid, servicePid, factoryPid);
    }

    protected void removeConfigurableComponent(final ServiceReference<ConfigurableComponent> reference) {

        Object serviceIds = reference.getProperty(Constants.SERVICE_PID);
        String servicePid = makeString(serviceIds);
        if (serviceIds instanceof List) {
            @SuppressWarnings("unchecked")
            List<String> servicePids = (List<String>) serviceIds;
            if (!servicePids.isEmpty()) {
                logger.error("removeConfigurableComponent have multiple servicePids:{}", servicePids);
                servicePid = servicePids.get(servicePids.size() - 1);
            } else {
                logger.error("removeConfigurableComponent get null servicePids list");
            }
        }

        if (servicePid == null) {
            logger.error("removeConfigurableComponent pid is null. properties:{}", reference.getProperties());
            return;
        }

        final String kuraPid = makeString(reference.getProperty(ConfigurationService.KURA_SERVICE_PID));

        unregisterComponentConfiguration(kuraPid);
    }

    protected void addSelfConfiguringComponent(final ServiceReference<SelfConfiguringComponent> reference) {

        Object serviceIds = reference.getProperty(Constants.SERVICE_PID);
        String servicePid = makeString(serviceIds);
        if (serviceIds instanceof List) {
            @SuppressWarnings("unchecked")
            List<String> servicePids = (List<String>) serviceIds;
            if (!servicePids.isEmpty()) {
                logger.error("addSelfConfiguringComponent have multiple servicePids:{}", servicePids);
                servicePid = servicePids.get(servicePids.size() - 1);
            } else {
                logger.error("addSelfConfiguringComponent get null servicePids list");
            }
        }

        if (servicePid == null) {
            logger.error("addSelfConfiguringComponent pid is null. properties:{}", reference.getProperties());
            return;
        }

        final String kuraPid = makeString(reference.getProperty(ConfigurationService.KURA_SERVICE_PID));

        registerSelfConfiguringComponent(kuraPid, servicePid);
    }

    protected void removeSelfConfiguringComponent(final ServiceReference<SelfConfiguringComponent> reference) {

        Object serviceIds = reference.getProperty(Constants.SERVICE_PID);
        String servicePid = makeString(serviceIds);
        if (serviceIds instanceof List) {
            @SuppressWarnings("unchecked")
            List<String> servicePids = (List<String>) serviceIds;
            if (!servicePids.isEmpty()) {
                logger.error("removeSelfConfiguringComponent have multiple servicePids:{}", servicePids);
                servicePid = servicePids.get(servicePids.size() - 1);
            } else {
                logger.error("removeSelfConfiguringComponent get null servicePids list");
            }
        }

        if (servicePid == null) {
            logger.error("removeSelfConfiguringComponent pid is null. properties:{}", reference.getProperties());
            return;
        }

        final String kuraPid = makeString(reference.getProperty(ConfigurationService.KURA_SERVICE_PID));

        unregisterComponentConfiguration(kuraPid);

    }

    protected void deactivate() {
        logger.info("deactivate...");

        if (this.bundleTracker != null) {
            this.bundleTracker.close();
            this.bundleTracker = null;
        }
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

        if (filter == null) {
            return getComponentConfigurationsInternal();
        }

        try {
            final ServiceReference<?>[] refs = this.bundleContext.getAllServiceReferences(null, null);
            if (refs == null) {
                return Collections.emptyList();
            }
            final List<ComponentConfiguration> result = new ArrayList<>(refs.length);

            for (final ServiceReference<?> ref : refs) {

                if (!filter.match(ref)) {
                    continue;
                }

                final Object kuraServicePid = ref.getProperty(KURA_SERVICE_PID);

                if (kuraServicePid instanceof String) {
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

    // Don't perform internal calls to this method
    @Override
    public ComponentConfiguration getComponentConfiguration(String pid) throws KuraException {
        ComponentConfiguration tempConfig = getComponentConfigurationInternal(pid);
        if (tempConfig != null && tempConfig.getConfigurationProperties() != null) {
            decryptConfigurationProperties(tempConfig.getConfigurationProperties());
        }
        return tempConfig;
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
            throws KuraException { // don't call this method internally
        for (ComponentConfiguration config : configsToUpdate) {
            if (config != null) {
                ComponentUtil.encryptConfigurationProperties(config.getConfigurationProperties(), this.cryptoService);
            }
        }

        // only encrypted properties are passed to internal methods
        updateConfigurationsInternal(configsToUpdate, takeSnapshot);
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
        Map<String, Object> props = ComponentUtil.getDefaultProperties(ocd, this.ctx);
        return new ComponentConfigurationImpl(pid, ocd, props);
    }

    @Override
    public synchronized void createFactoryConfiguration(String factoryPid, String pid, Map<String, Object> properties,
            boolean takeSnapshot) throws KuraException {
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
    public long snapshot() throws KuraException {
        logger.info("Writing snapshot - Getting component configurations...");

        List<ComponentConfiguration> configs = buildCurrentConfiguration(null);

        return saveSnapshot(configs);
    }

    @Override
    public long rollback() throws KuraException {
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
        logger.info("Rolling back to snapshot {}...", id);

        List<Throwable> causes = new ArrayList<>();
        final Map<String, ComponentConfiguration> snapshotConfigs = getSnapshotConfigs(id);
        final Map<String, Configuration> currentConfigs = getCurrentConfigs();
        Iterator<Entry<String, Configuration>> currentConfigsIterator = currentConfigs.entrySet().iterator();

        while (currentConfigsIterator.hasNext()) {
            manageCurrentConfigs(causes, snapshotConfigs, currentConfigsIterator);
        }

        for (final ComponentConfiguration snapshotConfig : snapshotConfigs.values()) {
            manageSnapshotConfigs(causes, currentConfigs, snapshotConfig);
        }

        this.pendingDeletePids.clear();

        if (!causes.isEmpty()) {
            throw new KuraPartialSuccessException("Rollback", causes);
        }

        final SortedSet<Long> snapshotIds = getSnapshotsInternal();

        if (snapshotIds.isEmpty() || id != snapshotIds.last()) {
            saveSnapshot(snapshotConfigs.values());
        }
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
            for (ComponentConfiguration config : configs) {
                if (config != null) {
                    try {
                        decryptConfigurationProperties(config.getConfigurationProperties());
                    } catch (Throwable t) {
                        logger.warn("Error during snapshot password decryption");
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

        this.ocds.put(metatypePid, ocd);

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
        this.factoryPids.removeIf(factory -> {
            final Bundle provider = factory.getProviderBundle();
            return provider.getSymbolicName().equals(bundle.getSymbolicName())
                    && provider.getVersion().equals(bundle.getVersion());
        });
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

            if (configValue instanceof Password || configValue instanceof Password[]) {
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

        for (ComponentConfiguration config : configs) {
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
                    createFactoryConfiguration(factoryPid, pid, properties, false);
                    configs.add(config);
                } catch (KuraException e) {
                    logger.warn("Error creating configuration with pid: {} and factory pid: {}", pid, factoryPid, e);
                }
            }
        }

        if (takeSnapshot && configs != null && !configs.isEmpty()) {
            saveSnapshot(configs);
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

    // returns configurations with encrypted passwords
    private ComponentConfiguration getComponentConfigurationInternal(String pid) {
        ComponentConfiguration cc;
        if (!this.activatedSelfConfigComponents.contains(pid)) {
            cc = getConfigurableComponentConfiguration(pid);
        } else {
            cc = getSelfConfiguringComponentConfiguration(pid);
        }
        return cc;
    }

    private void updateDefaultConfiguration(String pid, String servicePid, Tocd ocd) throws IOException {

        Configuration config = this.configurationAdmin.getConfiguration(servicePid, "?");
        if (config != null) {
            // get the properties from ConfigurationAdmin if any are present
            Map<String, Object> props = new HashMap<>();
            if (config.getProperties() != null) {
                props.putAll(CollectionsUtil.dictionaryToMap(config.getProperties(), ocd));
            }

            if (!props.containsKey(ConfigurationService.KURA_SERVICE_PID)) {
                props.put(ConfigurationService.KURA_SERVICE_PID, pid);
            }

            // merge the current properties, if any, with the defaults from metatype
            mergeWithDefaults(ocd, props);

            config.update(CollectionsUtil.mapToDictionary(props));
            logger.info("Seeding updated configuration for pid: {}", pid);
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

            ComponentUtil.encryptConfigs(xmlConfigs.getConfigurations(), this.cryptoService);

            // Writes an encrypted snapshot with encrypted passwords.
            writeSnapshot(snapshot, xmlConfigs);
        }
    }

    private synchronized long saveSnapshot(Collection<? extends ComponentConfiguration> configs) throws KuraException {

        List<ComponentConfiguration> configsToSave = configs.stream()
                .map(cc -> new ComponentConfigurationImpl(cc.getPid(), null, cc.getConfigurationProperties()))
                .collect(Collectors.toList());

        // Build the XML structure
        XmlComponentConfigurations conf = new XmlComponentConfigurations();
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
        Boolean isEncrypt = Boolean
                .valueOf(this.systemService == null || this.systemService.getProperties() == null ? "true"
                        : this.systemService.getProperties().getProperty("kura.snapshots.encrypt", "true"));
        if (isEncrypt != null && !isEncrypt) {
            try (FileOutputStream outputfile = new FileOutputStream(fSnapshot)) {
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
                FileOutputStream outputfile = new FileOutputStream(fSnapshot)) {
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

    private ComponentConfiguration getConfigurableComponentConfiguration(String pid) {
        ComponentConfiguration cc = null;
        try {

            Tocd ocd = getOCDForPid(pid);

            String servicePid = this.servicePidByPid.get(pid);

            if (servicePid != null) {
                Configuration cfg = this.configurationAdmin.getConfiguration(servicePid, "?");
                Map<String, Object> props = CollectionsUtil.dictionaryToMap(cfg.getProperties(), ocd);

                cc = new ComponentConfigurationImpl(pid, ocd, props);
            }
        } catch (Exception e) {
            logger.error("Error getting Configuration for component: " + pid + ". Ignoring it.", e);
        }
        return cc;
    }

    private ComponentConfiguration getSelfConfiguringComponentConfiguration(String pid) {
        ComponentConfiguration cc = null;
        try {
            String filterExpression = "(" + KURA_SERVICE_PID + "=" + pid + ")";
            ServiceReference<?>[] refs = this.ctx.getBundleContext().getServiceReferences((String) null,
                    filterExpression);
            if (refs != null) {
                for (ServiceReference<?> ref : refs) {
                    String ppid = (String) ref.getProperty(KURA_SERVICE_PID);
                    if (pid.equals(ppid)) {
                        Object obj = this.ctx.getBundleContext().getService(ref);
                        try {
                            if (obj instanceof SelfConfiguringComponent) {
                                SelfConfiguringComponent selfConfigComp = null;
                                selfConfigComp = (SelfConfiguringComponent) obj;
                                try {
                                    cc = selfConfigComp.getConfiguration();
                                    if (!isValidSelfConfiguringComponent(pid, cc)) {

                                        return null;
                                    }
                                } catch (KuraException e) {
                                    logger.error(GETTING_CONFIGURATION_ERROR, pid, e);
                                }
                            } else {
                                if (obj == null) {
                                    cc = getConfigurableComponentConfiguration(pid);
                                    if (cc == null) {
                                        logger.error("null ref object. properties:{}", ref.getProperties());
                                    }
                                } else {
                                    logger.error(
                                            "Component {},  pid: {} is not a SelfConfiguringComponent. Ignoring it.",
                                            obj, pid);
                                }
                            }

                        } finally {
                            this.ctx.getBundleContext().ungetService(ref);
                        }
                    }
                }
            }
        } catch (InvalidSyntaxException e) {
            logger.error(GETTING_CONFIGURATION_ERROR, pid, e);
        }

        return cc;
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
        boolean result = false;
        try {
            logger.debug("pid: {}, property name: {}, value: {}", pid, adId, value);
            Scalar propertyScalar = getScalarFromObject(value);
            Scalar adScalar = Scalar.fromValue(adType);
            if (propertyScalar != adScalar) {
                logger.error(
                        "Type: {} for property named: {} does not match the AD type: {} for returned Configuration of SelfConfiguringComponent with pid: {}",
                        propertyScalar.name(), adId, adType, pid);
            }
            result = true;
        } catch (IllegalArgumentException e) {
            logger.error(
                    "Invalid class for property named: {} for returned Configuration of SelfConfiguringComponent with pid: {}",
                    adId, pid);
        }
        return result;
    }

    private Scalar getScalarFromObject(Object p) {
        Class<?> clazz = p.getClass();
        if (clazz.isArray()) {
            Object[] tempArray = (Object[]) p;
            if (tempArray.length > 0 && tempArray[0] != null) {
                clazz = tempArray[0].getClass();
            } else {
                clazz = clazz.getComponentType();
            }
        }
        return Scalar.fromValue(clazz.getSimpleName());
    }

    private TreeSet<Long> getSnapshotsInternal() {
        // keeps the list of snapshots ordered
        TreeSet<Long> ids = new TreeSet<>();
        String configDir = getSnapshotsDirectory();
        if (configDir != null) {
            File fConfigDir = new File(configDir);
            File[] files = fConfigDir.listFiles();
            if (files != null) {

                for (File file : files) {
                    Matcher m = SNAPSHOT_FILENAME_PATTERN.matcher(file.getName());
                    if (m.matches()) {
                        if (file.length() > 0) {
                            ids.add(Long.parseLong(m.group(1)));
                        } else {
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
        List<ComponentConfiguration> configs = buildCurrentConfiguration(null);
        if (configs == null) {
            return;
        }
        for (ComponentConfiguration config : configs) {
            if (config != null) {
                Map<String, Object> props = config.getConfigurationProperties();
                if (props != null) {
                    String factoryPid = (String) props.get(ConfigurationAdmin.SERVICE_FACTORYPID);

                    if (factoryPid != null) {
                        String pid = config.getPid();
                        logger.info("Creating configuration with pid: {} and factory pid: {}", pid, factoryPid);
                        try {
                            createFactoryConfiguration(factoryPid, pid, props, false);
                        } catch (KuraException e) {
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

                            cfg.update(CollectionsUtil.mapToDictionary(newProperties));

                        } catch (IOException e) {
                            logger.warn("Error seeding initial properties to ConfigAdmin for pid: {}", config.getPid(),
                                    e);
                        }
                    }
                }
            }
        }
    }

    private List<ComponentConfiguration> loadLatestSnapshotConfigurations() throws KuraException {
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
            Boolean isEncrypt = Boolean
                    .valueOf(this.systemService == null || this.systemService.getProperties() == null ? "true"
                            : this.systemService.getProperties().getProperty("kura.snapshots.encrypt", "true"));
            if (isEncrypt != null && !isEncrypt) {
                if (e instanceof KuraException && ((KuraException) e).getCode() == KuraErrorCode.DECODER_ERROR) {
                    logger.error("error snapshot config file, id:{}. delete it", lastestID, e);
                    deleteSnapshotId(lastestID);
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
                    logger.error("error encrypt snapshot config file, id:{}. delete it", lastestID, e);
                    deleteSnapshotId(lastestID);
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
                        registerdOCD);

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

        // Update the new properties
        // use ConfigurationAdmin to do the update
        Configuration config = this.configurationAdmin.getConfiguration(this.servicePidByPid.get(pid), "?");
        config.update(CollectionsUtil.mapToDictionary(mergedProperties));

        if (snapshotOnConfirmation) {
            snapshot();
        }
    }

    private OCD getRegisteredOCD(String pid) {
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
        List<ComponentConfiguration> result = new ArrayList<>();

        // Merge the current configuration of registered components with the provided configurations.
        // It is assumed that the PIDs in the provided configurations is a subset of the registered PIDs.
        List<ComponentConfiguration> currentConfigs = getComponentConfigurationsInternal();
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
        if (value == null) {
            return null;
        }
        if (value instanceof String) {
            return (String) value;
        }
        return value.toString();
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
        try {
            return requireNonNull(this.xmlUnmarshaller.unmarshal(new FileInputStream(file), clazz));
        } catch (final Exception e) {
            throw new KuraException(KuraErrorCode.DECODER_ERROR, e);
        }
    }

    private void manageSnapshotConfigs(List<Throwable> causes, final Map<String, Configuration> currentConfigs,
            final ComponentConfiguration snapshotConfig) {
        final Optional<Configuration> optionalCurrentConfig = Optional
                .ofNullable(currentConfigs.get(snapshotConfig.getPid()));

        try {
            logger.info("Processing configuration rollback for component with pid {}...", snapshotConfig.getPid());
            rollbackConfigurationInternal(snapshotConfig, optionalCurrentConfig);
        } catch (IOException e) {
            logger.warn("Failed to rollback configuration for pid {}", snapshotConfig.getPid(), e);
            causes.add(e);
        }
    }

    private void manageCurrentConfigs(List<Throwable> causes, final Map<String, ComponentConfiguration> snapshotConfigs,
            Iterator<Entry<String, Configuration>> currentConfigsIterator) {
        final Entry<String, Configuration> currentConfigEntry = currentConfigsIterator.next();
        final Optional<ComponentConfiguration> optionalSnapshotConfig = Optional
                .ofNullable(snapshotConfigs.get(currentConfigEntry.getKey()));

        if (!isFactoryComponent(currentConfigEntry)) {

            if (!optionalSnapshotConfig.isPresent() && this.allActivatedPids.contains(currentConfigEntry.getKey())) {
                try {
                    rollbackToDefaultConfig(currentConfigEntry);
                } catch (IOException e) {
                    logger.warn("Failed to revert to factory configuration {}", currentConfigEntry.getKey(), e);
                    causes.add(e);
                }
            }

        } else if (!optionalSnapshotConfig.isPresent() || !Objects.equals(currentConfigEntry.getValue().getFactoryPid(),
                optionalSnapshotConfig.get().getConfigurationProperties().get(ConfigurationAdmin.SERVICE_FACTORYPID))) {

            try {
                deleteFactoryComponent(currentConfigsIterator, currentConfigEntry);
            } catch (IOException e) {
                logger.warn("Failed to delete configuration {}", currentConfigEntry.getKey(), e);
                causes.add(e);
            }
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
            final Optional<Configuration> existingConfig) throws IOException {
        final Optional<String> factoryPid = Optional
                .ofNullable(snapshotConfig.getConfigurationProperties().get(ConfigurationAdmin.SERVICE_FACTORYPID))
                .filter(String.class::isInstance).map(String.class::cast);

        final Map<String, Object> result = snapshotConfig.getConfigurationProperties();

        final Optional<OCD> ocd = Optional.ofNullable(getRegisteredOCD(snapshotConfig.getPid()));

        if (ocd.isPresent()) {
            mergeWithDefaults(ocd.get(), result);
        }

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
            target.update(resultAsDictionary);
            if (factoryPid.isPresent()) {
                registerComponentConfiguration(snapshotConfig.getPid(), target.getPid(), factoryPid.get());
            }
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

    private void rollbackToDefaultConfig(final Entry<String, Configuration> currentConfigEntry) throws IOException {
        logger.info("Rolling back to default configuration for component pid: '{}'", currentConfigEntry.getKey());
        rollbackConfigurationInternal(
                new ComponentConfigurationImpl(currentConfigEntry.getKey(), null, new HashMap<>()),
                Optional.of(currentConfigEntry.getValue()));
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
