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
public class S7Szl {

    public int LENTHDR;
    public int N_DR;
    public int DataSize;
    public byte Data[];

    public S7Szl(int BufferSize) {
        this.Data = new byte[BufferSize];
    }

    protected void Copy(byte[] Src, int SrcPos, int DestPos, int Size) {
        System.arraycopy(Src, SrcPos, this.Data, DestPos, Size);
    }
}
