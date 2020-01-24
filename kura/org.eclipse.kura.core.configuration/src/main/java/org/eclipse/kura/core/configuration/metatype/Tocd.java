/*******************************************************************************
 * Copyright (c) 2011, 2020 Eurotech and/or its affiliates
 *
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 * Contributors:
 *     Eurotech
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

import org.eclipse.kura.configuration.metatype.AD;
import org.eclipse.kura.configuration.metatype.Icon;
import org.eclipse.kura.configuration.metatype.OCD;
import org.w3c.dom.Element;

/**
 * <p>
 * Java class for Tocd complex type.
 *
 * <p>
 * The following schema fragment specifies the expected content contained within this class.
 *
 * <pre>
 * &lt;complexType name="Tocd">
 *   &lt;complexContent>
 *     &lt;restriction base="{http://www.w3.org/2001/XMLSchema}anyType">
 *       &lt;sequence>
 *         &lt;element name="AD" type="{http://www.osgi.org/xmlns/metatype/v1.2.0}Tad" maxOccurs="unbounded"/>
 *         &lt;element name="Icon" type="{http://www.osgi.org/xmlns/metatype/v1.2.0}Ticon" maxOccurs="unbounded" minOccurs="0"/>
 *         &lt;any processContents='lax' namespace='##other' maxOccurs="unbounded" minOccurs="0"/>
 *       &lt;/sequence>
 *       &lt;attribute name="name" use="required" type="{http://www.w3.org/2001/XMLSchema}string" />
 *       &lt;attribute name="description" type="{http://www.w3.org/2001/XMLSchema}string" />
 *       &lt;attribute name="id" use="required" type="{http://www.w3.org/2001/XMLSchema}string" />
 *       &lt;anyAttribute/>
 *     &lt;/restriction>
 *   &lt;/complexContent>
 * &lt;/complexType>
 * </pre>
 *
 *
 */

public class Tocd implements OCD {

    protected List<Tad> ad;
    protected List<Ticon> icon;
    protected List<Object> any;
    protected String name;
    protected String description;
    protected String id;
    protected URL[] localeUrls;
    protected String localization;

    public String getLocalization() {
        return this.localization;
    }

    public void setLocalization(String localization) {
        this.localization = localization;
    }

    public URL[] getLocaleUrls() {
        return this.localeUrls;
    }

    public void setLocaleUrls(URL[] localeUrls) {
        this.localeUrls = localeUrls;
    }

    private final Map<QName, String> otherAttributes = new HashMap<>();

    /**
     * Gets the value of the ad property.
     *
     * <p>
     * This accessor method returns a reference to the live list,
     * not a snapshot. Therefore any modification you make to the
     * returned list will be present inside the JAXB object.
     * This is why there is not a <CODE>set</CODE> method for the ad property.
     *
     * <p>
     * For example, to add a new item, do as follows:
     *
     * <pre>
     * getAD().add(newItem);
     * </pre>
     *
     *
     * <p>
     * Objects of the following type(s) are allowed in the list
     * {@link Tad }
     *
     *
     */
    @Override
    public List<AD> getAD() {
        if (this.ad == null) {
            this.ad = new ArrayList<>();
        }
        return new ArrayList<>(this.ad);
    }

    public void addAD(Tad tad) {
        if (this.ad == null) {
            this.ad = new ArrayList<>();
        }

        this.ad.add(tad);
    }

    /**
     * Gets the value of the icon property.
     *
     * <p>
     * This accessor method returns a reference to the live list,
     * not a snapshot. Therefore any modification you make to the
     * returned list will be present inside the JAXB object.
     * This is why there is not a <CODE>set</CODE> method for the icon property.
     *
     * <p>
     * For example, to add a new item, do as follows:
     *
     * <pre>
     * getIcon().add(newItem);
     * </pre>
     *
     *
     * <p>
     * Objects of the following type(s) are allowed in the list
     * {@link Ticon }
     *
     *
     */
    @Override
    public List<Icon> getIcon() {
        if (this.icon == null) {
            this.icon = new ArrayList<>();
        }
        return new ArrayList<>(this.icon);
    }

    public void setIcon(Ticon ti) {
        if (this.icon == null) {
            this.icon = new ArrayList<>();
        }
        this.icon.add(ti);
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

    public void setAny(Object o) {
        if (this.any == null) {
            this.any = new ArrayList<>();
        }
        this.any.add(o);
    }

    /**
     * Gets the value of the name property.
     *
     * @return
     *         possible object is
     *         {@link String }
     *
     */
    @Override
    public String getName() {
        return this.name;
    }

    /**
     * Sets the value of the name property.
     *
     * @param value
     *                  allowed object is
     *                  {@link String }
     *
     */
    public void setName(String value) {
        this.name = value;
    }

    /**
     * Gets the value of the description property.
     *
     * @return
     *         possible object is
     *         {@link String }
     *
     */
    @Override
    public String getDescription() {
        return this.description;
    }

    /**
     * Sets the value of the description property.
     *
     * @param value
     *                  allowed object is
     *                  {@link String }
     *
     */
    public void setDescription(String value) {
        this.description = value;
    }

    /**
     * Gets the value of the id property.
     *
     * @return
     *         possible object is
     *         {@link String }
     *
     */
    @Override
    public String getId() {
        return this.id;
    }

    /**
     * Sets the value of the id property.
     *
     * @param value
     *                  allowed object is
     *                  {@link String }
     *
     */
    public void setId(String value) {
        this.id = value;
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
