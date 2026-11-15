/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import java.io.DataOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.lang.reflect.Array;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.Map;
import java.util.Objects;
import java.util.TreeMap;
import java.util.Vector;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ConfigurationRevisionService.Reason;
import org.eclipse.kura.configuration.ConfigurationRevisionService.Rejected;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.configuration.metatype.AD;
import org.eclipse.kura.configuration.metatype.OCD;
import org.eclipse.kura.configuration.metatype.Scalar;

/** Bounded, typed canonicalization. Never invokes an arbitrary property's toString(). */
final class ConfigurationRevision {
    private final byte[] key = new byte[32];

    ConfigurationRevision() { new SecureRandom().nextBytes(this.key); }

    /** Stored dictionaries have no editable OCD. Keep their HMAC domain separate. */
    String storedToken(String pid, boolean present, Map<String,Object> properties, long changes, long admissions)
            throws Rejected {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(this.key, "HmacSHA256"));
            DataOutputStream out = bounded(new OutputStream() {
                @Override public void write(int value) { mac.update((byte)value); }
                @Override public void write(byte[] bytes, int offset, int length) { mac.update(bytes, offset, length); }
            });
            text(out, "kura.configuration.stored.revision.v1");
            text(out, pid); out.writeBoolean(present); out.writeLong(changes); out.writeLong(admissions);
            if (properties == null || properties.size() > 512 || properties.keySet().stream().anyMatch(k -> k == null)) {
                throw unsupported();
            }
            out.writeInt(properties.size());
            for (var entry : new TreeMap<>(properties).entrySet()) {
                text(out, entry.getKey()); value(out, entry.getValue(), true);
            }
            return "stored:" + HexFormat.of().formatHex(mac.doFinal());
        } catch (IOException | GeneralSecurityException e) { throw unsupported(); }
    }

    String token(ComponentConfiguration configuration, long changes, long admissions) throws Rejected {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(this.key, "HmacSHA256"));
            DataOutputStream out = bounded(new OutputStream() {
                @Override public void write(int value) { mac.update((byte) value); }
                @Override public void write(byte[] bytes, int offset, int length) { mac.update(bytes, offset, length); }
            });
            text(out, "kura.configuration.revision.v2");
            text(out, configuration.getPid());
            out.writeLong(changes);
            out.writeLong(admissions);
              if (configuration.getDefinition() instanceof ProviderDefinition provider) {
                  text(out, "dynamic-provider"); text(out, provider.generation());
              }
            var properties = configuration.getConfigurationProperties();
            if (properties == null || properties.size() > 512 || properties.keySet().stream().anyMatch(k -> k == null)) {
                throw unsupported();
            }
            out.writeInt(properties.size());
            for (var entry : new TreeMap<>(properties).entrySet()) {
                text(out, entry.getKey()); value(out, entry.getValue(), true);
            }
            var attributes = attributes(configuration.getDefinition());
            out.writeInt(attributes.size());
            for (AD attribute : attributes.values()) {
                text(out, attribute.getId()); text(out, attribute.getType() == null ? null : attribute.getType().name());
                out.writeInt(attribute.getCardinality()); out.writeBoolean(attribute.isScalarCardinality());
                out.writeBoolean(attribute.isRequired());
                text(out, attribute.getDefault()); text(out, attribute.getMin()); text(out, attribute.getMax());
                // Options influence validation even though defaults/options are not exported to the browser.
                var options = attribute.getOption();
                if (options == null) { out.writeInt(-1); }
                else {
                    if (options.size() > 256) { throw unsupported(); }
                    out.writeInt(options.size());
                    for (var option : options) {
                        if (option == null) { throw unsupported(); }
                        text(out, option.getValue());
                    }
                }
            }
            return HexFormat.of().formatHex(mac.doFinal());
        } catch (IOException | GeneralSecurityException e) { throw unsupported(); }
    }

    static Map<String, AD> attributes(OCD definition) throws Rejected {
        Map<String, AD> result = new TreeMap<>();
        if (definition == null || definition.getAD() == null || definition.getAD().size() > 512) { throw unsupported(); }
        for (AD attribute : definition.getAD()) {
            if (attribute == null || attribute.getId() == null || result.put(attribute.getId(), attribute) != null) {
                throw unsupported();
            }
        }
        return result;
    }

    static Map<String, Object> copyPatch(Map<String, Object> patch) throws Rejected {
        if (patch == null || patch.isEmpty() || patch.size() > 64) { throw new Rejected(Reason.INVALID_ARGUMENT); }
        Map<String, Object> result = new HashMap<>();
        DataOutputStream out = bounded(OutputStream.nullOutputStream());
        for (var entry : patch.entrySet()) {
            String name = entry.getKey();
            if (name == null || name.isBlank() || name.getBytes(StandardCharsets.UTF_8).length > 512
                    || name.codePoints().anyMatch(Character::isISOControl) || entry.getValue() == null) {
                throw new Rejected(Reason.INVALID_ARGUMENT);
            }
            Object value = copy(entry.getValue(), true);
            // The token's canonicalizer also bounds values supplied by local API consumers.
            try {
                text(out, name); value(out, value, true);
            } catch (IOException e) { throw unsupported(); }
            result.put(name, value);
        }
        return result;
    }

    static Map<String, Object> copyEditProperties(Map<String, Object> properties) throws Rejected {
        if (properties == null || properties.size() > 512) { throw new Rejected(Reason.INVALID_ARGUMENT); }
        Map<String, Object> result = new HashMap<>();
        for (var entry : properties.entrySet()) {
            String name = entry.getKey();
            if (name == null || name.isBlank() || name.getBytes(StandardCharsets.UTF_8).length > 512
                    || name.codePoints().anyMatch(Character::isISOControl)) {
                throw new Rejected(Reason.INVALID_ARGUMENT);
            }
            result.put(name, copy(entry.getValue(), true));
        }
        return result;
    }

    private static Object copy(Object value, boolean container) throws Rejected {
        if (value instanceof Password password) {
            return new Password(password.getPassword() == null ? null : password.getPassword().clone());
        }
        if (value instanceof java.util.Collection<?> collection) {
            if (!container || collection.size() > 256) { throw unsupported(); }
            java.util.Collection<Object> result = value instanceof Vector<?> ? new Vector<>() : new java.util.ArrayList<>();
            for (Object item : collection) { result.add(copy(item, false)); }
            return result;
        }
        if (value != null && value.getClass().isArray()) {
            int size = Array.getLength(value);
            if (!container || size > 256) { throw unsupported(); }
            Object result = Array.newInstance(value.getClass().getComponentType(), size);
            for (int i = 0; i < size; i++) { Array.set(result, i, copy(Array.get(value, i), false)); }
            return result;
        }
        return value;
    }

    private static void value(DataOutputStream out, Object value, boolean container) throws IOException, Rejected {
        if (value == null) { out.writeByte(0); return; }
        if (value instanceof Password password) {
            out.writeByte(1);
            char[] chars = password.getPassword();
            if (chars == null) { out.writeInt(-1); }
            else {
                if (chars.length > 16384) { throw unsupported(); }
                out.writeInt(chars.length); for (char ch : chars) { out.writeChar(ch); }
            }
        } else if (value instanceof String text) { out.writeByte(2); text(out, text); }
        else if (value instanceof Boolean bool) { out.writeByte(3); out.writeBoolean(bool); }
        else if (value instanceof Byte number) { out.writeByte(4); out.writeByte(number); }
        else if (value instanceof Short number) { out.writeByte(5); out.writeShort(number); }
        else if (value instanceof Integer number) { out.writeByte(6); out.writeInt(number); }
        else if (value instanceof Long number) { out.writeByte(7); out.writeLong(number); }
        else if (value instanceof Float number && Float.isFinite(number)) { out.writeByte(8); out.writeFloat(number); }
        else if (value instanceof Double number && Double.isFinite(number)) { out.writeByte(9); out.writeDouble(number); }
        else if (value instanceof Character ch) { out.writeByte(10); out.writeChar(ch); }
        else if (container && value instanceof java.util.Collection<?> collection) {
            if (collection.size() > 256) { throw unsupported(); }
            out.writeByte(11); out.writeInt(collection.size());
            for (Object item : collection) { value(out, item, false); }
        } else if (container && value.getClass().isArray()) {
            int size = Array.getLength(value);
            if (size > 256) { throw unsupported(); }
            out.writeByte(12); text(out, value.getClass().getComponentType().getName()); out.writeInt(size);
            for (int i = 0; i < size; i++) { value(out, Array.get(value, i), false); }
        } else { throw unsupported(); }
    }

    private static void text(DataOutputStream out, String text) throws IOException, Rejected {
        if (text == null) { out.writeInt(-1); return; }
        byte[] bytes = text.getBytes(StandardCharsets.UTF_8);
        if (bytes.length > 16384) { throw unsupported(); }
        out.writeInt(bytes.length); out.write(bytes);
    }

    private static Rejected unsupported() { return new Rejected(Reason.UNSUPPORTED); }

    static Map<String, Object> overlay(Map<String, Object> current, Map<String, Object> patch) throws Rejected {
        if (current == null || current.size() > 512) { throw unsupported(); }
        Map<String, Object> merged = new HashMap<>();
        for (var entry : current.entrySet()) {
            if (entry.getKey() == null) { throw unsupported(); }
            if (entry.getValue() != null) { merged.put(entry.getKey(), copy(entry.getValue(), true)); }
        }
        merged.putAll(patch);
        if (merged.size() > 512) { throw unsupported(); }
        return merged;
    }

    static boolean accepts(AD attribute, Object value) {
        int cardinality = attribute.getCardinality();
        if (org.eclipse.kura.configuration.ConfigurationConstraints.isScalarValue(attribute, value)) {
            return scalar(attribute.getType(), value);
        }
        if (cardinality < 0 && value instanceof java.util.Collection<?> collection) {
            return collection.size() <= Math.min(256L, -(long) cardinality)
                    && collection.stream().allMatch(item -> scalar(attribute.getType(), item));
        }
        if (cardinality > 0 && value != null && value.getClass().isArray()) {
            int length = Array.getLength(value);
            if (length > Math.min(256, cardinality)) { return false; }
            for (int i = 0; i < length; i++) { if (!scalar(attribute.getType(), Array.get(value, i))) { return false; } }
            return true;
        }
        return false;
    }

    private static boolean scalar(Scalar type, Object value) {
        if (type == null || value == null) { return false; }
        return switch (type) {
            case STRING -> value instanceof String;
            case BOOLEAN -> value instanceof Boolean;
            case BYTE -> value instanceof Byte;
            case SHORT -> value instanceof Short;
            case INTEGER -> value instanceof Integer;
            case LONG -> value instanceof Long;
            case FLOAT -> value instanceof Float number && Float.isFinite(number);
            case DOUBLE -> value instanceof Double number && Double.isFinite(number);
            case CHAR -> value instanceof Character;
            case PASSWORD -> value instanceof Password password && password.getPassword() != null;
        };
    }

    static boolean sameValue(Object left, Object right) {
        if (left instanceof Password password) {
            return right instanceof Password other && java.util.Arrays.equals(password.getPassword(), other.getPassword());
        }
        if (left instanceof java.util.Collection<?> collection) {
            if (!(right instanceof java.util.Collection<?> other) || collection.size() != other.size()) { return false; }
            var leftValues = collection.iterator(); var rightValues = other.iterator();
            while (leftValues.hasNext()) { if (!sameValue(leftValues.next(), rightValues.next())) { return false; } }
            return true;
        }
        if (left != null && left.getClass().isArray()) {
            if (right == null || !right.getClass().isArray() || Array.getLength(left) != Array.getLength(right)) { return false; }
            for (int i = 0; i < Array.getLength(left); i++) {
                if (!sameValue(Array.get(left, i), Array.get(right, i))) { return false; }
            }
            return true;
        }
        return Objects.equals(left, right);
    }

    private static DataOutputStream bounded(OutputStream delegate) {
        return new DataOutputStream(new OutputStream() {
            private int remaining = 256 * 1024;
            @Override public void write(int value) throws IOException {
                if (--this.remaining < 0) { throw new IOException("revision size limit"); }
                delegate.write(value);
            }
            @Override public void write(byte[] bytes, int offset, int length) throws IOException {
                if (length > this.remaining) { throw new IOException("revision size limit"); }
                this.remaining -= length;
                delegate.write(bytes, offset, length);
            }
        });
    }
}
