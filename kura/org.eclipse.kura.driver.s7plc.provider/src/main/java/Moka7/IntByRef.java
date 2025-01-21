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
package Moka7;

/**
 * Quick class to pass an integer by reference
 *
 * @author Davide
 */

public class IntByRef {

    public IntByRef(int Val) {
        this.Value = Val;
    }

    public IntByRef() {
        this.Value = 0;
    }

    public int Value;
}
