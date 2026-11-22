/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.configuration;

import java.lang.reflect.Array;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Set;

import org.eclipse.kura.configuration.metatype.AD;
import org.eclipse.kura.configuration.metatype.Option;
import org.eclipse.kura.configuration.metatype.Scalar;

/**
 * Enforces the metatype constraints used by a reviewed conditional update.
 * String and password bounds are inclusive UTF-16 code-unit lengths, matching
 * the local console. Numeric bounds are inclusive. A constraint that cannot be
 * interpreted is unsupported rather than ignored. This is not a generic editor
 * policy and does not lock direct ConfigurationAdmin writers.
 *
 * @since 1.5.0
 */
public final class ConfigurationConstraints {
    public enum Status { SATISFIED, REJECTED, UNSUPPORTED }

    static final int MAX_OPTIONS = 64;
    private static final int MAX_TEXT = 16384;
    private static final Set<String> SYSTEM = Set.of("kura.service.pid", "service.pid", "service.factoryPid",
            "service.bundleLocation", "component.id", "component.name");

    private ConfigurationConstraints() { }

    public static Status field(AD attribute) {
        return contract(attribute) == null ? Status.UNSUPPORTED : Status.SATISFIED;
    }

    public static Status value(AD attribute, Object value) {
        Contract contract = contract(attribute);
        if (contract == null || attribute.getType() == null) { return Status.UNSUPPORTED; }
        return (isScalarValue(attribute, value) ? scalar(contract, attribute.getType(), value)
                : satisfies(contract, attribute.getType(), value, attribute.getCardinality()))
                ? Status.SATISFIED : Status.REJECTED;
    }

    /** Resolve representation without confusing a one-element capacity with a scalar. */
    public static boolean isScalarValue(AD attribute, Object current) {
        int cardinality = attribute.getCardinality();
        return cardinality == 0 || ((cardinality == 1 || cardinality == -1)
                && attribute.isScalarCardinality() && !(current instanceof java.util.Collection<?>)
                && (current == null || !current.getClass().isArray()));
    }

    /** True when two definitions impose the same type, cardinality, required flag, bounds and option values. */
    public static boolean sameContract(AD left, AD right) {
        if (left == right) { return true; }
        if (left == null || right == null || left.getType() != right.getType()
                || left.getCardinality() != right.getCardinality()
                || left.isScalarCardinality() != right.isScalarCardinality() || left.isRequired() != right.isRequired()
                || !Objects.equals(left.getMin(), right.getMin()) || !Objects.equals(left.getMax(), right.getMax())) {
            return false;
        }
        return Objects.equals(optionValues(left), optionValues(right));
    }

    private static boolean satisfies(Contract contract, Scalar type, Object value, int cardinality) {
        if (cardinality == 0) { return scalar(contract, type, value); }
        long maximum = Math.abs((long) cardinality);
        if (value instanceof java.util.Collection<?> collection) {
            if (collection.size() > maximum) { return false; }
            if (contract.required && collection.isEmpty()) { return false; }
            return collection.stream().allMatch(item -> scalar(contract, type, item));
        }
        if (value != null && value.getClass().isArray()) {
            int length = Array.getLength(value);
            if (length > maximum) { return false; }
            if (contract.required && length == 0) { return false; }
            for (int i = 0; i < length; i++) { if (!scalar(contract, type, Array.get(value, i))) { return false; } }
            return true;
        }
        return false;
    }

    private static boolean scalar(Contract contract, Scalar type, Object value) {
        if (value == null) { return false; }
        String text = text(type, value);
        if (text == null) { return false; }
        if (contract.required && text.isEmpty()) { return false; }
        if (contract.min != null && compare(type, text, contract.min, false) < 0) { return false; }
        if (contract.max != null && compare(type, text, contract.max, false) > 0) { return false; }
        if (contract.options != null && contract.options.stream().noneMatch(option -> optionMatches(type, text, option))) {
            return false;
        }
        return true;
    }

    private static boolean optionMatches(Scalar type, String text, String option) {
        // String bounds describe length; option values describe the exact text.
        return type == Scalar.STRING ? text.equals(option) : compare(type, text, option, false) == 0;
    }

    private static Contract contract(AD attribute) {
        if (attribute == null || attribute.getId() == null || attribute.getType() == null
                || SYSTEM.contains(attribute.getId())) { return null; }
        Scalar type = attribute.getType();
        List<String> options = optionValues(attribute);
        if (options == null || options.size() > MAX_OPTIONS) { return null; }
        if (type == Scalar.PASSWORD && !options.isEmpty()) { return null; }
        if (attribute.getMin() != null && !bound(type, attribute.getMin())
                || attribute.getMax() != null && !bound(type, attribute.getMax())) { return null; }
        if (attribute.getMin() != null && attribute.getMax() != null
                && compare(type, attribute.getMin(), attribute.getMax(), true) > 0) { return null; }
        if (options.stream().anyMatch(option -> !literal(type, option))) { return null; }
        return new Contract(attribute.isRequired(), attribute.getMin(), attribute.getMax(),
                options.isEmpty() ? null : List.copyOf(options));
    }

    private static List<String> optionValues(AD attribute) {
        var options = attribute.getOption();
        if (options == null || options.isEmpty()) { return List.of(); }
        List<String> values = new ArrayList<>();
        for (Option option : options) {
            if (option == null || option.getValue() == null) { return null; }
            values.add(option.getValue());
        }
        return values;
    }

    private static boolean bound(Scalar type, String value) {
        if (type == Scalar.BOOLEAN || value.isBlank()) { return false; }
        if (type == Scalar.STRING || type == Scalar.PASSWORD) { return lengthBound(value); }
        if (type == Scalar.CHAR) { return value.length() == 1 && !Character.isSurrogate(value.charAt(0)); }
        return literal(type, value);
    }

    private static boolean lengthBound(String value) {
        try {
            int length = Integer.parseInt(value);
            return length >= 0 && length <= MAX_TEXT && value.equals(Integer.toString(length));
        } catch (NumberFormatException e) { return false; }
    }

    private static boolean literal(Scalar type, String value) {
        try {
            return switch (type) {
                case STRING -> value.length() <= MAX_TEXT;
                case PASSWORD -> false;
                case BOOLEAN -> value.equals("true") || value.equals("false");
                case CHAR -> value.length() == 1 && !Character.isSurrogate(value.charAt(0));
                case BYTE -> Byte.valueOf(value) != null;
                case SHORT -> Short.valueOf(value) != null;
                case INTEGER -> Integer.valueOf(value) != null;
                case LONG -> Long.valueOf(value) != null;
                case FLOAT -> { float number = Float.parseFloat(value); yield Float.isFinite(number); }
                case DOUBLE -> { double number = Double.parseDouble(value); yield Double.isFinite(number); }
            };
        } catch (NumberFormatException e) { return false; }
    }

    private static String text(Scalar type, Object value) {
        if (type == Scalar.PASSWORD && value instanceof Password password && password.getPassword() != null) {
            return new String(password.getPassword());
        }
        if (type == Scalar.BOOLEAN && value instanceof Boolean bool) { return Boolean.toString(bool); }
        if (type == Scalar.CHAR && value instanceof Character ch && !Character.isSurrogate(ch)) { return ch.toString(); }
        if (type == Scalar.STRING && value instanceof String text) { return text; }
        if (type == Scalar.BYTE && value instanceof Byte || type == Scalar.SHORT && value instanceof Short
                || type == Scalar.INTEGER && value instanceof Integer || type == Scalar.LONG && value instanceof Long) {
            return value.toString();
        }
        if (value instanceof Float number && Float.isFinite(number) && (type == Scalar.FLOAT)) { return Float.toString(number); }
        if (value instanceof Double number && Double.isFinite(number) && type == Scalar.DOUBLE) { return Double.toString(number); }
        return null;
    }

    private static int compare(Scalar type, String left, String right, boolean bounds) {
        if (type == Scalar.STRING || type == Scalar.PASSWORD) {
            int leftLength = bounds ? Integer.parseInt(left) : left.length();
            return Integer.compare(leftLength, Integer.parseInt(right));
        }
        if (type == Scalar.CHAR) { return Character.compare(left.charAt(0), right.charAt(0)); }
        if (type == Scalar.BOOLEAN) { return left.compareTo(right); }
        if (type == Scalar.FLOAT) { return Float.compare(Float.parseFloat(left), Float.parseFloat(right)); }
        if (type == Scalar.DOUBLE) { return Double.compare(Double.parseDouble(left), Double.parseDouble(right)); }
        return Long.compare(Long.parseLong(left), Long.parseLong(right));
    }

    private record Contract(boolean required, String min, String max, List<String> options) { }
}
