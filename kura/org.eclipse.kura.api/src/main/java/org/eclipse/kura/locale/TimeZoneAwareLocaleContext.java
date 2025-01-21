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

import java.util.TimeZone;

import org.eclipse.kura.annotation.Nullable;

public interface TimeZoneAwareLocaleContext extends LocaleContext {

    /**
     * Return the current TimeZone, which can be fixed or determined dynamically,
     * depending on the implementation strategy.
     *
     * @return the current TimeZone, or {@code null} if no specific TimeZone associated
     */
    @Nullable
    TimeZone getTimeZone();

}