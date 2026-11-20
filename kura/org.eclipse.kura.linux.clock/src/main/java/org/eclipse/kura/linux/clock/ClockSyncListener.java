/*******************************************************************************
 * Copyright (c) 2011, 2021 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.linux.clock;

public interface ClockSyncListener {

    void onClockUpdate(long offset, boolean changeSystemClock);

    /** Whether the system clock was confirmed after this Java NTP sample. */
    default boolean applyNtpSample(long offset) {
        onClockUpdate(offset, true);
        return true;
    }
}
