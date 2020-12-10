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
 *******************************************************************************/
//
// This file was generated by the JavaTM Architecture for XML Binding(JAXB) Reference Implementation, vhudson-jaxb-ri-2.2-147
// See <a href="http://java.sun.com/xml/jaxb">http://java.sun.com/xml/jaxb</a>
// Any modifications to this file will be lost upon recompilation of the source schema.
// Generated on: 2012.11.25 at 06:05:15 PM CET
//

package org.eclipse.kura.core.configuration.metatype;

import java.net.URL;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.xml.namespace.QName;

import org.eclipse.kura.configuration.metatype.Designate;
import org.eclipse.kura.configuration.metatype.MetaData;
import org.eclipse.kura.configuration.metatype.OCD;
import org.w3c.dom.Element;

/**
 * <p>
 * Java class for Tmetadata complex type.
 *
 * <p>
 * The following schema fragment specifies the expected content contained within this class.
 *
 * <pre>
 * &lt;complexType name="Tmetadata">
 *   &lt;complexContent>
 *     &lt;restriction base="{http://www.w3.org/2001/XMLSchema}anyType">
 *       &lt;sequence>
 *         &lt;element name="OCD" type="{http://www.osgi.org/xmlns/metatype/v1.2.0}Tocd" maxOccurs="unbounded" minOccurs="0"/>
 *         &lt;element name="Designate" type="{http://www.osgi.org/xmlns/metatype/v1.2.0}Tdesignate" maxOccurs="unbounded" minOccurs="0"/>
 *         &lt;any processContents='lax' namespace='##other' maxOccurs="unbounded" minOccurs="0"/>
 *       &lt;/sequence>
 *       &lt;attribute name="localization" type="{http://www.w3.org/2001/XMLSchema}string" />
 *       &lt;anyAttribute/>
 *     &lt;/restriction>
 *   &lt;/complexContent>
 * &lt;/complexType>
 * </pre>
 *
 *
 */

public class Tmetadata implements MetaData {

    protected List<Tocd> ocd;
    protected List<Tdesignate> designate;
    protected List<Object> any;
    protected URL[] localeUrls;

    public URL[] getLocaleUrls() {
        return this.localeUrls;
    }

    public void setLocaleUrls(URL[] localeUrls) {
        this.localeUrls = localeUrls;
    }

    protected String localization;
    private final Map<QName, String> otherAttributes = new HashMap<>();

    /**
     * Gets the value of the ocd property.
     *
     * <p>
     * This accessor method returns a reference to the live list,
     * not a snapshot. Therefore any modification you make to the
     * returned list will be present inside the JAXB object.
     * This is why there is not a <CODE>set</CODE> method for the ocd property.
     *
     * <p>
     * For example, to add a new item, do as follows:
     *
     * <pre>
     * getOCD().add(newItem);
     * </pre>
     *
     *
     * <p>
     * Objects of the following type(s) are allowed in the list
     * {@link Tocd }
     *
     *
     */
    @Override
    public List<OCD> getOCD() {
        if (this.ocd == null) {
            this.ocd = new ArrayList<>();
        }
        return new ArrayList<>(this.ocd);
    }

    public void setOCD(Tocd element) {
        if (this.ocd == null) {
            this.ocd = new ArrayList<>();
        }
        this.ocd.add(element);
    }

    /**
     * Gets the value of the designate property.
     *
     * <p>
     * This accessor method returns a reference to the live list,
     * not a snapshot. Therefore any modification you make to the
     * returned list will be present inside the JAXB object.
     * This is why there is not a <CODE>set</CODE> method for the designate property.
     *
     * <p>
     * For example, to add a new item, do as follows:
     *
     * <pre>
     * getDesignate().add(newItem);
     * </pre>
     *
     *
     * <p>
     * Objects of the following type(s) are allowed in the list
     * {@link Tdesignate }
     *
     *
     */
    @Override
    public List<Designate> getDesignate() {
        if (this.designate == null) {
            this.designate = new ArrayList<>();
        }
        return new ArrayList<>(this.designate);
    }

    public void setDesignate(Tdesignate td) {
        if (this.designate == null) {
            this.designate = new ArrayList<>();
        }
        this.designate.add(td);
    }

    /**
     * Gets the value of the any property.
     *
     * <p>
     * This accessor method returns a reference to the live list,
     * not a snapshot. Therefore any modification you make to the
     * returned list will be present inside the JAXB object.
     * This is why there is not a <CODE>set</CODE> method for the any property.
     *
     * <p>
     * For example, to add a new item, do as follows:
     *
     * <pre>
     * getAny().add(newItem);
     * </pre>
     *
     *
     * <p>
     * Objects of the following type(s) are allowed in the list
     * {@link Element }
     * {@link Object }
     *
     *
     */
    public List<Object> getAny() {
        if (this.any == null) {
            this.any = new ArrayList<>();
        }
        return this.any;
    }

    public void getAny(Object o) {
        if (this.any == null) {
            this.any = new ArrayList<>();
        }
        this.any.add(o);
    }

    /**
     * Gets the value of the localization property.
     *
     * @return
     *         possible object is
     *         {@link String }
     *
     */
    @Override
    public String getLocalization() {
        return this.localization;
    }

    /**
     * Sets the value of the localization property.
     *
     * @param value
     *                  allowed object is
     *                  {@link String }
     *
     */
    public void setLocalization(String value) {
        this.localization = value;
    }

    /**
     * Gets a map that contains attributes that aren't bound to any typed property on this class.
     *
     * <p>
     * the map is keyed by the name of the attribute and
     * the value is the string value of the attribute.
     *
     * the map returned by this method is live, and you can add new attribute
     * by updating the map directly. Because of this design, there's no setter.
     *
     *
     * @return
     *         always non-null
     */
    public Map<QName, String> getOtherAttributes() {
        return this.otherAttributes;
    }

}
