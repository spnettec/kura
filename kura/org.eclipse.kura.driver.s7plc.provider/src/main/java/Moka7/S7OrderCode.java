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
public class S7OrderCode {

    public int V1;
    public int V2;
    public int V3;
    protected byte[] Buffer = new byte[1024];

    protected void Update(byte[] Src, int Pos, int Size) {
        System.arraycopy(Src, Pos, this.Buffer, 0, Size);
        this.V1 = Src[Size - 3];
        this.V2 = Src[Size - 2];
        this.V3 = Src[Size - 1];
    }

    public String Code() {
        return S7.GetStringAt(this.Buffer, 2, 20);
    }
}
