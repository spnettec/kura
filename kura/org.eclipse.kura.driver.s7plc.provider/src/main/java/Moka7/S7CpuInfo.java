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
 *
 * @author Davide
 */
public class S7CpuInfo {

    private final int BufSize = 256;
    protected byte[] Buffer = new byte[this.BufSize];

    protected void Update(byte[] Src, int Pos) {
        System.arraycopy(Src, Pos, this.Buffer, 0, this.BufSize);
    }

    public String ModuleTypeName() {
        return S7.GetStringAt(this.Buffer, 172, 32);
    }

    public String SerialNumber() {
        return S7.GetStringAt(this.Buffer, 138, 24);
    }

    public String ASName() {
        return S7.GetStringAt(this.Buffer, 2, 24);
    }

    public String Copyright() {
        return S7.GetStringAt(this.Buffer, 104, 26);
    }

    public String ModuleName() {
        return S7.GetStringAt(this.Buffer, 36, 24);
    }
}
