/*******************************************************************************
 * Copyright (c) 2019, 2020 Eurotech and/or its affiliates and others
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
import java.util.Collections;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.eclipse.kura.core.configuration.metatype.Tscalar;
import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.web.shared.model.GwtConsoleUserOptions;
import org.osgi.framework.Bundle;
import org.osgi.framework.Constants;
import org.osgi.framework.FrameworkUtil;

public class ConsoleOptions {

    private final SelfConfiguringComponentProperty<String> username = new SelfConfiguringComponentProperty<>(
            new AdBuilder("console.username.value", "%username", Tscalar.STRING) //
                    .setDefault("admin") //
                    .setDescription("%usernameDesc") //
                    .build(), //
            String.class);

    private final SelfConfiguringComponentProperty<String> userPassword;

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

    private final SelfConfiguringComponentProperty<Boolean> bannerEnabled = new SelfConfiguringComponentProperty<>(
            new AdBuilder("access.banner.enabled", "%bannerEnabled", Tscalar.BOOLEAN) //
                    .setDefault("false") //
                    .setDescription("%bannerEnabledDesc") //
                    .build(), //
            Boolean.class);

    private final SelfConfiguringComponentProperty<String> bannerContent = new SelfConfiguringComponentProperty<>(
            new AdBuilder("access.banner.content", "%bannerContent", Tscalar.STRING) //
                    .setDefault("Sample Banner Content") //
                    .setDescription("%bannerContentDesc |TextArea") //
                    .build(), //
            String.class);

    private final SelfConfiguringComponentProperty<Integer> passwordMinLength = new SelfConfiguringComponentProperty<>(
            new AdBuilder("new.password.min.length", "%minPasswordLength", Tscalar.INTEGER) //
                    .setDefault("8") //
                    .setMin("0") //
                    .setDescription("%minPasswordLengthDesc") //
                    .build(), //
            Integer.class);

    private final SelfConfiguringComponentProperty<Boolean> passwordRequireDigits = new SelfConfiguringComponentProperty<>(
            new AdBuilder("new.password.require.digits", "%passwordRequireDigits", Tscalar.BOOLEAN) //
                    .setDefault("false") //
                    .setDescription("%passwordRequireDigitsDesc") //
                    .build(), //
            Boolean.class);

    private final SelfConfiguringComponentProperty<Boolean> passwordRequireSpecialCharacters = new SelfConfiguringComponentProperty<>(
            new AdBuilder("new.password.require.special.characters", "%passwordRequireSpecialCharacters",
                    Tscalar.BOOLEAN) //
                            .setDefault("false") //
                            .setDescription("%passwordRequireSpecialCharactersDesc") //
                            .build(), //
            Boolean.class);

    private final SelfConfiguringComponentProperty<Boolean> passwordRequireBothCases = new SelfConfiguringComponentProperty<>(
            new AdBuilder("new.password.require.both.cases", "%passwordRequireBothCases", Tscalar.BOOLEAN) //
                    .setDefault("false") //
                    .setDescription("%passwordRequireBothCasesDesc") //
                    .build(), //
            Boolean.class);

    private final List<SelfConfiguringComponentProperty<?>> configurationProperties = new ArrayList<>();
    private final Map<String, SelfConfiguringComponentProperty<Boolean>> authenticationMethodProperties = new HashMap<>();
    private final ComponentConfiguration config;

    private ConsoleOptions(final CryptoService cryptoService) {
        this.userPassword = initPasswordProperty(cryptoService);

        initProperties();

        this.config = toComponentConfiguration();
    }

    private ConsoleOptions(final Map<String, Object> properties, final CryptoService cryptoService) {
        this.userPassword = initPasswordProperty(cryptoService);

        initProperties();

        for (final SelfConfiguringComponentProperty<?> property : configurationProperties) {
            property.update(properties);
        }

        this.config = toComponentConfiguration();
    }

    public static ConsoleOptions defaultConfiguration(final CryptoService cryptoService) {
        return new ConsoleOptions(cryptoService);
    }

    public static ConsoleOptions fromProperties(final Map<String, Object> properties,
            final CryptoService cryptoService) {
        return new ConsoleOptions(properties, cryptoService);
    }

    public String getUsername() {
        return this.username.get();
    }

    public String getUserPassword() {
        return this.userPassword.get();
    }

    public String getAppRoot() {
        return this.appRoot.get();
    }

    public int getSessionMaxInactivityInterval() {
        return this.sessionMaxInactivityInterval.get();
    }

    public boolean isBannerEnabled() {
        return this.bannerEnabled.get();
    }

    public String getBannerContent() {
        return this.bannerContent.get();
    }

    public Set<String> getEnabledAuthMethods() {
        return authenticationMethodProperties.entrySet().stream().filter(e -> e.getValue().get()).map(e -> e.getKey())
                .collect(Collectors.toSet());
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

    public GwtConsoleUserOptions getUserOptions() {
        final GwtConsoleUserOptions result = new GwtConsoleUserOptions();

        result.setPasswordMinimumLength(passwordMinLength.get());
        result.setPasswordRequireDigits(passwordRequireDigits.get());
        result.setPasswordRequireSpecialChars(passwordRequireSpecialCharacters.get());
        result.setPasswordRequireBothCases(passwordRequireBothCases.get());

        return result;
    }

    private void initProperties() {
        configurationProperties.add(username);
        configurationProperties.add(userPassword);
        configurationProperties.add(appRoot);
        configurationProperties.add(sessionMaxInactivityInterval);
        configurationProperties.add(bannerEnabled);
        configurationProperties.add(bannerContent);
        configurationProperties.add(passwordMinLength);
        configurationProperties.add(passwordRequireDigits);
        configurationProperties.add(passwordRequireSpecialCharacters);
        configurationProperties.add(passwordRequireBothCases);

        addAuthenticationMethodProperties();
    }

    private static SelfConfiguringComponentProperty<String> initPasswordProperty(final CryptoService cryptoService) {

        return new SelfConfiguringComponentProperty<>(
                new AdBuilder("console.password.value", "%password", Tscalar.PASSWORD) //
                        .setDefault("admin") //
                        .setDescription("%passwordDesc") //
                        .build(), //
                String.class, cryptoService);
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

        for (final SelfConfiguringComponentProperty<?> property : configurationProperties) {
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

        authenticationMethodProperties.put(name, result);
        configurationProperties.add(result);

    }

    private static String getAuthenticationMethodPropertyId(final String name) {
        return "auth.method" + name.replaceAll(" ", ".");
    }

    private void addAuthenticationMethodProperties() {
        final Set<String> builtinAuthenticationMethods = Console.instance().getBuiltinAuthenticationMethods();

        for (final String authMethod : Console.instance().getAuthenticationMethods()) {
            addAuthenticationMethodProperty(authMethod, builtinAuthenticationMethods.contains(authMethod));
        }
    }

}
