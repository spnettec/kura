/*******************************************************************************
 * Copyright (c) 2016, 2022 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 *  Amit Kumar Mondal
 *  Red Hat Inc
 *******************************************************************************/
package org.eclipse.kura.web.server;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;
import java.util.stream.Stream;

import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.configuration.metatype.OCDService;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.configuration.metatype.Tad;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.eclipse.kura.driver.Driver;
import org.eclipse.kura.driver.descriptor.DriverDescriptor;
import org.eclipse.kura.driver.descriptor.DriverDescriptorService;
import org.eclipse.kura.internal.wire.asset.WireAssetChannelDescriptor;
import org.eclipse.kura.internal.wire.asset.WireAssetOCD;
import org.eclipse.kura.locale.LocaleContextHolder;
import org.eclipse.kura.web.server.util.GwtServerUtil;
import org.eclipse.kura.web.server.util.ServiceLocator;
import org.eclipse.kura.web.shared.FilterUtil;
import org.eclipse.kura.web.shared.GwtKuraErrorCode;
import org.eclipse.kura.web.shared.GwtKuraException;
import org.eclipse.kura.web.shared.IdHelper;
import org.eclipse.kura.web.shared.model.GwtConfigComponent;
import org.eclipse.kura.web.shared.model.GwtWireComponentConfiguration;
import org.eclipse.kura.web.shared.model.GwtWireComponentDescriptor;
import org.eclipse.kura.web.shared.model.GwtWireComposerStaticInfo;
import org.eclipse.kura.web.shared.model.GwtWireConfiguration;
import org.eclipse.kura.web.shared.model.GwtWireGraph;
import org.eclipse.kura.web.shared.model.GwtWireGraphConfiguration;
import org.eclipse.kura.web.shared.model.GwtXSRFToken;
import org.eclipse.kura.web.shared.service.GwtWireGraphService;
import org.eclipse.kura.wire.WireComponent;
import org.eclipse.kura.wire.WireEmitter;
import org.eclipse.kura.wire.WireReceiver;
import org.eclipse.kura.wire.graph.MultiportWireConfiguration;
import org.eclipse.kura.wire.graph.WireComponentConfiguration;
import org.eclipse.kura.wire.graph.WireComponentDefinition;
import org.eclipse.kura.wire.graph.WireComponentDefinitionService;
import org.eclipse.kura.wire.graph.WireGraphConfiguration;
import org.eclipse.kura.wire.graph.WireGraphService;
import org.osgi.framework.BundleContext;
import org.osgi.framework.Filter;
import org.osgi.framework.FrameworkUtil;
import org.osgi.framework.ServiceReference;
import org.osgi.service.cm.ConfigurationAdmin;

/**
 * The class GwtWireGraphServiceImpl implements {@link GwtWireGraphService}
 */
public final class GwtWireGraphServiceImpl extends OsgiRemoteServiceServlet implements GwtWireGraphService {

    private static final ComponentConfiguration WIRE_ASSET_OCD_CONFIG = new ComponentConfigurationImpl(
            "org.eclipse.kura.wire.WireAsset", new WireAssetOCD(), new HashMap<>());
    // private static final GwtConfigComponent WIRE_ASSET_CHANNEL_DESCRIPTOR = GwtServerUtil.toGwtConfigComponent(null,
    // WireAssetChannelDescriptor.get().getDescriptor(), "");

    private static final Filter DRIVER_FILTER = getFilterUnchecked("(objectClass=org.eclipse.kura.driver.Driver)");
    private static final Filter ADDITIONAL_CONFIGS_FILTER = getFilterUnchecked(
            "(|(objectClass=org.eclipse.kura.driver.Driver)(service.factoryPid=org.eclipse.kura.wire.WireAsset))");

    private static final long serialVersionUID = -6577843865830245755L;

    @Override
    public GwtConfigComponent getGwtChannelDescriptor(final GwtXSRFToken xsrfToken, final String driverPid)
            throws GwtKuraException {
        final DriverDescriptorService driverDescriptorService = ServiceLocator.getInstance()
                .getService(DriverDescriptorService.class);

        Optional<DriverDescriptor> driverDescriptorOptional = driverDescriptorService.getDriverDescriptor(driverPid);

        if (driverDescriptorOptional.isPresent()) {
            DriverDescriptor driverDescriptor = driverDescriptorOptional.get();
            return GwtServerUtil.toGwtConfigComponent(driverDescriptor, LocaleContextHolder.getLocale().getLanguage());
        } else {
            throw new GwtKuraException(GwtKuraErrorCode.INTERNAL_ERROR);
        }
    }

    private void fillGwtRenderingProperties(GwtWireComponentConfiguration component,
            Map<String, Object> renderingProperties) {
        component.setInputPortCount((Integer) renderingProperties.get("inputPortCount"));
        component.setOutputPortCount((Integer) renderingProperties.get("outputPortCount"));
        component.setPositionX(getOrDefault(renderingProperties, "position.x", 0.0f));
        component.setPositionY(getOrDefault(renderingProperties, "position.y", 0.0f));
    }

    @SuppressWarnings("unchecked")
    private static <T> T getOrDefault(final Map<String, Object> properties, final String key, final T defaultValue) {
        final Object raw = properties.get(key);

        if (defaultValue.getClass().isInstance(raw)) {
            return (T) raw;
        }

        return defaultValue;
    }

    private List<GwtConfigComponent> getAdditionalConfigurations(Set<String> wireComponentsInGraph,
            Set<String> driverPids) throws GwtKuraException {

        final List<ComponentConfiguration> configurations = ServiceLocator.applyToServiceOptionally(
                ConfigurationService.class, cs -> cs.getComponentConfigurations(ADDITIONAL_CONFIGS_FILTER));

        final List<GwtConfigComponent> result = new ArrayList<>();

        for (ComponentConfiguration config : configurations) {
            final String pid = config.getPid();
            final Object factoryPid = config.getConfigurationProperties().get(ConfigurationAdmin.SERVICE_FACTORYPID);
            final boolean isDriver = driverPids.contains(pid);
            final boolean isAssetNotInGraph = factoryPid != null && "org.eclipse.kura.wire.WireAsset".equals(factoryPid)
                    && !wireComponentsInGraph.contains(pid);
            if (isDriver || isAssetNotInGraph) {
                final GwtConfigComponent gwtConfig = GwtServerUtil.toGwtConfigComponent(config,
                        LocaleContextHolder.getLocale().getLanguage());
                gwtConfig.setIsDriver(isDriver);
                result.add(gwtConfig);
            }
        }

        return result;
    }

    @Override
    public GwtWireGraphConfiguration getWiresConfiguration(final GwtXSRFToken xsrfToken) throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        return getWiresConfigurationInternal();
    }

    private GwtWireGraphConfiguration getWiresConfigurationInternal() throws GwtKuraException {
        final GwtWireGraphConfiguration result = new GwtWireGraphConfiguration();

        final WireGraphConfiguration wireGraphConfiguration = ServiceLocator
                .applyToServiceOptionally(WireGraphService.class, WireGraphService::get);

        final Set<String> wireComponentsInGraph = new HashSet<>();

        result.setWireComponentConfigurations(
                wireGraphConfiguration.getWireComponentConfigurations().stream().map(wireComponentConfig -> {
                    final ComponentConfiguration config = wireComponentConfig.getConfiguration();
                    if (config == null) {
                        return null;
                    }
                    final String pid = config.getPid();
                    final GwtWireComponentConfiguration gwtWireComponentConfig = new GwtWireComponentConfiguration();
                    GwtConfigComponent gwtConfig = GwtServerUtil.toGwtConfigComponent(config,
                            LocaleContextHolder.getLocale().getLanguage());
                    if (gwtConfig == null) {
                        gwtConfig = new GwtConfigComponent();
                        gwtConfig.setComponentId(pid);
                    }
                    gwtConfig.setIsWireComponent(true);
                    gwtWireComponentConfig.setConfiguration(gwtConfig);
                    fillGwtRenderingProperties(gwtWireComponentConfig, wireComponentConfig.getProperties());
                    wireComponentsInGraph.add(pid);
                    return gwtWireComponentConfig;
                }).filter(Objects::nonNull).collect(Collectors.toList()));

        result.setWires(wireGraphConfiguration.getWireConfigurations().stream().map(config -> {
            final GwtWireConfiguration gwtConfig = new GwtWireConfiguration();
            gwtConfig.setEmitterPid(config.getEmitterPid());
            gwtConfig.setEmitterPort(config.getEmitterPort());
            gwtConfig.setReceiverPid(config.getReceiverPid());
            gwtConfig.setReceiverPort(config.getReceiverPort());
            return gwtConfig;
        }).collect(Collectors.toList()));

        final List<String> allActivePids = new ArrayList<>();
        final Set<String> driverPids = new HashSet<>();

        for (final ServiceReference<?> ref : getAllServiceReferences()) {
            final Object kuraServicePid = ref.getProperty(ConfigurationService.KURA_SERVICE_PID);

            if (!(kuraServicePid instanceof String)) {
                continue;
            }

            allActivePids.add((String) kuraServicePid);

            if (DRIVER_FILTER.match(ref)) {
                driverPids.add((String) kuraServicePid);
            }
        }

        result.setAllActivePids(allActivePids);
        result.setAdditionalConfigurations(getAdditionalConfigurations(wireComponentsInGraph, driverPids));

        return result;
    }

    private Map<String, Object> getRenderingProperties(GwtWireComponentConfiguration component) {

        final Map<String, Object> result = new HashMap<>();

        result.put("inputPortCount", component.getInputPortCount());
        result.put("outputPortCount", component.getOutputPortCount());
        result.put("position.x", (float) component.getPositionX());
        result.put("position.y", (float) component.getPositionY());

        return result;
    }

    /** {@inheritDoc} */
    @Override
    public void updateWireConfiguration(final GwtXSRFToken xsrfToken, GwtWireGraphConfiguration gwtConfigurations,
            List<GwtConfigComponent> additionalGwtConfigs) throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        for (final GwtWireComponentConfiguration config : gwtConfigurations.getWireComponentConfigurations()) {
            if (!GwtServerUtil.isFactoryOfAnyService(config.getConfiguration().getFactoryId(), WireComponent.class,
                    WireEmitter.class, WireReceiver.class)) {
                throw new GwtKuraException(GwtKuraErrorCode.ILLEGAL_ARGUMENT);
            }
        }

        for (final GwtConfigComponent config : additionalGwtConfigs) {
            if (!GwtServerUtil.isFactoryOfAnyService(config.getFactoryId(), Driver.class)) {
                throw new GwtKuraException(GwtKuraErrorCode.ILLEGAL_ARGUMENT);
            }
        }

        final List<String> receivedConfigurationPids = Stream.concat(gwtConfigurations.getWireComponentConfigurations() //
                .stream()//
                .map(config -> config.getConfiguration().getComponentId()),
                additionalGwtConfigs //
                        .stream() //
                        .map(GwtConfigComponent::getComponentId))
                .collect(Collectors.toList());

        final Iterator<String> receivedConfigurationPidsIterator = receivedConfigurationPids.iterator();

        final Map<String, ComponentConfiguration> originalConfigs;

        if (receivedConfigurationPidsIterator.hasNext()) {
            final Filter receivedConfigurationPidsFilter = getFilter(
                    FilterUtil.getPidFilter(receivedConfigurationPidsIterator));

            originalConfigs = ServiceLocator.applyToServiceOptionally(ConfigurationService.class, cs -> cs //
                    .getComponentConfigurations(receivedConfigurationPidsFilter) //
                    .stream() //
                    .collect(Collectors.toMap(ComponentConfiguration::getPid, c -> c)));
        } else {
            originalConfigs = Collections.emptyMap();
        }

        final List<WireComponentConfiguration> wireComponentConfigurations = gwtConfigurations
                .getWireComponentConfigurations() //
                .stream() //
                .map(gwtConfig -> {

                    final GwtConfigComponent receivedConfig = gwtConfig.getConfiguration();
                    final ComponentConfiguration config = GwtServerUtil.fromGwtConfigComponent(receivedConfig,
                            originalConfigs.get(receivedConfig.getComponentId()));

                    final Map<String, Object> renderingProperties = getRenderingProperties(gwtConfig);

                    return new WireComponentConfiguration(config, renderingProperties);
                }) //
                .collect(Collectors.toList());

        final List<MultiportWireConfiguration> wireConfigurations = gwtConfigurations //
                .getWires() //
                .stream() //
                .map(gwtWire -> new MultiportWireConfiguration(gwtWire.getEmitterPid(), gwtWire.getReceiverPid(),
                        gwtWire.getEmitterPort(), gwtWire.getReceiverPort()))
                .collect(Collectors.toList());

        final List<ComponentConfiguration> additionalConfigs = additionalGwtConfigs.stream().map(gwtConfig -> {
            final ComponentConfiguration originalConfig = originalConfigs.get(gwtConfig.getComponentId());
            if (originalConfig == null) {
                return null;
            }
            return GwtServerUtil.fromGwtConfigComponent(gwtConfig, originalConfig);
        }).filter(Objects::nonNull).collect(Collectors.toList());

        if (!additionalConfigs.isEmpty()) {
            ServiceLocator.applyToServiceOptionally(ConfigurationService.class, configurationService -> {
                configurationService.updateConfigurations(additionalConfigs);
                return null;
            });
        }

        ServiceLocator.applyToServiceOptionally(WireGraphService.class, wireGraphService -> {
            wireGraphService.update(new WireGraphConfiguration(wireComponentConfigurations, wireConfigurations));
            return null;
        });
    }

    @Deprecated
    private GwtConfigComponent getWireAssetDefinition() { // TODO provide a metatype for WireAsset

        return GwtServerUtil.toGwtConfigComponent(WIRE_ASSET_OCD_CONFIG, LocaleContextHolder.getLocale().getLanguage());
    }

    private void fillWireComponentDefinitions(List<GwtWireComponentDescriptor> resultDescriptors,
            List<GwtConfigComponent> resultDefinitions) throws GwtKuraException {

        ServiceLocator.applyToServiceOptionally(WireComponentDefinitionService.class,
                wireComponentDefinitionService -> {
                    for (WireComponentDefinition wireComponentDefinition : wireComponentDefinitionService
                            .getComponentDefinitions()) {
                        ComponentConfigurationImpl impl = (ComponentConfigurationImpl) wireComponentDefinition
                                .getComponentOCD();
                        if (impl.getPid().equals(WIRE_ASSET_OCD_CONFIG.getPid())) {
                            impl.setDefinition((Tocd) WIRE_ASSET_OCD_CONFIG
                                    .getLocalizedDefinition(LocaleContextHolder.getLocale().getLanguage()));
                        } else {
                            Tocd ocd0 = (Tocd) impl
                                    .getLocalizedDefinition(LocaleContextHolder.getLocale().getLanguage());
                            impl.setDefinition(ocd0);
                        }

                        final GwtWireComponentDescriptor result = new GwtWireComponentDescriptor(
                                toComponentName(wireComponentDefinition),
                                toComponentDescription(wireComponentDefinition),
                                wireComponentDefinition.getFactoryPid(), wireComponentDefinition.getMinInputPorts(),
                                wireComponentDefinition.getMaxInputPorts(),
                                wireComponentDefinition.getDefaultInputPorts(),
                                wireComponentDefinition.getMinOutputPorts(),
                                wireComponentDefinition.getMaxOutputPorts(),
                                wireComponentDefinition.getDefaultOutputPorts(),
                                wireComponentDefinition.getInputPortNames(),
                                wireComponentDefinition.getOutputPortNames());

                        final GwtConfigComponent ocd = GwtServerUtil.toGwtConfigComponent(
                                wireComponentDefinition.getComponentOCD(),
                                LocaleContextHolder.getLocale().getLanguage());
                        if (ocd != null) {
                            resultDefinitions.add(ocd);
                        }
                        result.setToolsSorted(wireComponentDefinition.getToolsSorted());
                        resultDescriptors.add(result);
                    }
                    resultDefinitions.add(getWireAssetDefinition());
                    return null;
                });
    }

    private String toComponentName(WireComponentDefinition wireComponentDefinition) {
        if (wireComponentDefinition.getComponentOCD() == null) {
            return IdHelper.getLastIdComponent(wireComponentDefinition.getFactoryPid());
        }

        if (wireComponentDefinition.getComponentOCD().getDefinition() == null) {
            return IdHelper.getLastIdComponent(wireComponentDefinition.getFactoryPid());
        }

        if (wireComponentDefinition.getComponentOCD().getDefinition().getName() == null) {
            return IdHelper.getLastIdComponent(wireComponentDefinition.getFactoryPid());
        }

        return wireComponentDefinition.getComponentOCD().getDefinition().getName();
    }

    private String toComponentDescription(WireComponentDefinition wireComponentDefinition) {
        if (wireComponentDefinition.getComponentOCD() == null) {
            return IdHelper.getLastIdComponent(wireComponentDefinition.getFactoryPid());
        }

        if (wireComponentDefinition.getComponentOCD().getDefinition() == null) {
            return IdHelper.getLastIdComponent(wireComponentDefinition.getFactoryPid());
        }

        if (wireComponentDefinition.getComponentOCD().getDefinition().getName() == null) {
            return IdHelper.getLastIdComponent(wireComponentDefinition.getFactoryPid());
        }

        return wireComponentDefinition.getComponentOCD().getDefinition().getDescription();
    }

    private void fillDriverDefinitions(List<GwtConfigComponent> resultDefinitions) throws GwtKuraException {
        ServiceLocator.applyToServiceOptionally(OCDService.class, ocdService -> {

            for (ComponentConfiguration config : ocdService.getServiceProviderOCDs("org.eclipse.kura.driver.Driver")) {
                final GwtConfigComponent descriptor = GwtServerUtil.toGwtConfigComponent(config,
                        LocaleContextHolder.getLocale().getLanguage());
                if (descriptor != null) {
                    descriptor.setIsDriver(true);
                    resultDefinitions.add(descriptor);
                }
            }
            return null;
        });
    }

    private void fillDriverDescriptors(List<GwtConfigComponent> resultDescriptors) throws GwtKuraException {

        ServiceLocator.applyToServiceOptionally(DriverDescriptorService.class, driverDescriptorService -> {

            driverDescriptorService.listDriverDescriptors().stream()
                    .map(descriptor -> GwtServerUtil.toGwtConfigComponent(descriptor,
                            LocaleContextHolder.getLocale().getLanguage()))
                    .filter(Objects::nonNull).forEach(resultDescriptors::add);
            return null;
        });
    }

    @Override
    public GwtWireComposerStaticInfo getWireComposerStaticInfo(GwtXSRFToken xsrfToken) throws GwtKuraException {
        this.checkXSRFToken(xsrfToken);

        return getWireComposerStaticInfoInternal();
    }

    private GwtWireComposerStaticInfo getWireComposerStaticInfoInternal() throws GwtKuraException {
        final GwtWireComposerStaticInfo result = new GwtWireComposerStaticInfo();

        final List<GwtWireComponentDescriptor> componentDescriptors = new ArrayList<>();
        final List<GwtConfigComponent> componentDefinitions = new ArrayList<>();
        final List<GwtConfigComponent> driverDescriptors = new ArrayList<>();

        fillWireComponentDefinitions(componentDescriptors, componentDefinitions);
        fillDriverDefinitions(componentDefinitions);
        fillDriverDescriptors(driverDescriptors);

        result.setComponentDefinitions(componentDefinitions);
        result.setWireComponentDescriptors(componentDescriptors);
        result.setDriverDescriptors(driverDescriptors);
        GwtConfigComponent wireAssetChannelDescriptor = GwtServerUtil.toGwtConfigComponent(
                toComponentConfiguration("", WireAssetChannelDescriptor.get().getDescriptor()),
                LocaleContextHolder.getLocale().getLanguage());
        result.setBaseChannelDescriptor(wireAssetChannelDescriptor);

        return result;
    }

    private ComponentConfiguration toComponentConfiguration(String pid, Object descriptor) {
        if (!(descriptor instanceof List<?>)) {
            return null;
        }

        final List<?> ads = (List<?>) descriptor;

        final Tocd ocd = new Tocd();
        ocd.setId(pid);
        for (final Object ad : ads) {
            if (!(ad instanceof Tad)) {
                return null;
            }
            ocd.addAD((Tad) ad);
        }
        Tocd tocd = (Tocd) WIRE_ASSET_OCD_CONFIG.getDefinition();
        ocd.setLocalization(tocd.getLocalization());
        ocd.setLocaleUrls(tocd.getLocaleUrls());
        return new ComponentConfigurationImpl(pid, ocd, null);
    }

    private static Filter getFilterUnchecked(final String filter) {
        try {
            return FrameworkUtil.createFilter(filter);
        } catch (final Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static Filter getFilter(final String filter) throws GwtKuraException {
        try {
            return FrameworkUtil.createFilter(filter);
        } catch (final Exception e) {
            throw new GwtKuraException(GwtKuraErrorCode.ILLEGAL_ARGUMENT);
        }
    }

    private static ServiceReference<?>[] getAllServiceReferences() {
        final BundleContext context = FrameworkUtil.getBundle(GwtDriverAndAssetServiceImpl.class).getBundleContext();
        try {
            return context.getAllServiceReferences(null, null);
        } catch (final Exception e) {
            throw new IllegalStateException(e);
        }
    }

    @Override
    public GwtWireGraph getWireGraph(final GwtXSRFToken xsrfToken) throws GwtKuraException {
        checkXSRFToken(xsrfToken);

        final GwtWireComposerStaticInfo staticInfo = getWireComposerStaticInfoInternal();
        final GwtWireGraphConfiguration wireGraphConfiguration = getWiresConfigurationInternal();

        return new GwtWireGraph(staticInfo, wireGraphConfiguration);
    }

}
