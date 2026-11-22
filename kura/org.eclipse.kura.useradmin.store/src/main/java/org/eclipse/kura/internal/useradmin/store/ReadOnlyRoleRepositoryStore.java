package org.eclipse.kura.internal.useradmin.store;

import java.util.Collections;
import java.util.Dictionary;
import java.util.Enumeration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Hashtable;
import java.util.HashSet;
import java.util.Objects;

import org.apache.felix.useradmin.RoleFactory;
import org.apache.felix.useradmin.RoleRepositoryStore;
import org.osgi.framework.FrameworkUtil;
import org.osgi.framework.BundleContext;
import org.osgi.framework.ServiceRegistration;
import org.osgi.service.useradmin.Group;
import org.osgi.service.useradmin.Role;
import org.osgi.service.useradmin.User;

import com.eclipsesource.json.Json;
import com.eclipsesource.json.JsonArray;
import com.eclipsesource.json.JsonValue;

/**
 * Lowest-priority, immutable view of persisted identities, including during a
 * ConfigurationService startup gate. Never supplies defaults or writes CM.
 */
public final class ReadOnlyRoleRepositoryStore implements RoleRepositoryStore {
    private volatile Map<String, Role> roles = Map.of();

    private ServiceRegistration<RoleRepositoryStore> registration;

    public void activate(BundleContext context, Map<String, Object> properties) {
        update(properties);
        Hashtable<String, Object> serviceProperties = new Hashtable<>();
        // CM may contain service properties: it must never raise this fallback's rank.
        serviceProperties.put("service.ranking", Integer.MIN_VALUE);
        serviceProperties.put("identity.persistence.mode", "read-only");
        this.registration = context.registerService(RoleRepositoryStore.class, this, serviceProperties);
    }

    public synchronized void update(Map<String, Object> properties) {
        // A rejected update must not leave stale credentials or permissions usable.
        this.roles = Map.of();
        try {
            Map<String, Role> decoded = new LinkedHashMap<>();
            JsonArray groups = null;
            int totalCharacters = 0;
            for (String key : new String[] { "roles.config", "users.config", "groups.config" }) {
                Object value = properties.get(key);
                if (!(value instanceof String)) { throw new IllegalArgumentException(); }
                totalCharacters += ((String) value).length();
                if (totalCharacters > 2_000_000) { throw new IllegalArgumentException(); }
                JsonArray array = Json.parse((String) value).asArray();
                Class<? extends Role> type = key.equals("roles.config") ? Role.class
                        : key.equals("users.config") ? User.class : Group.class;
                for (JsonValue member : array) {
                    validateObject(member.asObject());
                    Role role = RoleSerializer.deserializeRole(type, member.asObject(), RoleFactory::createRole);
                    if (role.getName().isBlank() || decoded.putIfAbsent(role.getName(), role) != null
                            || decoded.size() > 10_000) { throw new IllegalArgumentException(); }
                }
                if (type == Group.class) { groups = array; }
            }
            for (JsonValue member : groups) {
                // The legacy decoder skips unknown members, including required ones.
                // A read-only authentication view must reject that ambiguity.
                for (String key : new String[] { "basicMembers", "requiredMembers" }) {
                    JsonValue members = member.asObject().get(key);
                    if (members != null) {
                        for (JsonValue name : members.asArray()) {
                            if (!decoded.containsKey(name.asString())) { throw new IllegalArgumentException(); }
                        }
                    }
                }
                RoleSerializer.assignMembers(member.asObject(), decoded);
            }
            Map<String, Role> frozen = new LinkedHashMap<>();
            for (Role role : decoded.values()) {
                Role wrapper = role instanceof Group ? new FrozenGroup((Group) role, frozen)
                        : role instanceof User ? new FrozenUser((User) role) : new FrozenRole(role);
                frozen.put(role.getName(), wrapper);
            }
            this.roles = Collections.unmodifiableMap(frozen);
        } catch (Exception failure) {
            // Do not log the parser exception, which can include credential JSON.
            throw new IllegalArgumentException("Persisted identity view unavailable");
        }
    }

    public void deactivate() {
        this.roles = Map.of();
        if (this.registration != null) { this.registration.unregister(); this.registration = null; }
    }

    private static void validateObject(com.eclipsesource.json.JsonObject object) {
        if (new HashSet<>(object.names()).size() != object.size()) { throw new IllegalArgumentException(); }
        for (String key : new String[] { "properties", "credentials" }) {
            JsonValue properties = object.get(key);
            if (properties == null) { continue; }
            var dictionary = properties.asObject();
            if (new HashSet<>(dictionary.names()).size() != dictionary.size()) { throw new IllegalArgumentException(); }
            for (var member : dictionary) {
                JsonValue value = member.getValue();
                if (value.isString()) { continue; }
                for (JsonValue number : value.asArray()) {
                    int b = number.asInt();
                    if (b < -128 || b > 127) { throw new IllegalArgumentException(); }
                }
            }
        }
    }

    @Override
    public Role getRoleByName(String name) { return this.roles.get(name); }

    @Override
    public Role[] getRoles(String filter) throws Exception {
        var parsed = filter == null ? null : FrameworkUtil.createFilter(filter);
        return this.roles.values().stream().filter(role -> parsed == null || parsed.match(role.getProperties()))
                .toArray(Role[]::new);
    }

    @Override
    public Role addRole(String name, int type) {
        // Felix initializers may request an already persisted role. Match the
        // normal store's null result without creating a role or emitting a change.
        if (this.roles.containsKey(name)) { return null; }
        throw readOnly();
    }

    @Override
    public Role removeRole(String name) {
        if (!this.roles.containsKey(name)) { return null; }
        throw readOnly();
    }

    private static IllegalStateException readOnly() {
        return new IllegalStateException("Persisted identity view is read-only");
    }

    private static class FrozenRole implements Role {
        final Role original;
        FrozenRole(Role original) { this.original = original; }
        @Override public String getName() { return this.original.getName(); }
        @Override public int getType() { return this.original.getType(); }
        @Override public Dictionary<String, Object> getProperties() { return frozenDictionary(this.original.getProperties()); }
        @Override public int hashCode() { return Objects.hash(getName(), getType()); }
        @Override public boolean equals(Object other) {
            return other instanceof Role && getType() == ((Role) other).getType()
                    && getName().equals(((Role) other).getName());
        }
    }

    private static class FrozenUser extends FrozenRole implements User {
        FrozenUser(User original) { super(original); }
        @Override public Dictionary<String, Object> getCredentials() {
            return frozenDictionary(((User) this.original).getCredentials());
        }
        @Override public boolean hasCredential(String key, Object value) {
            return ((User) this.original).hasCredential(key, value);
        }
    }

    private static final class FrozenGroup extends FrozenUser implements Group {
        private final Map<String, Role> frozen;
        FrozenGroup(Group original, Map<String, Role> frozen) { super(original); this.frozen = frozen; }
        @Override public boolean addMember(Role role) { throw readOnly(); }
        @Override public boolean addRequiredMember(Role role) { throw readOnly(); }
        @Override public boolean removeMember(Role role) { throw readOnly(); }
        @Override public Role[] getMembers() { return members(((Group) this.original).getMembers()); }
        @Override public Role[] getRequiredMembers() { return members(((Group) this.original).getRequiredMembers()); }
        private Role[] members(Role[] original) {
            if (original == null) { return null; }
            Role[] result = new Role[original.length];
            for (int i = 0; i < original.length; i++) {
                result[i] = this.frozen.get(original[i].getName());
                if (result[i] == null) { throw new IllegalStateException("Invalid persisted membership"); }
            }
            return result;
        }
    }

    private static Dictionary<String, Object> frozenDictionary(Dictionary<?, ?> original) {
        return new Dictionary<>() {
            @Override public int size() { return original.size(); }
            @Override public boolean isEmpty() { return original.isEmpty(); }
            @Override public Enumeration<String> keys() {
                return Collections.enumeration(Collections.list(original.keys()).stream().map(String.class::cast).toList());
            }
            @Override public Enumeration<Object> elements() {
                return Collections.enumeration(Collections.list(original.elements()).stream()
                        .map(ReadOnlyRoleRepositoryStore::copyValue).toList());
            }
            @Override public Object get(Object key) { return copyValue(original.get(key)); }
            @Override public Object put(String key, Object value) { throw readOnly(); }
            @Override public Object remove(Object key) { throw readOnly(); }
        };
    }

    private static Object copyValue(Object value) {
        return value instanceof byte[] ? ((byte[]) value).clone() : value;
    }
}
