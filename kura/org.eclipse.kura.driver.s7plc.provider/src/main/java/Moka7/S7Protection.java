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

// See §33.19 of "System Software for S7-300/400 System and Standard Functions"
public class S7Protection {

    public int sch_schal;
    public int sch_par;
    public int sch_rel;
    public int bart_sch;
    public int anl_sch;

    protected void Update(byte[] Src) {
        this.sch_schal = S7.GetWordAt(Src, 2);
        this.sch_par = S7.GetWordAt(Src, 4);
        this.sch_rel = S7.GetWordAt(Src, 6);
        this.bart_sch = S7.GetWordAt(Src, 8);
        this.anl_sch = S7.GetWordAt(Src, 10);
    }
}
