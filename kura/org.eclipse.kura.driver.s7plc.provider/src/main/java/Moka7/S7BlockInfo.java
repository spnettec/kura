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

import java.util.Date;

/**
 *
 * @author Davide
 */
public class S7BlockInfo {

    private final int BufSize = 96;
    // MilliSeconds between 1970/1/1 (Java time base) and 1984/1/1 (Siemens base)
    private final long DeltaMilliSecs = 441763200000L;
    protected byte[] Buffer = new byte[this.BufSize];

    protected void Update(byte[] Src, int Pos) {
        System.arraycopy(Src, Pos, this.Buffer, 0, this.BufSize);
    }

    public int BlkType() {
        return this.Buffer[2];
    }

    public int BlkNumber() {
        return S7.GetWordAt(this.Buffer, 3);
    }

    public int BlkLang() {
        return this.Buffer[1];
    }

    public int BlkFlags() {
        return this.Buffer[0];
    }

    public int MC7Size()  // The real size in bytes
    {
        return S7.GetWordAt(this.Buffer, 31);
    }

    public int LoadSize() {
        return S7.GetDIntAt(this.Buffer, 5);
    }

    public int LocalData() {
        return S7.GetWordAt(this.Buffer, 29);
    }

    public int SBBLength() {
        return S7.GetWordAt(this.Buffer, 25);
    }

    public int Checksum() {
        return S7.GetWordAt(this.Buffer, 59);
    }

    public int Version() {
        return this.Buffer[57];
    }

    public Date CodeDate() {
        long BlockDate = S7.GetWordAt(this.Buffer, 17) * 86400000L + this.DeltaMilliSecs;
        return new Date(BlockDate);
    }

    public Date IntfDate() {
        long BlockDate = S7.GetWordAt(this.Buffer, 23) * 86400000L + this.DeltaMilliSecs;
        return new Date(BlockDate);
    }

    public String Author() {
        return S7.GetStringAt(this.Buffer, 33, 8);
    }

    public String Family() {
        return S7.GetStringAt(this.Buffer, 41, 8);
    }

    public String Header() {
        return S7.GetStringAt(this.Buffer, 49, 8);
    }

}
