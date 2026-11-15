/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import java.lang.reflect.Array;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.function.BooleanSupplier;
import java.util.stream.Collectors;

import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ConfigurationRevisionService.Reason;
import org.eclipse.kura.configuration.ConfigurationRevisionService.Rejected;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.configuration.metatype.AD;
import org.eclipse.kura.configuration.metatype.OCD;
import org.eclipse.kura.configuration.metatype.Scalar;
import org.eclipse.kura.core.configuration.metatype.Tad;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.eclipse.kura.core.configuration.metatype.Toption;
import org.eclipse.kura.core.configuration.metatype.Tscalar;
import org.eclipse.kura.core.configuration.util.ComponentUtil;
import org.eclipse.kura.crypto.CryptoService;
import org.osgi.service.component.ComponentContext;
import org.osgi.service.metatype.AttributeDefinition;
import org.osgi.service.metatype.MetaTypeProvider;
import org.osgi.service.metatype.ObjectClassDefinition;

/** Runtime metadata retains its provider's validator and an invalidatable source generation. */
public final class ProviderDefinition extends Tocd {
    @FunctionalInterface interface Write { void run() throws KuraException; }
    static final class Source {
        final MetaTypeProvider provider;
        final String generation = UUID.randomUUID().toString();
        private final BooleanSupplier available;
        private volatile boolean active = true;
        Source(MetaTypeProvider provider) { this(provider, () -> true); }
        Source(MetaTypeProvider provider, BooleanSupplier available) { this.provider = provider; this.available = available; }
        synchronized void invalidate() { this.active = false; }
        // A read worker may inspect defaults while its caller owns the write lease.
        // Only invalidation and write admission need the source monitor; visibility
        // of the closed state must not require that caller-owned monitor.
        void requireCurrent() throws Rejected {
            if (!this.active || !this.available.getAsBoolean()) { throw new Rejected(Reason.UNSUPPORTED); }
        }
    }
    private final Source source;
    private final String pid;
    private final Map<String, AttributeDefinition> validators = new LinkedHashMap<>();
    private final Map<String, String[]> defaultValues = new HashMap<>();

    ProviderDefinition(Source source, String pid) {
        this.source = source; this.pid = pid;
        currentUnchecked();
            ObjectClassDefinition definition = source.provider.getObjectClassDefinition(pid, null);
            if (definition == null || definition.getID() == null) { throw invalidMetadata(); }
            setId(definition.getID()); setName(definition.getName()); setDescription(definition.getDescription());
            Set<String> required = new HashSet<>();
            AttributeDefinition[] requiredAttributes = definition.getAttributeDefinitions(ObjectClassDefinition.REQUIRED);
            if (requiredAttributes != null) {
                for (AttributeDefinition attribute : requiredAttributes) { required.add(attribute.getID()); }
            }
            AttributeDefinition[] attributes = definition.getAttributeDefinitions(ObjectClassDefinition.ALL);
            if (attributes != null) {
                if (attributes.length > 512) { throw invalidMetadata(); }
                for (AttributeDefinition attribute : attributes) {
                    if (attribute == null || attribute.getID() == null || this.validators.put(attribute.getID(), attribute) != null) {
                        throw invalidMetadata();
                    }
                    Tad normalized = normalize(attribute, required.contains(attribute.getID()));
                    addAD(normalized);
                    String[] defaults = attribute.getDefaultValue();
                    if (defaults != null) {
                        if (defaults.length > 256) { throw invalidMetadata(); }
                        defaults = defaults.clone();
                        for (String value : defaults) { if (value == null) { throw invalidMetadata(); } }
                        this.defaultValues.put(attribute.getID(), defaults);
                        if (attribute.getType() != AttributeDefinition.PASSWORD) { normalized.setDefault(encode(List.of(defaults), true)); }
                    }
                }
            }
            if (!this.validators.keySet().containsAll(required)) { throw invalidMetadata(); }
            currentUnchecked();
    }

    private static Tad normalize(AttributeDefinition attribute, boolean required) {
        Tad result = nativeAttribute(); result.setId(attribute.getID()); result.setName(attribute.getName());
        result.setDescription(attribute.getDescription()); result.setCardinality(attribute.getCardinality());
        result.setRequired(required); result.setType(switch (attribute.getType()) {
            case AttributeDefinition.STRING -> Tscalar.STRING; case AttributeDefinition.PASSWORD -> Tscalar.PASSWORD;
            case AttributeDefinition.BOOLEAN -> Tscalar.BOOLEAN; case AttributeDefinition.BYTE -> Tscalar.BYTE;
            case AttributeDefinition.SHORT -> Tscalar.SHORT; case AttributeDefinition.INTEGER -> Tscalar.INTEGER;
            case AttributeDefinition.LONG -> Tscalar.LONG; case AttributeDefinition.FLOAT -> Tscalar.FLOAT;
            case AttributeDefinition.DOUBLE -> Tscalar.DOUBLE; case AttributeDefinition.CHARACTER -> Tscalar.CHAR;
            default -> throw invalidMetadata();
        });
        String[] values = attribute.getOptionValues(); String[] labels = attribute.getOptionLabels();
        if (values != null) {
            if (values.length > 256 || labels == null || values.length != labels.length) { throw invalidMetadata(); }
            for (int i = 0; i < values.length; i++) {
                if (values[i] == null || labels[i] == null) { throw invalidMetadata(); }
                Toption option = new Toption(); option.setValue(values[i]); option.setLabel(labels[i]); result.setOption(option);
            }
        }
        return result;
    }

    private static Tad nativeAttribute() {
        return new Tad() {
            @Override public boolean isScalarCardinality() { return getCardinality() == 0; }
        };
    }

    String generation() throws Rejected { this.source.requireCurrent(); return this.source.generation; }

    void withSource(Write write) throws KuraException {
        synchronized (this.source) { this.source.requireCurrent(); write.run(); }
    }

    void withValidatedProperties(Map<String, Object> properties, Write write) throws KuraException {
        synchronized (this.source) {
            this.source.requireCurrent();
            for (AD attribute : getAD()) {
                Object value = properties.get(attribute.getId());
                if (value == null) {
                    if (attribute.isRequired()) { throw new Rejected(Reason.INVALID_ARGUMENT); }
                    continue;
                }
                if (!ConfigurationRevision.accepts(attribute, value)) { throw new Rejected(Reason.INVALID_ARGUMENT); }
                List<Object> elements = elements(value);
                for (Object element : elements) {
                    if (!attribute.getOption().isEmpty() && attribute.getOption().stream()
                            .noneMatch(option -> option.getValue().equals(element.toString()))) {
                        throw new Rejected(Reason.INVALID_ARGUMENT);
                    }
                }
                validate(attribute.getId(), encode(elements, attribute.getCardinality() != 0));
            }
            this.source.requireCurrent();
            write.run();
        }
    }

    private void validate(String id, String value) throws Rejected {
        try {
            String result = this.validators.get(id).validate(value);
            if (result != null && !result.isEmpty()) { throw new Rejected(Reason.INVALID_ARGUMENT); }
        } catch (Rejected e) { throw e; }
        catch (RuntimeException e) { throw new Rejected(Reason.UNSUPPORTED); }
    }

    /** Invalid defaults are omitted, as required by Meta Type; existing CM values are never replaced. */
    public Map<String, Object> defaultProperties(ComponentContext context) {
            currentUnchecked(); Map<String, Object> result = new LinkedHashMap<>();
            for (AD attribute : getAD()) {
                String[] defaults = this.defaultValues.get(attribute.getId());
                if (defaults == null) { continue; }
                try {
                    int cardinality = attribute.getCardinality();
                    if (cardinality == 0 && defaults.length != 1
                            || cardinality != 0 && defaults.length > Math.min(256L, Math.abs((long) cardinality))) { continue; }
                      if (!attribute.getOption().isEmpty() && Arrays.stream(defaults).anyMatch(value -> attribute.getOption()
                              .stream().noneMatch(option -> option.getValue().equals(value)))) { continue; }
                    validate(attribute.getId(), encode(List.of(defaults), cardinality != 0));
                    List<Object> values = new ArrayList<>();
                    for (String value : defaults) { values.add(scalar(attribute.getType(), value)); }
                    Object value;
                    if (cardinality == 0) { value = values.get(0); }
                    else if (cardinality < 0) { value = new ArrayList<>(values); }
                    else {
                        Class<?> type = scalarClass(attribute.getType()); value = Array.newInstance(type, values.size());
                        for (int i = 0; i < values.size(); i++) { Array.set(value, i, values.get(i)); }
                    }
                    result.put(attribute.getId(), value);
                } catch (Rejected | IllegalArgumentException e) { /* Do not use an invalid provider default. */ }
            }
            if (getAD().stream().anyMatch(ad -> ad.getType() == Scalar.PASSWORD && result.containsKey(ad.getId()))) {
                if (context == null) { throw invalidMetadata(); }
                var bundleContext = context.getBundleContext(); var reference = bundleContext.getServiceReference(CryptoService.class);
                if (reference == null) { throw invalidMetadata(); }
                try {
                    CryptoService crypto = bundleContext.getService(reference);
                    if (crypto == null) { throw invalidMetadata(); }
                    ComponentUtil.encryptConfigurationProperties(result, crypto);
                } finally { bundleContext.ungetService(reference); }
            }
            currentUnchecked(); return result;
    }

    OCD localized(String locale) {
            currentUnchecked(); ObjectClassDefinition localized = this.source.provider.getObjectClassDefinition(this.pid, locale);
            if (localized == null) { return this; }
            Tocd result = new Tocd(); result.setId(getId()); result.setName(localized.getName()); result.setDescription(localized.getDescription());
            Map<String, AttributeDefinition> labels = new HashMap<>();
            AttributeDefinition[] attributes = localized.getAttributeDefinitions(ObjectClassDefinition.ALL);
            if (attributes != null) { for (AttributeDefinition attribute : attributes) { labels.put(attribute.getID(), attribute); } }
            for (AD attribute : getAD()) {
                AttributeDefinition label = labels.get(attribute.getId());
                Tad copy = nativeAttribute(); copy.setId(attribute.getId()); copy.setType(Tscalar.valueOf(attribute.getType().name()));
                copy.setCardinality(attribute.getCardinality()); copy.setRequired(attribute.isRequired());
                copy.setDefault(attribute.getDefault()); copy.setName(label == null ? attribute.getName() : label.getName());
                copy.setDescription(label == null ? attribute.getDescription() : label.getDescription());
                Map<String, String> optionLabels = new HashMap<>();
                if (label != null && label.getOptionValues() != null && label.getOptionLabels() != null
                        && label.getOptionValues().length == label.getOptionLabels().length) {
                    for (int i = 0; i < label.getOptionValues().length; i++) { optionLabels.put(label.getOptionValues()[i], label.getOptionLabels()[i]); }
                }
                for (var option : attribute.getOption()) {
                    Toption converted = new Toption(); converted.setValue(option.getValue());
                    converted.setLabel(optionLabels.getOrDefault(option.getValue(), option.getLabel())); copy.setOption(converted);
                }
                result.addAD(copy);
            }
            currentUnchecked(); return result;
    }

    private void currentUnchecked() {
        try { this.source.requireCurrent(); } catch (Rejected e) { throw new IllegalStateException("Metadata source unavailable"); }
    }
    private static IllegalArgumentException invalidMetadata() { return new IllegalArgumentException("Invalid provider metadata"); }
    private static List<Object> elements(Object value) {
        if (value instanceof Collection<?> collection) { return new ArrayList<>(collection); }
        if (value.getClass().isArray()) {
            List<Object> result = new ArrayList<>(); for (int i = 0; i < Array.getLength(value); i++) { result.add(Array.get(value, i)); } return result;
        }
        return List.of(value);
    }
    private static String encode(List<?> values, boolean multiple) {
        if (!multiple) { return values.isEmpty() ? "" : values.get(0).toString(); }
        return values.stream().map(value -> {
            StringBuilder result = new StringBuilder();
            for (char ch : value.toString().toCharArray()) {
                if (ch == '\\' || ch == ',' || Character.isWhitespace(ch)) { result.append('\\'); } result.append(ch);
            }
            return result.toString();
        }).collect(Collectors.joining(","));
    }
    private static Class<?> scalarClass(Scalar type) {
        return switch (type) {
            case STRING -> String.class; case PASSWORD -> Password.class; case BOOLEAN -> Boolean.class;
            case BYTE -> Byte.class; case SHORT -> Short.class; case INTEGER -> Integer.class; case LONG -> Long.class;
            case FLOAT -> Float.class; case DOUBLE -> Double.class; case CHAR -> Character.class;
        };
    }
    private static Object scalar(Scalar type, String value) {
        return switch (type) {
            case STRING -> value; case PASSWORD -> new Password(value);
            case BOOLEAN -> { if (!value.equalsIgnoreCase("true") && !value.equalsIgnoreCase("false")) { throw invalidMetadata(); } yield Boolean.valueOf(value); }
            case BYTE -> Byte.valueOf(value); case SHORT -> Short.valueOf(value); case INTEGER -> Integer.valueOf(value);
            case LONG -> Long.valueOf(value); case FLOAT -> { float number = Float.parseFloat(value); if (!Float.isFinite(number)) { throw invalidMetadata(); } yield number; }
            case DOUBLE -> { double number = Double.parseDouble(value); if (!Double.isFinite(number)) { throw invalidMetadata(); } yield number; }
            case CHAR -> { if (value.length() != 1 || Character.isSurrogate(value.charAt(0))) { throw invalidMetadata(); } yield value.charAt(0); }
        };
    }
}
