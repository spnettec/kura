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
package org.eclipse.kura.core.configuration;

import java.util.List;
import java.util.Map;
import java.util.ResourceBundle;

import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.metatype.AD;
import org.eclipse.kura.configuration.metatype.OCD;
import org.eclipse.kura.configuration.metatype.Option;
import org.eclipse.kura.core.configuration.metatype.Tad;
import org.eclipse.kura.core.configuration.metatype.Ticon;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.eclipse.kura.core.configuration.metatype.Toption;
import org.eclipse.kura.core.configuration.metatype.Tscalar;
import org.eclipse.kura.core.configuration.util.ComponentUtil;

public class ComponentConfigurationImpl implements ComponentConfiguration {

    protected String pid;

    protected Tocd definition;

    protected Map<String, Object> properties;

    /**
     * Default constructor. Does not initialize any of the fields.
     */
    // Required by JAXB
    public ComponentConfigurationImpl() {
    }

    public ComponentConfigurationImpl(String pid, Tocd definition, Map<String, Object> properties) {
        super();
        this.pid = pid;
        this.definition = definition;
        this.properties = properties;
    }

    @Override
    public String getPid() {
        return this.pid;
    }

    @Override
    public Tocd getDefinition() {
        return this.definition;
    }

    @Override
    public Map<String, Object> getConfigurationProperties() {
        return this.properties;
    }

    public void setPid(String pid) {
        this.pid = pid;
    }

    public void setDefinition(Tocd definition) {
        this.definition = definition;
    }

    public void setProperties(Map<String, Object> properties) {
        this.properties = properties;
    }

    @Override
    public String toString() {
        return "ComponentConfigurationImpl [pid=" + this.pid + ", definition=" + this.definition + ", properties="
                + this.properties + "]";
    }

    @Override
    public OCD getLocalizedDefinition(String locale) {
        if (this.definition == null) {
            return null;
        }
        ResourceBundle rb = ComponentUtil.getResourceBundle(this.definition.getLocalization(), locale,
                this.definition.getLocaleUrls());
        if (rb == null) {
            return this.definition;
        }
        Tocd localeDefinition = new Tocd();
        localeDefinition.setName(ComponentUtil.getLocalized(rb, this.definition.getName()));
        localeDefinition.setDescription(ComponentUtil.getLocalized(rb, this.definition.getDescription()));
        this.definition.getIcon().forEach(icon -> localeDefinition.setIcon((Ticon) icon));
        this.definition.getAny().forEach(any -> localeDefinition.setAny(any));
        localeDefinition.setId(this.definition.getId());
        List<AD> ads = this.definition.getAD();
        for (AD ad : ads) {
            Tad localeTad = new Tad();
            Tad tad = (Tad) ad;
            if (tad.getOption() != null) {
                for (Option option : tad.getOption()) {
                    Toption localeTotion = new Toption();
                    Toption toption = (Toption) option;
                    toption.getAny().forEach(any -> localeTotion.setAny(any));
                    localeTotion.setLabel(ComponentUtil.getLocalized(rb, toption.getLabel()));
                    localeTotion.setValue(toption.getValue());
                    localeTad.setOption(localeTotion);
                }
            }
            localeTad.setName(ComponentUtil.getLocalized(rb, tad.getName()));
            localeTad.setDescription(ComponentUtil.getLocalized(rb, tad.getDescription()));
            localeTad.setCardinality(tad.getCardinality());
            localeTad.setDefault(tad.getDefault());
            localeTad.setId(tad.getId());
            localeTad.setMax(tad.getMax());
            localeTad.setMin(tad.getMin());
            localeTad.setRequired(tad.isRequired());
            localeTad.setType(Tscalar.valueOf(tad.getType().name()));
            localeDefinition.addAD(localeTad);
        }
        return localeDefinition;
    }

}
