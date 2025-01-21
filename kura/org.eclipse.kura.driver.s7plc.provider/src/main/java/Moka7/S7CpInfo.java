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
public class S7CpInfo {

    public int MaxPduLength;
    public int MaxConnections;
    public int MaxMpiRate;
    public int MaxBusRate;

    protected void Update(byte[] Src, int Pos) {
        this.MaxPduLength = S7.GetShortAt(Src, 2);
        this.MaxConnections = S7.GetShortAt(Src, 4);
        this.MaxMpiRate = S7.GetDIntAt(Src, 6);
        this.MaxBusRate = S7.GetDIntAt(Src, 10);
    }
}
