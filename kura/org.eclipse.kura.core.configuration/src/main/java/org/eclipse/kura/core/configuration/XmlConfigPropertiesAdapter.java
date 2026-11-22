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

import java.lang.reflect.Array;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Map.Entry;
import java.util.Set;
import java.util.Vector;

import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.core.configuration.XmlConfigPropertyAdapted.ConfigPropertyType;
import org.eclipse.kura.core.configuration.XmlConfigPropertyAdapted.Container;
import org.eclipse.kura.crypto.CryptoService;
import org.osgi.framework.BundleContext;
import org.osgi.framework.FrameworkUtil;
import org.osgi.framework.ServiceReference;

/**
 * Helper class to serialize a set of properties in XML.
 */
public class XmlConfigPropertiesAdapter {

    private final CryptoService standaloneCrypto;
    private final boolean logicalPasswords;

    public XmlConfigPropertiesAdapter() {
        this(null);
    }

    /** Explicit dependency for offline tooling; the default OSGi lookup is unchanged. */
    public XmlConfigPropertiesAdapter(CryptoService crypto) {
        this(crypto, false);
    }

    public XmlConfigPropertiesAdapter(CryptoService crypto, boolean logicalPasswords) {
        this.standaloneCrypto = crypto;
        this.logicalPasswords = logicalPasswords;
    }

    private CryptoLease crypto() {
        if (this.standaloneCrypto != null) {
            return new CryptoLease(this.standaloneCrypto, null, null);
        }
        BundleContext context = FrameworkUtil.getBundle(this.getClass()).getBundleContext();
        ServiceReference<CryptoService> reference = context.getServiceReference(CryptoService.class);
        return new CryptoLease(context.getService(reference), context, reference);
    }

    private record CryptoLease(CryptoService service, BundleContext context,
            ServiceReference<CryptoService> reference) implements AutoCloseable {
        @Override
        public void close() {
            if (this.context != null) {
                this.context.ungetService(this.reference);
            }
        }
    }

    public XmlConfigPropertiesAdapted marshal(Map<String, Object> props) throws Exception {
        List<XmlConfigPropertyAdapted> adaptedValues = new ArrayList<>();
        if (props != null) {

            for (Entry<String, Object> prop : props.entrySet()) {

                XmlConfigPropertyAdapted adaptedValue = new XmlConfigPropertyAdapted();

                String key = prop.getKey();
                adaptedValue.setName(key);

                Object value = prop.getValue();
                if (value instanceof Collection<?> || value != null && value.getClass().isArray()
                        && value.getClass().getComponentType().isPrimitive()) {
                    adaptedValues.add(marshalContainer(key, value));
                    continue;
                }
                if (value != null && value.getClass().isArray()) {
                    for (int i = 0; i < Array.getLength(value); i++) {
                        if (Array.get(value, i) == null) { throw unsupported(); }
                    }
                }
                if (value == null) {
                    adaptedValue.setType(ConfigPropertyType.STRING_TYPE);
                    adaptedValue.setValues(new String[0]);
                } else if (value instanceof String) {
                    adaptedValue.setArray(false);
                    adaptedValue.setType(ConfigPropertyType.STRING_TYPE);
                    adaptedValue.setValues(new String[] { value.toString() });
                } else if (value instanceof Long) {
                    adaptedValue.setArray(false);
                    adaptedValue.setType(ConfigPropertyType.LONG_TYPE);
                    adaptedValue.setValues(new String[] { value.toString() });
                } else if (value instanceof Double) {
                    adaptedValue.setArray(false);
                    adaptedValue.setType(ConfigPropertyType.DOUBLE_TYPE);
                    adaptedValue.setValues(new String[] { value.toString() });
                } else if (value instanceof Float) {
                    adaptedValue.setArray(false);
                    adaptedValue.setType(ConfigPropertyType.FLOAT_TYPE);
                    adaptedValue.setValues(new String[] { value.toString() });
                } else if (value instanceof Integer) {
                    adaptedValue.setArray(false);
                    adaptedValue.setType(ConfigPropertyType.INTEGER_TYPE);
                    adaptedValue.setValues(new String[] { value.toString() });
                } else if (value instanceof Byte) {
                    adaptedValue.setArray(false);
                    adaptedValue.setType(ConfigPropertyType.BYTE_TYPE);
                    adaptedValue.setValues(new String[] { value.toString() });
                } else if (value instanceof Character) {
                    adaptedValue.setArray(false);
                    adaptedValue.setType(ConfigPropertyType.CHAR_TYPE);
                    adaptedValue.setValues(new String[] { value.toString() });
                } else if (value instanceof Boolean) {
                    adaptedValue.setArray(false);
                    adaptedValue.setType(ConfigPropertyType.BOOLEAN_TYPE);
                    adaptedValue.setValues(new String[] { value.toString() });
                } else if (value instanceof Short) {
                    adaptedValue.setArray(false);
                    adaptedValue.setType(ConfigPropertyType.SHORT_TYPE);
                    adaptedValue.setValues(new String[] { value.toString() });
                } else if (value instanceof Password) {
                    try (CryptoLease lease = crypto()) {
                        CryptoService cryptoService = lease.service();
                        adaptedValue.setArray(false);
                        adaptedValue.setEncrypted(true);
                        adaptedValue.setType(ConfigPropertyType.PASSWORD_TYPE);
                        adaptedValue.setValues(new String[] { cryptoService.encodeBase64(value.toString()) });
                    }
                } else if (value instanceof String[]) {
                    adaptedValue.setArray(true);
                    adaptedValue.setType(ConfigPropertyType.STRING_TYPE);
                    adaptedValue.setValues((String[]) value);
                } else if (value instanceof Long[]) {
                    adaptedValue.setArray(true);
                    adaptedValue.setType(ConfigPropertyType.LONG_TYPE);
                    Long[] nativeValues = (Long[]) value;
                    String[] stringValues = new String[nativeValues.length];
                    for (int i = 0; i < nativeValues.length; i++) {
                        if (nativeValues[i] != null) {
                            stringValues[i] = nativeValues[i].toString();
                        }
                    }
                    adaptedValue.setValues(stringValues);
                } else if (value instanceof Double[]) {
                    adaptedValue.setArray(true);
                    adaptedValue.setType(ConfigPropertyType.DOUBLE_TYPE);
                    Double[] nativeValues = (Double[]) value;
                    String[] stringValues = new String[nativeValues.length];
                    for (int i = 0; i < nativeValues.length; i++) {
                        if (nativeValues[i] != null) {
                            stringValues[i] = nativeValues[i].toString();
                        }
                    }
                    adaptedValue.setValues(stringValues);
                } else if (value instanceof Float[]) {
                    adaptedValue.setArray(true);
                    adaptedValue.setType(ConfigPropertyType.FLOAT_TYPE);
                    Float[] nativeValues = (Float[]) value;
                    String[] stringValues = new String[nativeValues.length];
                    for (int i = 0; i < nativeValues.length; i++) {
                        if (nativeValues[i] != null) {
                            stringValues[i] = nativeValues[i].toString();
                        }
                    }
                    adaptedValue.setValues(stringValues);
                } else if (value instanceof Integer[]) {
                    adaptedValue.setArray(true);
                    adaptedValue.setType(ConfigPropertyType.INTEGER_TYPE);
                    Integer[] nativeValues = (Integer[]) value;
                    String[] stringValues = new String[nativeValues.length];
                    for (int i = 0; i < nativeValues.length; i++) {
                        if (nativeValues[i] != null) {
                            stringValues[i] = nativeValues[i].toString();
                        }
                    }
                    adaptedValue.setValues(stringValues);
                } else if (value instanceof Byte[]) {
                    adaptedValue.setArray(true);
                    adaptedValue.setType(ConfigPropertyType.BYTE_TYPE);
                    Byte[] nativeValues = (Byte[]) value;
                    String[] stringValues = new String[nativeValues.length];
                    for (int i = 0; i < nativeValues.length; i++) {
                        if (nativeValues[i] != null) {
                            stringValues[i] = nativeValues[i].toString();
                        }
                    }
                    adaptedValue.setValues(stringValues);
                } else if (value instanceof Character[]) {
                    adaptedValue.setArray(true);
                    adaptedValue.setType(ConfigPropertyType.CHAR_TYPE);
                    Character[] nativeValues = (Character[]) value;
                    String[] stringValues = new String[nativeValues.length];
                    for (int i = 0; i < nativeValues.length; i++) {
                        if (nativeValues[i] != null) {
                            stringValues[i] = nativeValues[i].toString();
                        }
                    }
                    adaptedValue.setValues(stringValues);
                } else if (value instanceof Boolean[]) {
                    adaptedValue.setArray(true);
                    adaptedValue.setType(ConfigPropertyType.BOOLEAN_TYPE);
                    Boolean[] nativeValues = (Boolean[]) value;
                    String[] stringValues = new String[nativeValues.length];
                    for (int i = 0; i < nativeValues.length; i++) {
                        if (nativeValues[i] != null) {
                            stringValues[i] = nativeValues[i].toString();
                        }
                    }
                    adaptedValue.setValues(stringValues);
                } else if (value instanceof Short[]) {
                    adaptedValue.setArray(true);
                    adaptedValue.setType(ConfigPropertyType.SHORT_TYPE);
                    Short[] nativeValues = (Short[]) value;
                    String[] stringValues = new String[nativeValues.length];
                    for (int i = 0; i < nativeValues.length; i++) {
                        if (nativeValues[i] != null) {
                            stringValues[i] = nativeValues[i].toString();
                        }
                    }
                    adaptedValue.setValues(stringValues);
                } else if (value instanceof Password[]) {
                    try (CryptoLease lease = crypto()) {
                        CryptoService cryptoService = lease.service();
                        adaptedValue.setArray(true);
                        adaptedValue.setEncrypted(true);
                        adaptedValue.setType(ConfigPropertyType.PASSWORD_TYPE);
                        Password[] nativeValues = (Password[]) value;
                        String[] stringValues = new String[nativeValues.length];
                        for (int i = 0; i < nativeValues.length; i++) {
                            if (nativeValues[i] != null) {
                                stringValues[i] = cryptoService.encodeBase64(nativeValues[i].toString());
                            }
                        }
                        adaptedValue.setValues(stringValues);
                    }
                }

                if (adaptedValue.getType() == null) { throw unsupported(); }
                adaptedValues.add(adaptedValue);
            }
        }

        XmlConfigPropertiesAdapted result = new XmlConfigPropertiesAdapted();
        result.setProperties(adaptedValues.toArray(new XmlConfigPropertyAdapted[] {}));
        return result;
    }

    private XmlConfigPropertyAdapted marshalContainer(String key, Object value) throws Exception {
        Container container;
        Class<?> type;
        Object[] elements;
        if (value instanceof Collection<?> collection) {
            elements = collection.toArray();
            type = elements.length == 0 ? String.class : elements[0] == null ? null : elements[0].getClass();
            container = value instanceof Vector<?> ? Container.VECTOR : Container.LIST;
        } else {
            elements = new Object[Array.getLength(value)];
            for (int i = 0; i < elements.length; i++) { elements[i] = Array.get(value, i); }
            type = boxed(value.getClass().getComponentType());
            container = Container.PRIMITIVE_ARRAY;
        }
        if (type == null || !Set.of(String.class, Long.class, Double.class, Float.class, Integer.class,
                Byte.class, Character.class, Boolean.class, Short.class, Password.class).contains(type)) {
            throw unsupported();
        }
        Object typed = Array.newInstance(type, elements.length);
        for (int i = 0; i < elements.length; i++) {
            if (elements[i] == null || elements[i].getClass() != type) { throw unsupported(); }
            Array.set(typed, i, elements[i]);
        }
        XmlConfigPropertyAdapted result = marshal(Map.of(key, typed)).getProperties()[0];
        result.setContainer(container);
        return result;
    }

    private static Class<?> boxed(Class<?> primitive) {
        if (primitive == boolean.class) { return Boolean.class; }
        if (primitive == byte.class) { return Byte.class; }
        if (primitive == short.class) { return Short.class; }
        if (primitive == int.class) { return Integer.class; }
        if (primitive == long.class) { return Long.class; }
        if (primitive == float.class) { return Float.class; }
        if (primitive == double.class) { return Double.class; }
        if (primitive == char.class) { return Character.class; }
        throw unsupported();
    }

    private static IllegalArgumentException unsupported() {
        return new IllegalArgumentException("Unsupported snapshot property representation");
    }

    public Map<String, Object> unmarshal(XmlConfigPropertiesAdapted adaptedPropsAdapted) throws Exception {
        Map<String, Object> properties = new HashMap<>();
        XmlConfigPropertyAdapted[] adaptedProps = adaptedPropsAdapted.getProperties();
        if (adaptedProps == null) {
            return properties;
        }
        for (XmlConfigPropertyAdapted adaptedProp : adaptedProps) {
            String propName = adaptedProp.getName();
            String[] values = adaptedProp.getValues();
            if (adaptedProp.getContainer() != null && !adaptedProp.getArray()) { throw unsupported(); }
            if (values == null || values.length == 0 && !adaptedProp.getArray()) {
                properties.put(propName, null);
                continue;
            }
            ConfigPropertyType type = adaptedProp.getType();
            if (type != null) {
                Object propvalue = null;
                if (adaptedProp.getArray() == false) {
                    switch (adaptedProp.getType()) {
                    case STRING_TYPE:
                        propvalue = values[0];
                        break;
                    case LONG_TYPE:
                        propvalue = Long.parseLong(values[0]);
                        break;
                    case DOUBLE_TYPE:
                        propvalue = Double.parseDouble(values[0]);
                        break;
                    case FLOAT_TYPE:
                        propvalue = Float.parseFloat(values[0]);
                        break;
                    case INTEGER_TYPE:
                        propvalue = Integer.parseInt(values[0]);
                        break;
                    case BYTE_TYPE:
                        propvalue = Byte.parseByte(values[0]);
                        break;
                    case CHAR_TYPE:
                        String s = values[0];
                        propvalue = Character.valueOf(s.charAt(0));
                        break;
                    case BOOLEAN_TYPE:
                        propvalue = Boolean.parseBoolean(values[0]);
                        break;
                    case SHORT_TYPE:
                        propvalue = Short.parseShort(values[0]);
                        break;
                    case PASSWORD_TYPE:
                        try (CryptoLease lease = crypto()) {
                            propvalue = decodePassword(values[0], adaptedProp.isEncrypted(), lease.service());
                        }
                        break;
                    }
                } else {
                    switch (adaptedProp.getType()) {
                    case STRING_TYPE:
                        propvalue = values;
                        break;
                    case LONG_TYPE:
                        Long[] longValues = new Long[values.length];
                        for (int i = 0; i < values.length; i++) {
                            if (values[i] != null) {
                                longValues[i] = Long.parseLong(values[i]);
                            }
                        }
                        propvalue = longValues;
                        break;
                    case DOUBLE_TYPE:
                        Double[] doubleValues = new Double[values.length];
                        for (int i = 0; i < values.length; i++) {
                            if (values[i] != null) {
                                doubleValues[i] = Double.parseDouble(values[i]);
                            }
                        }
                        propvalue = doubleValues;
                        break;
                    case FLOAT_TYPE:
                        Float[] floatValues = new Float[values.length];
                        for (int i = 0; i < values.length; i++) {
                            if (values[i] != null) {
                                floatValues[i] = Float.parseFloat(values[i]);
                            }
                        }
                        propvalue = floatValues;
                        break;
                    case INTEGER_TYPE:
                        Integer[] intValues = new Integer[values.length];
                        for (int i = 0; i < values.length; i++) {
                            if (values[i] != null) {
                                intValues[i] = Integer.parseInt(values[i]);
                            }
                        }
                        propvalue = intValues;
                        break;
                    case BYTE_TYPE:
                        Byte[] byteValues = new Byte[values.length];
                        for (int i = 0; i < values.length; i++) {
                            if (values[i] != null) {
                                byteValues[i] = Byte.parseByte(values[i]);
                            }
                        }
                        propvalue = byteValues;
                        break;
                    case CHAR_TYPE:
                        Character[] charValues = new Character[values.length];
                        for (int i = 0; i < values.length; i++) {
                            if (values[i] != null) {
                                String s = values[i];
                                charValues[i] = Character.valueOf(s.charAt(0));
                            }
                        }
                        propvalue = charValues;
                        break;
                    case BOOLEAN_TYPE:
                        Boolean[] booleanValues = new Boolean[values.length];
                        for (int i = 0; i < values.length; i++) {
                            if (values[i] != null) {
                                booleanValues[i] = Boolean.parseBoolean(values[i]);
                            }
                        }
                        propvalue = booleanValues;
                        break;
                    case SHORT_TYPE:
                        Short[] shortValues = new Short[values.length];
                        for (int i = 0; i < values.length; i++) {
                            if (values[i] != null) {
                                shortValues[i] = Short.parseShort(values[i]);
                            }
                        }
                        propvalue = shortValues;
                        break;
                    case PASSWORD_TYPE:
                        try (CryptoLease lease = crypto()) {
                            CryptoService cryptoService = lease.service();
                            Password[] pwdValues = new Password[values.length];
                            for (int i = 0; i < values.length; i++) {
                                if (values[i] != null) {
                                    pwdValues[i] = decodePassword(values[i], adaptedProp.isEncrypted(), cryptoService);
                                }
                            }
                            propvalue = pwdValues;
                        }
                        break;
                    }
                }
                properties.put(propName, restoreContainer(adaptedProp, propvalue));
            }
        }
        return properties;
    }

    private Password decodePassword(String value, boolean encrypted, CryptoService crypto) throws Exception {
        if (this.logicalPasswords) {
            return new Password(crypto.decodeBase64(value));
        }
        if (!encrypted) {
            return new LegacyLogicalPassword(value == null ? null : value.toCharArray());
        }
        try {
            return new LegacyLogicalPassword(crypto.decryptAes(value.toCharArray()));
        } catch (KuraException legacyBase64) {
            // Historical writers used Base64 for both stored CM ciphertext and logical text.
            return new Password(crypto.decodeBase64(value));
        }
    }

    /** A legacy value that the XML representation has already identified as logical. */
    static final class LegacyLogicalPassword extends Password {
        LegacyLogicalPassword(char[] value) {
            super(value);
        }
    }

    private static Object restoreContainer(XmlConfigPropertyAdapted property, Object value) {
        Container container = property.getContainer();
        if (container == null) { return value; }
        if (!(value instanceof Object[] elements)) { throw unsupported(); }
        if (container == Container.VECTOR) { return new Vector<>(Arrays.asList(elements)); }
        if (container == Container.LIST) { return new ArrayList<>(Arrays.asList(elements)); }
        Class<?> boxed = value.getClass().getComponentType();
        Class<?> primitive;
        if (boxed == Boolean.class) { primitive = boolean.class; }
        else if (boxed == Byte.class) { primitive = byte.class; }
        else if (boxed == Short.class) { primitive = short.class; }
        else if (boxed == Integer.class) { primitive = int.class; }
        else if (boxed == Long.class) { primitive = long.class; }
        else if (boxed == Float.class) { primitive = float.class; }
        else if (boxed == Double.class) { primitive = double.class; }
        else if (boxed == Character.class) { primitive = char.class; }
        else { throw unsupported(); }
        Object result = Array.newInstance(primitive, elements.length);
        for (int i = 0; i < elements.length; i++) { Array.set(result, i, elements[i]); }
        return result;
    }
}
