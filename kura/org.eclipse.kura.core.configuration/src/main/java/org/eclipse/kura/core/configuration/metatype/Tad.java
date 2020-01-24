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

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.xml.namespace.QName;

import org.eclipse.kura.configuration.metatype.AD;
import org.eclipse.kura.configuration.metatype.Option;
import org.eclipse.kura.configuration.metatype.Scalar;
import org.w3c.dom.Element;

/**
 * <p>
 * Java class for Tad complex type.
 *
 * <p>
 * The following schema fragment specifies the expected content contained within this class.
 *
 * <pre>
 * &lt;complexType name="Tad">
 *   &lt;complexContent>
 *     &lt;restriction base="{http://www.w3.org/2001/XMLSchema}anyType">
 *       &lt;sequence>
 *         &lt;element name="Option" type="{http://www.osgi.org/xmlns/metatype/v1.2.0}Toption" maxOccurs="unbounded" minOccurs="0"/>
 *         &lt;any processContents='lax' namespace='##other' maxOccurs="unbounded" minOccurs="0"/>
 *       &lt;/sequence>
 *       &lt;attribute name="name" type="{http://www.w3.org/2001/XMLSchema}string" />
 *       &lt;attribute name="description" type="{http://www.w3.org/2001/XMLSchema}string" />
 *       &lt;attribute name="id" use="required" type="{http://www.w3.org/2001/XMLSchema}string" />
 *       &lt;attribute name="type" use="required" type="{http://www.osgi.org/xmlns/metatype/v1.2.0}Tscalar" />
 *       &lt;attribute name="cardinality" type="{http://www.w3.org/2001/XMLSchema}int" default="0" />
 *       &lt;attribute name="min" type="{http://www.w3.org/2001/XMLSchema}string" />
 *       &lt;attribute name="max" type="{http://www.w3.org/2001/XMLSchema}string" />
 *       &lt;attribute name="default" type="{http://www.w3.org/2001/XMLSchema}string" />
 *       &lt;attribute name="required" type="{http://www.w3.org/2001/XMLSchema}boolean" default="true" />
 *       &lt;anyAttribute/>
 *     &lt;/restriction>
 *   &lt;/complexContent>
 * &lt;/complexType>
 * </pre>
 *
 *
 */

public class Tad implements AD {

    protected List<Toption> option;
    protected List<Object> any;
    protected String name;
    protected String description;
    protected String id;
    protected Tscalar type;
    protected Integer cardinality;
    protected String min;
    protected String max;
    protected String _default;
    protected Boolean required;
    private final Map<QName, String> otherAttributes = new HashMap<>();

    /**
     * Gets the value of the option property.
     *
     * <p>
     * This accessor method returns a reference to the live list,
     * not a snapshot. Therefore any modification you make to the
     * returned list will be present inside the JAXB object.
     * This is why there is not a <CODE>set</CODE> method for the option property.
     *
     * <p>
     * For example, to add a new item, do as follows:
     *
     * <pre>
     * getOption().add(newItem);
     * </pre>
     *
     *
     * <p>
     * Objects of the following type(s) are allowed in the list
     * {@link Toption }
     *
     *
     */
    @Override
    @SuppressWarnings("unchecked")
    public List<Option> getOption() {
        if (this.option == null) {
            this.option = new ArrayList<>();
        }
        return (List<Option>) (List<?>) this.option;
    }

    public void setOption(Toption o) {
        if (this.option == null) {
            this.option = new ArrayList<>();
        }
        this.option.add(o);
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
     * Gets the value of the type property.
     *
     * @return
     *         possible object is
     *         {@link Tscalar }
     *
     */
    @Override
    public Scalar getType() {
        return Scalar.valueOf(this.type.name());
    }

    /**
     * Sets the value of the type property.
     *
     * @param value
     *                  allowed object is
     *                  {@link Tscalar }
     *
     */
    public void setType(Tscalar value) {
        this.type = value;
    }

    /**
     * Gets the value of the cardinality property.
     *
     * @return
     *         possible object is
     *         {@link Integer }
     *
     */
    @Override
    public int getCardinality() {
        if (this.cardinality == null) {
            return 0;
        } else {
            return this.cardinality;
        }
    }

    /**
     * Sets the value of the cardinality property.
     *
     * @param value
     *                  allowed object is
     *                  {@link Integer }
     *
     */
    public void setCardinality(Integer value) {
        this.cardinality = value;
    }

    /**
     * Gets the value of the min property.
     *
     * @return
     *         possible object is
     *         {@link String }
     *
     */
    @Override
    public String getMin() {
        return this.min;
    }

    /**
     * Sets the value of the min property.
     *
     * @param value
     *                  allowed object is
     *                  {@link String }
     *
     */
    public void setMin(String value) {
        this.min = value;
    }

    /**
     * Gets the value of the max property.
     *
     * @return
     *         possible object is
     *         {@link String }
     *
     */
    @Override
    public String getMax() {
        return this.max;
    }

    /**
     * Sets the value of the max property.
     *
     * @param value
     *                  allowed object is
     *                  {@link String }
     *
     */
    public void setMax(String value) {
        this.max = value;
    }

    /**
     * Gets the value of the default property.
     *
     * @return
     *         possible object is
     *         {@link String }
     *
     */
    @Override
    public String getDefault() {
        return this._default;
    }

    /**
     * Sets the value of the default property.
     *
     * @param value
     *                  allowed object is
     *                  {@link String }
     *
     */
    public void setDefault(String value) {
        this._default = value;
    }

    /**
     * Gets the value of the required property.
     *
     * @return
     *         possible object is
     *         {@link Boolean }
     *
     */
    @Override
    public boolean isRequired() {
        if (this.required == null) {
            return true;
        } else {
            return this.required;
        }
    }

    /**
     * Sets the value of the required property.
     *
     * @param value
     *                  allowed object is
     *                  {@link Boolean }
     *
     */
    public void setRequired(Boolean value) {
        this.required = value;
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
