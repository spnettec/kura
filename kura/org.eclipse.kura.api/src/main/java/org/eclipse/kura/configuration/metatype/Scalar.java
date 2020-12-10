/*******************************************************************************
 * Copyright (c) 2011, 2020 Eurotech and/or its affiliates and others
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
//
// This file was generated by the JavaTM Architecture for XML Binding(JAXB) Reference Implementation, vJAXB 2.1.10 in JDK 6
// See <a href="http://java.sun.com/xml/jaxb">http://java.sun.com/xml/jaxb</a>
// Any modifications to this file will be lost upon recompilation of the source schema.
// Generated on: 2012.10.26 at 02:11:54 PM CEST
//

package org.eclipse.kura.configuration.metatype;

/**
 * <p>
 * Java class for Tscalar.
 *
 * <p>
 * The following schema fragment specifies the expected content contained within this class.
 * <p>
 *
 * <pre>
 * &lt;simpleType name="Tscalar"&gt;
 *   &lt;restriction base="{http://www.w3.org/2001/XMLSchema}string"&gt;
 *     &lt;enumeration value="String"/&gt;
 *     &lt;enumeration value="Long"/&gt;
 *     &lt;enumeration value="Double"/&gt;
 *     &lt;enumeration value="Float"/&gt;
 *     &lt;enumeration value="Integer"/&gt;
 *     &lt;enumeration value="Byte"/&gt;
 *     &lt;enumeration value="Char"/&gt;
 *     &lt;enumeration value="Boolean"/&gt;
 *     &lt;enumeration value="Short"/&gt;
 *     &lt;enumeration value="Password"/&gt;
 *   &lt;/restriction&gt;
 * &lt;/simpleType&gt;
 * </pre>
 */
public enum Scalar {

    STRING("String"),  //
    LONG("Long"),  //
    DOUBLE("Double"),  //
    FLOAT("Float"),  //
    INTEGER("Integer"),  //
    BYTE("Byte"),  //
    CHAR("Char"),  //
    BOOLEAN("Boolean"),  //
    SHORT("Short"),  //
    PASSWORD("Password"); //

    private final String value;

    Scalar(String v) {
        this.value = v;
    }

    public String value() {
        return this.value;
    }

    public static Scalar fromValue(String v) {
        for (Scalar c : Scalar.values()) {
            if (c.value.equals(v)) {
                return c;
            }
        }
        throw new IllegalArgumentException(v);
    }

}
