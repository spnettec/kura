/*******************************************************************************
 * Copyright (c) 2019, 2025 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 *******************************************************************************/
package org.eclipse.kura.web;

import java.net.URL;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;

import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.eclipse.kura.core.configuration.metatype.Tscalar;
import org.eclipse.kura.web.server.util.GwtServerUtil;
import org.osgi.framework.Bundle;
import org.osgi.framework.Constants;
import org.osgi.framework.FrameworkUtil;

public class ConsoleOptions {

    private final SelfConfiguringComponentProperty<String> appRoot = new SelfConfiguringComponentProperty<>(
            new AdBuilder("app.root", "%root", Tscalar.STRING) //
                    .setDefault("/admin/console") //
                    .setDescription("%rootDesc") //
                    .build(), //
            String.class);

    private final SelfConfiguringComponentProperty<Integer> sessionMaxInactivityInterval = new SelfConfiguringComponentProperty<>(
            new AdBuilder("session.max.inactivity.interval", "%sessionMaxInactivityInterval", Tscalar.INTEGER) //
                    .setDefault("15") //
                    .setMin("1") //
                    .setDescription("%sessionMaxInactivityIntervalDesc") //
                    .build(), //
            Integer.class);
    private final SelfConfiguringComponentProperty<Integer[]> allowedPorts = new SelfConfiguringComponentProperty<>(
            new AdBuilder("allowed.ports", "%allowedPorts", Tscalar.INTEGER) //
                    .setRequired(false) //
                    .setCardinality(3) //
                    // .setDefault("443,4443,8080") //
                    .setDescription("%allowedPortsDesc") //
                    .build(), //
            Integer[].class);

    private final SelfConfiguringComponentProperty<String> sslManagerServiceTarget = new SelfConfiguringComponentProperty<>(
            new AdBuilder("SslManagerService.target", "%sslManagerServiceTarget", Tscalar.STRING) //
                    .setRequired(true) //
                    .setDefault("(kura.service.pid=org.eclipse.kura.ssl.SslManagerService)") //
                    .setDescription("%sslManagerServiceTargetDesc") //
                    .build(),
            String.class);

    private final List<SelfConfiguringComponentProperty<?>> configurationProperties = new ArrayList<>();
    private final Map<String, SelfConfiguringComponentProperty<Boolean>> authenticationMethodProperties = new HashMap<>();
    private final ComponentConfiguration config;

    private ConsoleOptions() {
        initProperties();

        this.config = toComponentConfiguration();
    }

    private ConsoleOptions(final Map<String, Object> properties) {
        initProperties();

        for (final SelfConfiguringComponentProperty<?> property : this.configurationProperties) {
            property.update(properties);
        }

        this.config = toComponentConfiguration();
    }

    public static ConsoleOptions defaultConfiguration() {
        return new ConsoleOptions();
    }

    public static ConsoleOptions fromProperties(final Map<String, Object> properties) {
        return new ConsoleOptions(properties);
    }

    public String getAppRoot() {
        return this.appRoot.get();
    }

    public int getSessionMaxInactivityInterval() {
        return this.sessionMaxInactivityInterval.get();
    }

    public Set<String> getEnabledAuthMethods() {
        return this.authenticationMethodProperties.entrySet().stream().filter(e -> e.getValue().get())
                .map(Map.Entry::getKey).collect(Collectors.toSet());
    }

    public Set<Integer> getAllowedPorts() {
        return GwtServerUtil.getArrayProperty(this.allowedPorts.get(), Integer.class);
    }

    public String getSslManagerServiceTarget() {
        return this.sslManagerServiceTarget.get();
    }

    public boolean isPortAllowed(final int port) {
        final Optional<Integer[]> ports = this.allowedPorts.getOptional();

        if (!ports.isPresent() || ports.get().length == 0) {
            return true;
        }

        for (final Integer allowed : ports.get()) {
            if (allowed != null && allowed == port) {
                return true;
            }
        }

        return false;
    }

    public ComponentConfiguration getConfiguration() {
        return this.config;
    }

    public boolean isAuthenticationMethodEnabled(final String name) {
        final SelfConfiguringComponentProperty<Boolean> property = this.authenticationMethodProperties.get(name);

        if (property == null) {
            return false;
        }

        return property.get();
    }

    private void initProperties() {
        this.configurationProperties.add(this.appRoot);
        this.configurationProperties.add(this.sessionMaxInactivityInterval);
        this.configurationProperties.add(this.allowedPorts);
        this.configurationProperties.add(this.sslManagerServiceTarget);

        addAuthenticationMethodProperties();
    }

    private ComponentConfiguration toComponentConfiguration() {
        final Tocd definition = new Tocd();

        definition.setId("org.eclipse.kura.web.Console");
        definition.setName("%name");
        definition.setLocalization("OSGI-INF/l10n/WebConsole");
        definition
                .setLocaleUrls(findAllEntries(FrameworkUtil.getBundle(this.getClass()), definition.getLocalization()));
        definition.setDescription("%description");

        final Map<String, Object> properties = new HashMap<>();

        for (final SelfConfiguringComponentProperty<?> property : this.configurationProperties) {
            definition.addAD(property.getAd());
            property.fillValue(properties);
        }

        return new ComponentConfigurationImpl("org.eclipse.kura.web.Console", definition, properties);
    }

    private static URL[] findAllEntries(Bundle bundle, String path) {
        path = path == null ? Constants.BUNDLE_LOCALIZATION_DEFAULT_BASENAME : path;
        String directory = "/"; //$NON-NLS-1$
        String file = "*"; //$NON-NLS-1$
        int index = path.lastIndexOf('/');
        if (index > 0) {
            directory = path.substring(0, index);
        }

        Enumeration<URL> entries = bundle.findEntries(directory, file, false);
        if (entries == null) {
            return new URL[0];
        }
        List<URL> list = Collections.list(entries);
        return list.toArray(new URL[list.size()]);
    }

    private void addAuthenticationMethodProperty(final String name, final boolean enabledByDefault) {
        final SelfConfiguringComponentProperty<Boolean> result = new SelfConfiguringComponentProperty<>(
                new AdBuilder(getAuthenticationMethodPropertyId(name), "%authenticationMethod" + name + "Enabled",
                        Tscalar.BOOLEAN) //
                        .setDefault(Boolean.toString(enabledByDefault)) //
                        .setDescription("%authenticationMethod" + name + "EnabledDesc") //
                        .build(), //
                Boolean.class);

        this.authenticationMethodProperties.put(name, result);
        this.configurationProperties.add(result);

    }

    private static String getAuthenticationMethodPropertyId(final String name) {
        return "auth.method" + name.replace(" ", ".");
    }

    private void addAuthenticationMethodProperties() {
        final Set<String> builtinAuthenticationMethods = Console.instance().getBuiltinAuthenticationMethods();

        for (final String authMethod : Console.instance().getAuthenticationMethods()) {
            addAuthenticationMethodProperty(authMethod, builtinAuthenticationMethods.contains(authMethod));
        }
    }

    @Override
    public int hashCode() {
        return Objects.hash(this.allowedPorts, this.appRoot, this.authenticationMethodProperties,
                this.sessionMaxInactivityInterval, this.sslManagerServiceTarget);
    }

    @Override
    public boolean equals(Object obj) {

        if (this == obj) {
            return true;
        }
        if (obj == null || getClass() != obj.getClass()) {
            return false;
        }
        ConsoleOptions other = (ConsoleOptions) obj;

        return Objects.equals(this.appRoot.get(), other.appRoot.get())
                && Objects.equals(this.sessionMaxInactivityInterval.get(), other.sessionMaxInactivityInterval.get())
                && Arrays.equals(
                        this.allowedPorts.getOptional().isPresent() ? this.allowedPorts.get() : new Integer[] {},
                        other.allowedPorts.getOptional().isPresent() ? other.allowedPorts.get() : new Integer[] {})
                && Objects.equals(this.sslManagerServiceTarget.get(), other.sslManagerServiceTarget.get())
                && Objects.equals(getEnabledAuthMethods(), other.getEnabledAuthMethods());

    }

}
