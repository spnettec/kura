/*******************************************************************************
 * Copyright (c) 2025 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 ******************************************************************************/
package org.eclipse.kura.core.identity;

import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.BooleanSupplier;
import java.util.function.Supplier;

import org.eclipse.kura.configuration.ConfigurableComponent;
import org.eclipse.kura.identity.LoginBannerService;

public class LoginBannerServiceImpl implements LoginBannerService, ConfigurableComponent {

    private AtomicReference<Map<String, Object>> options = null;

    public void activate(Map<String, Object> options) {
        this.options = new AtomicReference<>(options);
    }

    public void updated(Map<String, Object> options) {
        this.options.set(options);
    }

    @Override
    public Optional<String> getPreLoginBanner() {
        final Map<String, Object> currentOptions = this.options.get();

        return getMessage(() -> (boolean) currentOptions.getOrDefault("pre.login.banner.enabled", false),
                () -> getStringValue(currentOptions, "pre.login.banner.content"));
    }

    @Override
    public Optional<String> getPostLoginBanner() {
        final Map<String, Object> currentOptions = this.options.get();

        return getMessage(() -> (boolean) currentOptions.getOrDefault("post.login.banner.enabled", false),
                () -> getStringValue(currentOptions, "post.login.banner.content"));
    }

    private static final Optional<String> getMessage(final BooleanSupplier enabled, final Supplier<String> message) {
        if (enabled.getAsBoolean()) {
            return Optional.ofNullable(message.get()).map(String::trim).filter(s -> !s.isEmpty());
        } else {
            return Optional.empty();
        }
    }

    private String getStringValue(Map<String, Object> options, String name) {
        final Object propertyRaw = options.get(name);
        if (!(propertyRaw instanceof String)) {
            return "";
        }

        String property = (String) propertyRaw;
        property = property.trim();
        return property;
    }

}
