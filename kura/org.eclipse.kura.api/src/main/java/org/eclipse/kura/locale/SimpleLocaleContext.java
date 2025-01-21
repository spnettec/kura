/*******************************************************************************
 * Copyright (c) 2021, 2025 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.locale;

import java.util.Locale;

import org.eclipse.kura.annotation.Nullable;

public class SimpleLocaleContext implements LocaleContext {

    @Nullable
    private final Locale locale;

    /**
     * Create a new SimpleLocaleContext that exposes the specified Locale.
     * Every {@link #getLocale()} call will return this Locale.
     *
     * @param locale
     *                   the Locale to expose, or {@code null} for no specific one
     */
    public SimpleLocaleContext(@Nullable Locale locale) {
        this.locale = locale;
    }

    @Override
    @Nullable
    public Locale getLocale() {
        return this.locale;
    }

    @Override
    public String toString() {
        return this.locale != null ? this.locale.toString() : "-";
    }

}