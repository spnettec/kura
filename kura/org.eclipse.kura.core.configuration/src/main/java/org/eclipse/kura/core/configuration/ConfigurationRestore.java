/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import java.util.ArrayList;
import java.util.Dictionary;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.core.configuration.util.CollectionsUtil;
import org.osgi.service.cm.Configuration;
import org.osgi.service.cm.ConfigurationAdmin;

/** Complete replacement of Kura-managed CM records, called only with business activation blocked. */
public final class ConfigurationRestore {
    private static final String PID = ConfigurationService.KURA_SERVICE_PID;
    private static final String FACTORY = ConfigurationAdmin.SERVICE_FACTORYPID;
    private static final String SERVICE_PID = "service.pid";
    private ConfigurationRestore() { }

    public record Applied(List<String> replaced, List<String> created, List<String> deleted) { }
    @FunctionalInterface public interface Backup {
        void persist(List<ComponentConfiguration> configurations) throws Exception;
    }

    public static Applied apply(ConfigurationAdmin admin, List<ComponentConfiguration> target, Backup backup)
            throws Exception {
        return replace(admin, target, backup, false);
    }

    /** API-level evidence, captured while all business and other CM writers remain blocked. */
    public static List<ComponentConfiguration> capture(ConfigurationAdmin admin) throws Exception {
        List<ComponentConfiguration> result = new ArrayList<>();
        for (var entry : managed(admin.listConfigurations(null)).entrySet()) {
            Map<String, Object> values = properties(entry.getValue().getProperties());
            validateProperties(values);
            result.add(new ComponentConfigurationImpl(entry.getKey(), null, values));
        }
        return List.copyOf(result);
    }

    /** Exact intended CM values, preserving ciphertext as String rather than re-decoding Password. */
    public static List<ComponentConfiguration> expected(List<ComponentConfiguration> configurations) {
        List<ComponentConfiguration> result = new ArrayList<>();
        for (var entry : target(configurations, true).entrySet()) {
            result.add(new ComponentConfigurationImpl(entry.getKey(), null,
                    properties(CollectionsUtil.mapToDictionary(applicationProperties(entry.getValue())))));
        }
        return List.copyOf(result);
    }

    /**
     * Restore the retained original API records, including an originally empty managed set.
     * Caller must authenticate both evidence sets and block business/CM writers first.
     * Only whole old/new records or their absence are accepted after a partial apply;
     * foreign edits and unknown managed identities are preserved for operator inspection.
     * The callback durably saves the pre-compensation state before any inverse mutation.
     */
    public static Applied compensate(ConfigurationAdmin admin, List<ComponentConfiguration> original,
            List<ComponentConfiguration> applied, Backup backup) throws Exception {
        Map<String, ComponentConfiguration> before = target(original, true);
        Map<String, ComponentConfiguration> after = target(applied);
        Map<String, Configuration> actual = managed(admin.listConfigurations(null));
        for (var entry : before.entrySet()) {
            ComponentConfiguration next = after.get(entry.getKey());
            // An in-place update never deletes a retained record. Its absence is external drift.
            if (next != null && Objects.equals(factory(entry.getValue()), factory(next))) {
                require(actual.containsKey(entry.getKey()));
            }
        }
        for (var entry : actual.entrySet()) {
            require(matches(entry.getValue(), before.get(entry.getKey()))
                    || matches(entry.getValue(), after.get(entry.getKey())));
        }
        return replace(admin, original, backup, true);
    }

    private static Applied replace(ConfigurationAdmin admin, List<ComponentConfiguration> target, Backup backup,
            boolean allowEmpty) throws Exception {
        Map<String, ComponentConfiguration> wanted = target(target, allowEmpty);
        Configuration[] listed = admin.listConfigurations(null);
        Map<String, Configuration> managed = managed(listed);
        // Preflight all ownership collisions before the first CM mutation.
        if (listed != null) {
            for (Configuration existing : listed) {
                if (existing.getFactoryPid() == null && wanted.containsKey(existing.getPid())
                        && !managed.containsKey(existing.getPid()) && existing.getProperties() != null) {
                    throw new IllegalStateException("Unmanaged configuration collision");
                }
            }
        }
        List<ComponentConfiguration> original = new ArrayList<>();
        for (var entry : managed.entrySet()) {
            Map<String, Object> values = properties(entry.getValue().getProperties());
            validateProperties(values);
            original.add(new ComponentConfigurationImpl(entry.getKey(), null, values));
        }
        backup.persist(List.copyOf(original));
        List<String> replaced = new ArrayList<>(), created = new ArrayList<>(), deleted = new ArrayList<>();
        // The framework gate is still closed. Type changes need delete/create, never adoption of a foreign instance.
        for (var entry : managed.entrySet()) {
            ComponentConfiguration desired = wanted.get(entry.getKey());
            String factory = desired == null ? null : factory(desired);
            if (desired == null || !Objects.equals(factory, entry.getValue().getFactoryPid())) {
                entry.getValue().delete();
                deleted.add(entry.getKey());
            }
        }
        for (var entry : wanted.entrySet()) {
            String pid = entry.getKey();
            ComponentConfiguration desired = entry.getValue();
            Configuration existing = managed.get(pid);
            if (deleted.contains(pid)) {
                existing = null;
            }
            if (existing == null) {
                existing = factory(desired) == null ? admin.getConfiguration(pid, "?")
                        : admin.createFactoryConfiguration(factory(desired), "?");
                created.add(pid);
            } else {
                replaced.add(pid);
            }
            existing.updateIfDifferent(CollectionsUtil.mapToDictionary(applicationProperties(desired)));
        }
        verify(admin, target, allowEmpty);
        return new Applied(List.copyOf(replaced), List.copyOf(created), List.copyOf(deleted));
    }

    public static void verify(ConfigurationAdmin admin, List<ComponentConfiguration> target) throws Exception {
        verify(admin, target, false);
    }

    private static void verify(ConfigurationAdmin admin, List<ComponentConfiguration> target, boolean allowEmpty)
            throws Exception {
        Map<String, ComponentConfiguration> wanted = target(target, allowEmpty);
        Map<String, Configuration> actual = managed(admin.listConfigurations(null));
        require(actual.keySet().equals(wanted.keySet()));
        for (var entry : wanted.entrySet()) {
            require(matches(actual.get(entry.getKey()), entry.getValue()));
        }
    }

    private static boolean matches(Configuration actual, ComponentConfiguration expected) {
        if (expected == null || !Objects.equals(actual.getFactoryPid(), factory(expected))) {
            return false;
        }
        Map<String, Object> values = properties(actual.getProperties());
        values.remove(SERVICE_PID);
        values.remove("service.bundleLocation");
        Map<String, Object> desired = properties(CollectionsUtil.mapToDictionary(applicationProperties(expected)));
        desired.remove(SERVICE_PID);
        desired.remove("service.bundleLocation");
        return values.keySet().equals(desired.keySet()) && desired.entrySet().stream()
                .allMatch(entry -> Objects.deepEquals(entry.getValue(), values.get(entry.getKey())));
    }

    private static Map<String, ComponentConfiguration> target(List<ComponentConfiguration> target) {
        return target(target, false);
    }
    private static Map<String, ComponentConfiguration> target(List<ComponentConfiguration> target, boolean allowEmpty) {
        require(target != null && (allowEmpty || !target.isEmpty()) && target.size() <= 4096);
        Map<String, ComponentConfiguration> result = new LinkedHashMap<>();
        for (ComponentConfiguration configuration : target) {
            require(configuration != null && validPid(configuration.getPid())
                    && configuration.getConfigurationProperties() != null);
            require(result.putIfAbsent(configuration.getPid(), configuration) == null);
            Object marker = configuration.getConfigurationProperties().get(PID);
            require(marker == null || configuration.getPid().equals(marker));
            Object factory = configuration.getConfigurationProperties().get(FACTORY);
            require(factory == null || factory instanceof String && validPid((String) factory));
            validateProperties(configuration.getConfigurationProperties());
        }
        return result;
    }

    private static Map<String, Configuration> managed(Configuration[] configurations) {
        Map<String, Configuration> result = new LinkedHashMap<>();
        if (configurations != null) {
            for (Configuration configuration : configurations) {
                Dictionary<String, Object> values = configuration.getProperties();
                Object pid = values == null ? null : values.get(PID);
                if (pid != null) {
                    require(pid instanceof String && validPid((String) pid));
                    require(result.putIfAbsent((String) pid, configuration) == null);
                    require(result.size() <= 4096);
                    if (configuration.getFactoryPid() == null) {
                        require(configuration.getPid().equals(pid));
                    }
                }
            }
        }
        return result;
    }

    private static String factory(ComponentConfiguration configuration) {
        return (String) configuration.getConfigurationProperties().get(FACTORY);
    }
    private static Map<String, Object> applicationProperties(ComponentConfiguration configuration) {
        Map<String, Object> result = new HashMap<>(configuration.getConfigurationProperties());
        result.remove(SERVICE_PID);
        result.remove("service.bundleLocation");
        result.put(PID, configuration.getPid());
        return result;
    }
    private static Map<String, Object> properties(Dictionary<String, Object> dictionary) {
        Map<String, Object> result = new HashMap<>();
        if (dictionary != null) {
            for (var keys = dictionary.keys(); keys.hasMoreElements();) {
                String key = keys.nextElement();
                result.put(key, dictionary.get(key));
            }
        }
        return result;
    }
    private static void validateProperties(Map<String, Object> values) {
        java.util.Set<String> names = new java.util.HashSet<>();
        for (var entry : values.entrySet()) {
            require(entry.getKey() != null && names.add(entry.getKey().toLowerCase(java.util.Locale.ROOT)));
            for (String reserved : List.of(PID, FACTORY, SERVICE_PID, "service.bundleLocation")) {
                require(!entry.getKey().equalsIgnoreCase(reserved) || entry.getKey().equals(reserved));
            }
            require(supported(entry.getValue()));
        }
    }
    private static boolean supported(Object value) {
        if (value == null) { return true; }
        if (value.getClass().isArray()) {
            Class<?> type = value.getClass().getComponentType();
            if (type.isArray()) { return false; }
            for (int i=0;i<java.lang.reflect.Array.getLength(value);i++) {
                Object item=java.lang.reflect.Array.get(value,i);
                if (item == null || !scalar(item)) { return false; }
            }
            return type.isPrimitive() || java.util.Set.of(String.class, Long.class, Double.class, Float.class, Integer.class,
                    Byte.class, Character.class, Boolean.class, Short.class,
                    org.eclipse.kura.configuration.Password.class).contains(type);
        }
        if (value instanceof java.util.Collection<?> collection) {
            Class<?> type = null;
            for (Object item : collection) {
                if (item == null || !scalar(item) || type != null && type != item.getClass()) { return false; }
                type = item.getClass();
            }
            return true;
        }
        return scalar(value);
    }
    private static boolean scalar(Object value) {
        return value instanceof String || value instanceof Long || value instanceof Double
                || value instanceof Float || value instanceof Integer || value instanceof Byte
                || value instanceof Character || value instanceof Boolean || value instanceof Short
                || value instanceof org.eclipse.kura.configuration.Password;
    }
    private static boolean validPid(String pid) {
        return pid != null && !pid.isBlank() && pid.length() <= 1024 && pid.chars().noneMatch(Character::isISOControl);
    }
    private static void require(boolean condition) {
        if (!condition) {
            throw new IllegalStateException("Invalid or ambiguous complete configuration restore");
        }
    }
}
