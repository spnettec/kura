/**
 * Copyright (c) 2017, 2020 Eurotech and/or its affiliates and others
 * 
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 * 
 * SPDX-License-Identifier: EPL-2.0
 * 
 * Contributors:
 *  Eurotech
 *  Amit Kumar Mondal (admin@amitinside.com)
 */
package org.eclipse.kura.internal.driver.s7plc;

import java.util.List;

import org.eclipse.kura.core.configuration.metatype.Tad;
import org.eclipse.kura.core.configuration.metatype.Toption;
import org.eclipse.kura.core.configuration.metatype.Tscalar;
import org.eclipse.kura.driver.ChannelDescriptor;
import org.eclipse.kura.util.collection.CollectionUtil;

import Moka7.S7;

/**
 * S7 PLC specific channel descriptor. The descriptor contains the following
 * attribute definition identifiers.
 *
 * <ul>
 * <li>area.no</li> denotes the Area Number
 * <li>offset</li> the offset
 * <li>byte.count</li> the number of bytes to read
 * </ul>
 */
public final class S7PlcChannelDescriptor implements ChannelDescriptor {

    public static final String S7_DB_TYPE = "s7.db.type";
    public static final String S7_ELEMENT_TYPE_ID = "s7.data.type";
    public static final String DATA_BLOCK_NO_ID = "data.block.no";
    public static final String BYTE_COUNT_ID = "byte.count";
    public static final String OFFSET_ID = "byte.offset";
    public static final String BIT_INDEX_ID = "bit.index";

    private Toption generateOption(S7PlcDataType type) {
        Toption option = new Toption();
        option.setLabel(type.name());
        option.setValue(type.name());
        return option;
    }

    private Toption generateDbTypeOption(int type) {
        Toption option = new Toption();
        option.setValue(String.valueOf(type));
        switch (type) {
        case S7.S7AreaDB:
            option.setLabel("D,DB");
            break;
        case S7.S7AreaPE:
            option.setLabel("I");
            break;
        case S7.S7AreaPA:
            option.setLabel("Q");
            break;
        case S7.S7AreaMK:
            option.setLabel("M");
            break;
        case S7.S7AreaCT:
            option.setLabel("C");
            break;
        case S7.S7AreaTM:
            option.setLabel("T");
            break;
        default:
            break;
        }

        return option;
    }

    /** {@inheritDoc} */
    @Override
    public Object getDescriptor() {
        final List<Tad> elements = CollectionUtil.newArrayList();

        final Tad dbType = new Tad();
        dbType.setId(S7_DB_TYPE);
        dbType.setName("%" + S7_DB_TYPE);
        dbType.setDescription("%s7.db.typeDesc");
        dbType.setType(Tscalar.INTEGER);
        dbType.setRequired(true);
        dbType.setDefault(String.valueOf(S7.S7AreaDB));
        dbType.setOption(generateDbTypeOption(S7.S7AreaDB));
        dbType.setOption(generateDbTypeOption(S7.S7AreaPE));
        dbType.setOption(generateDbTypeOption(S7.S7AreaPA));
        dbType.setOption(generateDbTypeOption(S7.S7AreaMK));
        dbType.setOption(generateDbTypeOption(S7.S7AreaCT));
        dbType.setOption(generateDbTypeOption(S7.S7AreaTM));
        elements.add(dbType);

        final Tad s7ElementType = new Tad();
        s7ElementType.setId(S7_ELEMENT_TYPE_ID);
        s7ElementType.setName("%" + S7_ELEMENT_TYPE_ID);
        s7ElementType.setDescription("%s7.data.typeDesc");
        s7ElementType.setType(Tscalar.STRING);
        s7ElementType.setRequired(true);
        s7ElementType.setDefault(S7PlcDataType.INT.name());

        for (S7PlcDataType t : S7PlcDataType.values()) {
            s7ElementType.setOption(generateOption(t));
        }

        elements.add(s7ElementType);

        final Tad areaNo = new Tad();
        areaNo.setId(DATA_BLOCK_NO_ID);
        areaNo.setName("%" + DATA_BLOCK_NO_ID);
        areaNo.setDescription("%data.block.noDesc");
        areaNo.setType(Tscalar.INTEGER);
        areaNo.setRequired(true);
        areaNo.setDefault("0");

        elements.add(areaNo);

        final Tad offset = new Tad();
        offset.setId(OFFSET_ID);
        offset.setName("%" + OFFSET_ID);
        offset.setDescription("%offsetDesc");
        offset.setType(Tscalar.INTEGER);
        offset.setRequired(true);
        offset.setDefault("0");

        elements.add(offset);

        final Tad byteCount = new Tad();
        byteCount.setId(BYTE_COUNT_ID);
        byteCount.setName("%" + BYTE_COUNT_ID);
        byteCount.setDescription("%byte.countDesc");
        byteCount.setType(Tscalar.INTEGER);
        byteCount.setRequired(true);
        byteCount.setDefault("0");

        elements.add(byteCount);

        final Tad bitIndex = new Tad();
        bitIndex.setId(BIT_INDEX_ID);
        bitIndex.setName("%" + BIT_INDEX_ID);
        bitIndex.setDescription("%bit.indexDesc");
        bitIndex.setType(Tscalar.INTEGER);
        bitIndex.setRequired(true);
        bitIndex.setMin("0");
        bitIndex.setMax("7");
        bitIndex.setDefault("0");

        elements.add(bitIndex);

        return elements;
    }

}
