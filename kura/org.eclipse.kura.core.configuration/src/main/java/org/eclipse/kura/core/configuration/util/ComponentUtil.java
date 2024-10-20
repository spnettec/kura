/*******************************************************************************
 * Copyright (c) 2011, 2022 Eurotech and/or its affiliates and others
 * 
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 * 
 * SPDX-License-Identifier: EPL-2.0
 * 
 * Contributors:
 *  Eurotech
 *  Red Hat Inc 
 *******************************************************************************/
package org.eclipse.kura.core.configuration.util;

import java.io.IOException;
import java.net.URL;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.MissingResourceException;
import java.util.PropertyResourceBundle;
import java.util.ResourceBundle;

import javax.xml.stream.FactoryConfigurationError;
import javax.xml.stream.XMLStreamException;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.configuration.metatype.AD;
import org.eclipse.kura.configuration.metatype.Designate;
import org.eclipse.kura.configuration.metatype.MetaData;
import org.eclipse.kura.configuration.metatype.OCD;
import org.eclipse.kura.configuration.metatype.Scalar;
import org.eclipse.kura.core.configuration.metatype.Tmetadata;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.eclipse.kura.core.util.IOUtil;
import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.marshalling.Unmarshaller;
import org.eclipse.kura.util.service.ServiceUtil;
import org.osgi.framework.Bundle;
import org.osgi.framework.BundleContext;
import org.osgi.framework.Constants;
import org.osgi.framework.FrameworkUtil;
import org.osgi.framework.ServiceReference;
import org.osgi.service.component.ComponentContext;
import org.osgi.service.metatype.MetaTypeInformation;
import org.osgi.service.metatype.MetaTypeService;
import org.osgi.service.metatype.ObjectClassDefinition;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Utility class to handle the loading of the meta-information
 * of a bundle or one of its Services/Components.
 */
public class ComponentUtil {

    private static final Logger logger = LoggerFactory.getLogger(ComponentUtil.class);
    private static final String OSGI_INF_METATYPE = "OSGI-INF/metatype/";

    private ComponentUtil() {
        // Do nothing...
    }

    /**
     * Returns a Map with all the MetaType Object Class Definitions contained in the bundle.
     *
     * @param ctx
     * @param bnd
     * @return
     */
    public static Map<String, Tmetadata> getMetadata(BundleContext ctx, Bundle bnd) {
        final Map<String, Tmetadata> bundleMetadata = new HashMap<>();

        final ServiceReference<MetaTypeService> ref = ctx.getServiceReference(MetaTypeService.class);
        final MetaTypeService metaTypeService = ctx.getService(ref);

        try {
            final MetaTypeInformation mti = metaTypeService.getMetaTypeInformation(bnd);
            if (mti != null) {

                final List<String> pids = new ArrayList<>();
                pids.addAll(Arrays.asList(mti.getPids()));
                pids.addAll(Arrays.asList(mti.getFactoryPids()));

                for (String pid : pids) {

                    final Tmetadata metadata;
                    try {
                        metadata = readMetadata(bnd, pid);
                        if (metadata != null) {
                            bundleMetadata.put(pid, metadata);
                        }
                    } catch (Exception e) {
                        // ignore: Metadata for the specified pid is not found
                        logger.warn("Error loading Metadata for pid " + pid, e);
                    }
                }

            }
        } finally {
            ctx.ungetService(ref);
        }

        return bundleMetadata;
    }

    /**
     * Returns the Designate for the given pid
     */
    public static Designate getDesignate(final Tmetadata metadata, final String pid) {

        if (metadata == null || pid == null) {
            return null;
        }

        final List<Designate> designates = metadata.getDesignate();
        if (designates == null) {
            return null;
        }

        for (final Designate designate : designates) {
            if (pid.equals(designate.getPid())) {
                return designate;
            }
            if (pid.equals(designate.getFactoryPid())) {
                return designate;
            }
        }

        return null;
    }

    /**
     * Returns the Designate for the given pid
     */
    public static OCD getOCD(Tmetadata metadata, String pid) {
        if (metadata.getOCD() != null && !metadata.getOCD().isEmpty()) {
            for (OCD ocd : metadata.getOCD()) {
                if (ocd.getId() != null && ocd.getId().equals(pid)) {
                    return ocd;
                }
            }
        }
        return null;
    }

    /**
     * Returns a Map with all the MetaType Object Class Definitions contained in the bundle.
     *
     * @param ctx
     * @param bnd
     * @return
     */
    public static Map<String, OCD> getObjectClassDefinition(BundleContext ctx, Bundle bnd) {
        Map<String, OCD> bundleDefaults = new HashMap<>();

        ServiceReference<MetaTypeService> ref = ctx.getServiceReference(MetaTypeService.class);
        MetaTypeService metaTypeService = ctx.getService(ref);
        MetaTypeInformation mti = metaTypeService.getMetaTypeInformation(bnd);
        if (mti != null) {

            String[] pids = mti.getPids();
            if (pids != null) {
                for (String pid : pids) {
                    OCD ocd = null;
                    try {
                        ocd = readObjectClassDefinition(bnd, pid);
                        if (ocd != null) {
                            bundleDefaults.put(pid, ocd);
                        }
                    } catch (Exception e) {
                        // ignore: OCD for the specified pid is not found
                        logger.warn("Error loading OCD for pid " + pid, e);
                    }
                }
            }
        }
        return bundleDefaults;
    }

    /**
     * Returns the ObjectClassDefinition for the provided Service pid
     * as returned by the native OSGi MetaTypeService.
     * The returned ObjectClassDefinition is a thick object tied to
     * OSGi framework which masks certain attributes of the OCD XML
     * file - like required and min/max values - but which exposes
     * business logic like the validate method for each attribute.
     *
     * @param ctx
     * @param pid
     * @return
     */
    public static ObjectClassDefinition getObjectClassDefinition(BundleContext ctx, String pid) {

        ServiceReference<MetaTypeService> ref = ctx.getServiceReference(MetaTypeService.class);
        MetaTypeService metaTypeService = ctx.getService(ref);

        for (Bundle bundle : ctx.getBundles()) {
            MetaTypeInformation mti = metaTypeService.getMetaTypeInformation(bundle);
            if (mti == null) {
                continue;
            }
            String[] pids = mti.getPids();
            for (String cPid : pids) {
                if (cPid.equals(pid)) {
                    return mti.getObjectClassDefinition(cPid, null);
                }
            }
        }
        return null;
    }

    /**
     * Returned the Tmetadata as parsed from the XML file.
     * The returned Tmetadata is just an object representation of the Metadata
     * element contained in the XML MetaData file and it does not
     * contain any extra post-processing of the loaded information.
     *
     * @param ctx
     * @param pid
     *                ID of the service whose OCD should be loaded
     * @return
     * @throws IOException
     * @throws XMLStreamException
     * @throws FactoryConfigurationError
     */
    public static Tmetadata readMetadata(Bundle bundle, String pid)
            throws IOException, KuraException, FactoryConfigurationError {
        Tmetadata metaData = null;
        StringBuilder sbMetatypeXmlName = new StringBuilder();
        sbMetatypeXmlName.append(OSGI_INF_METATYPE).append(pid).append(".xml");

        String metatypeXmlName = sbMetatypeXmlName.toString();
        String metatypeXml = IOUtil.readResource(bundle, metatypeXmlName);
        if (metatypeXml != null) {
            metaData = unmarshal(metatypeXml, Tmetadata.class);
        }
        if (metaData != null) {
            String localization = metaData.getLocalization();
            URL[] urls = findAllEntries(bundle, localization);
            metaData.setLocaleUrls(urls);
            List<OCD> ocds = metaData.getOCD();
            for (OCD ocd : ocds) {
                Tocd tocd = (Tocd) ocd;
                tocd.setLocaleUrls(urls);
                tocd.setLocalization(localization);
            }

        }
        return metaData;
    }

    public static final char LOCALE_SEP = '_';
    public static final String RESOURCE_FILE_EXT = ".properties";
    public static final char DIRECTORY_SEP = '/';
    public static final char KEY_SIGN = '%';

    private static String[] getSearchCandidates(String locale) {

        // There are seven searching candidates possible:
        // baseName +
        // "_" + language1 + "_" + country1 + "_" + variation1 + ".properties"
        // or "_" + language1 + "_" + country1 + ".properties"
        // or "_" + language1 + ".properties"
        // or "_" + language2 + "_" + country2 + "_" + variation2 + ".properties"
        // or "_" + language2 + "_" + country2 + ".properties"
        // or "_" + language2 + ".properties"
        // or "" + ".properties"
        //
        // Where language1[_country1[_variation1]] is the requested locale,
        // and language2[_country2[_variation2]] is the default locale.

        String[] searchCandidates = new String[7];

        // Candidates from passed locale:
        if (locale != null && locale.length() > 0) {
            int idx1_first = locale.indexOf(LOCALE_SEP);
            if (idx1_first == -1) {
                // locale has only language.
                searchCandidates[2] = LOCALE_SEP + locale;
            } else {
                // locale has at least language and country.
                searchCandidates[2] = LOCALE_SEP + locale.substring(0, idx1_first);
                int idx1_second = locale.indexOf(LOCALE_SEP, idx1_first + 1);
                if (idx1_second == -1) {
                    // locale just has both language and country.
                    searchCandidates[1] = LOCALE_SEP + locale;
                } else {
                    // locale has language, country, and variation all.
                    searchCandidates[1] = LOCALE_SEP + locale.substring(0, idx1_second);
                    searchCandidates[0] = LOCALE_SEP + locale;
                }
            }
        }

        // Candidates from Locale.getDefault():
        String defaultLocale = Locale.getDefault().toString();
        int idx2_first = defaultLocale.indexOf(LOCALE_SEP);
        int idx2_second = defaultLocale.indexOf(LOCALE_SEP, idx2_first + 1);
        if (idx2_second != -1) {
            // default-locale is format of [language]_[country]_variation.
            searchCandidates[3] = LOCALE_SEP + defaultLocale;
            if (searchCandidates[3].equalsIgnoreCase(searchCandidates[0])) {
                searchCandidates[3] = null;
            }
        }
        if (idx2_first != -1 && idx2_second != idx2_first + 1) {
            // default-locale is format of [language]_country[_variation].
            searchCandidates[4] = LOCALE_SEP
                    + (idx2_second == -1 ? defaultLocale : defaultLocale.substring(0, idx2_second));
            if (searchCandidates[4].equalsIgnoreCase(searchCandidates[1])) {
                searchCandidates[4] = null;
            }
        }
        if (idx2_first == -1 && defaultLocale.length() > 0) {
            // default-locale has only language.
            searchCandidates[5] = LOCALE_SEP + defaultLocale;
        } else if (idx2_first > 0) {
            // default-locale is format of language_[...].
            searchCandidates[5] = LOCALE_SEP + defaultLocale.substring(0, idx2_first);
        }
        if (searchCandidates[5] != null && searchCandidates[5].equalsIgnoreCase(searchCandidates[2])) {
            searchCandidates[5] = null;
        }

        // The final candidate.
        searchCandidates[6] = ""; //$NON-NLS-1$
        return searchCandidates;
    }

    public static ResourceBundle getResourceBundle(String localization, String locale, URL[] urls) {
        if (urls == null) {
            return null;
        }
        String[] searchCandidates = getSearchCandidates(locale);

        URL resourceUrl = getLocaleUrl(urls, searchCandidates, localization);

        if (resourceUrl != null) {
            try {
                return new PropertyResourceBundle(resourceUrl.openStream());
            } catch (IOException ioe) {
                // Exception when creating PropertyResourceBundle object.
            }
        }
        return null;
    }

    private static URL[] findAllEntries(Bundle bundle, String path) {
        path = path == null ? Constants.BUNDLE_LOCALIZATION_DEFAULT_BASENAME : path;
        String directory = "/"; //$NON-NLS-1$
        String file = "*"; //$NON-NLS-1$
        int index = path.lastIndexOf(DIRECTORY_SEP);
        if (index > 0) {
            directory = path.substring(0, index);
        }

        Enumeration<URL> entries = bundle.findEntries(directory, file, false);
        if (entries == null) {
            return new URL[0];
        }
        List<URL> list = Collections.list(entries);
        return list.toArray(new URL[list.size()]);
    }

    private static URL getLocaleUrl(URL[] urls, String[] searchCandidates, String resourceBase) {
        if (urls == null) {
            return null;
        }
        resourceBase = resourceBase == null ? Constants.BUNDLE_LOCALIZATION_DEFAULT_BASENAME : resourceBase;

        for (String searchCandidate : searchCandidates) {
            for (URL url : urls) {
                String path = url.getPath();
                if (searchCandidate != null && path.equals("/" + resourceBase + searchCandidate + RESOURCE_FILE_EXT)) {
                    return url;
                }
            }
        }

        return null;
    }

    public static String getLocalized(ResourceBundle rb, String key) {

        if (key == null) {
            return null;
        }

        if (key.charAt(0) == KEY_SIGN && key.length() > 1) {
            if (rb != null) {
                try {
                    String transfered = rb.getString(key.substring(1));
                    if (transfered != null) {
                        return transfered;
                    }
                } catch (MissingResourceException mre) {
                    // Nothing found for this key.
                }
            }
            // If no localization file available or no localized value found
            // for the key, then return the raw data without the key-sign.
            return key.substring(1);
        }
        return key;
    }

    /**
     * Returned the ObjectClassDefinition as parsed from the XML file.
     * The returned OCD is just an object representation of the OCD
     * element contained in the XML MetaData file and it does not
     * contain any extra post-processing of the loaded information.
     *
     * @param resourceUrl
     *                        Url of the MetaData XML file which needs to be loaded
     * @return
     * @throws IOException
     * @throws XMLStreamException
     * @throws FactoryConfigurationError
     */
    public static OCD readObjectClassDefinition(URL resourceUrl)
            throws IOException, FactoryConfigurationError, KuraException {
        OCD ocd = null;
        String metatypeXml = IOUtil.readResource(resourceUrl);
        if (metatypeXml != null) {
            MetaData metaData = unmarshal(metatypeXml, MetaData.class);
            if (metaData.getOCD() != null && !metaData.getOCD().isEmpty()) {
                ocd = metaData.getOCD().get(0);
            } else {
                logger.warn("Cannot find OCD for component with url: {}", resourceUrl);
            }
        }
        return ocd;
    }

    /**
     * Returned the ObjectClassDefinition as parsed from the XML file.
     * The returned OCD is just an object representation of the OCD
     * element contained in the XML MetaData file and it does not
     * contain any extra post-processing of the loaded information.
     *
     * @param pid
     *                ID of the service whose OCD should be loaded
     * @return
     * @throws IOException
     * @throws XMLStreamException
     * @throws FactoryConfigurationError
     */
    public static Tocd readObjectClassDefinition(String pid)
            throws IOException, KuraException, FactoryConfigurationError {
        Tocd ocd = null;
        StringBuilder sbMetatypeXmlName = new StringBuilder();
        sbMetatypeXmlName.append(OSGI_INF_METATYPE).append(pid).append(".xml");

        String metatypeXmlName = sbMetatypeXmlName.toString();
        String metatypeXml = IOUtil.readResource(metatypeXmlName);
        if (metatypeXml != null) {
            Tmetadata metaData = unmarshal(metatypeXml, Tmetadata.class);
            if (metaData.getOCD() != null && !metaData.getOCD().isEmpty()) {
                ocd = (Tocd) metaData.getOCD().get(0);
            } else {
                logger.warn("Cannot find OCD for component with pid: {}", pid);
            }
        }
        return ocd;
    }

    /**
     * Returned the ObjectClassDefinition as parsed from the XML file.
     * The returned OCD is just an object representation of the OCD
     * element contained in the XML MetaData file and it does not
     * contain any extra post-processing of the loaded information.
     *
     * @param ctx
     * @param pid
     *                ID of the service whose OCD should be loaded
     * @return
     * @throws IOException
     * @throws XMLStreamException
     * @throws FactoryConfigurationError
     */
    public static Tocd readObjectClassDefinition(Bundle bundle, String pid)
            throws IOException, KuraException, FactoryConfigurationError {
        Tocd ocd = null;
        StringBuilder sbMetatypeXmlName = new StringBuilder();
        sbMetatypeXmlName.append(OSGI_INF_METATYPE).append(pid).append(".xml");

        String metatypeXmlName = sbMetatypeXmlName.toString();
        String metatypeXml = IOUtil.readResource(bundle, metatypeXmlName);
        if (metatypeXml != null) {
            Tmetadata metaData = unmarshal(metatypeXml, Tmetadata.class);
            if (metaData.getOCD() != null && !metaData.getOCD().isEmpty()) {
                ocd = (Tocd) metaData.getOCD().get(0);
            }
        }
        return ocd;
    }

    public static Map<String, Object> getDefaultProperties(OCD ocd, ComponentContext ctx) {
        //
        // reconcile by looping through the ocd properties
        Map<String, Object> defaults = null;
        defaults = new HashMap<>();
        if (ocd != null) {

            List<AD> attrDefs = ocd.getAD();
            if (attrDefs != null) {

                for (AD attrDef : attrDefs) {

                    String id = attrDef.getId();
                    Object defaultValue = getDefaultValue(attrDef, ctx);
                    if (defaults.get(id) == null && defaultValue != null) {
                        defaults.put(id, defaultValue);
                    }
                }
            }
        }
        return defaults;
    }

    private static Object getDefaultValue(AD attrDef, ComponentContext ctx) {
        // get the default value string from the AD
        // then split it by comma-separate list
        // keeping in mind the possible escape sequence "\,"
        String defaultValue = attrDef.getDefault();
        if (defaultValue == null || defaultValue.isEmpty()) {
            return null;
        }

        Object[] objectValues = null;
        Scalar type = attrDef.getType();
        if (type != null) {
            String[] defaultValues = StringUtil.splitValues(defaultValue);

            // convert string values into object values
            int cardinality = attrDef.getCardinality();
            objectValues = getObjectValue(type, defaultValues, ctx);
            if (objectValues != null && (cardinality == 0 || cardinality == 1 || cardinality == -1)) {

                // return one single object
                // if cardinality is 0 or abs(1)
                return objectValues[0];
            }
        } else {
            logger.warn("Unknown type for attribute {}", attrDef.getId());
        }
        return objectValues;
    }

    private static Object[] getObjectValue(Scalar type, String[] defaultValues, ComponentContext ctx) {
        List<Object> values = new ArrayList<>();
        switch (type) {
        case BOOLEAN:
            for (String value : defaultValues) {
                values.add(Boolean.valueOf(value));
            }
            return values.toArray(new Boolean[] {});

        case BYTE:
            for (String value : defaultValues) {
                values.add(Byte.valueOf(value));
            }
            return values.toArray(new Byte[] {});

        case CHAR:
            for (String value : defaultValues) {
                values.add(Character.valueOf(value.charAt(0)));
            }
            return values.toArray(new Character[] {});

        case DOUBLE:
            for (String value : defaultValues) {
                values.add(Double.valueOf(value));
            }
            return values.toArray(new Double[] {});

        case FLOAT:
            for (String value : defaultValues) {
                values.add(Float.valueOf(value));
            }
            return values.toArray(new Float[] {});

        case INTEGER:
            for (String value : defaultValues) {
                values.add(Integer.valueOf(value));
            }
            return values.toArray(new Integer[] {});

        case LONG:
            for (String value : defaultValues) {
                values.add(Long.valueOf(value));
            }
            return values.toArray(new Long[] {});

        case SHORT:
            for (String value : defaultValues) {
                values.add(Short.valueOf(value));
            }
            return values.toArray(new Short[] {});

        case PASSWORD:
            ServiceReference<CryptoService> sr = ctx.getBundleContext().getServiceReference(CryptoService.class);
            CryptoService cryptoService = ctx.getBundleContext().getService(sr);
            for (String value : defaultValues) {
                try {
                    values.add(new Password(cryptoService.encryptAes(value.toCharArray())));
                } catch (Exception e) {
                    values.add(new Password(value));
                }
            }
            return values.toArray(new Password[] {});

        case STRING:
            return defaultValues;
        }

        return null;
    }

    private static ServiceReference<Unmarshaller>[] getXmlUnmarshallers() {
        String filterString = String.format("(&(kura.service.pid=%s))",
                "org.eclipse.kura.xml.marshaller.unmarshaller.provider");
        return ServiceUtil.getServiceReferences(FrameworkUtil.getBundle(ComponentUtil.class).getBundleContext(),
                Unmarshaller.class, filterString);
    }

    private static void ungetServiceReferences(final ServiceReference<?>[] refs) {
        ServiceUtil.ungetServiceReferences(FrameworkUtil.getBundle(ComponentUtil.class).getBundleContext(), refs);
    }

    protected static <T> T unmarshal(String string, Class<T> clazz) throws KuraException {
        T result = null;
        ServiceReference<Unmarshaller>[] unmarshallerSRs = getXmlUnmarshallers();
        try {
            for (final ServiceReference<Unmarshaller> unmarshallerSR : unmarshallerSRs) {
                Unmarshaller unmarshaller = FrameworkUtil.getBundle(ComponentUtil.class).getBundleContext()
                        .getService(unmarshallerSR);
                result = unmarshaller.unmarshal(string, clazz);
            }
        } catch (Exception e) {
            logger.warn("Failed to extract persisted configuration.");
        } finally {
            ungetServiceReferences(unmarshallerSRs);
        }
        if (result == null) {
            throw new KuraException(KuraErrorCode.DECODER_ERROR, "value");
        }
        return result;
    }
}
