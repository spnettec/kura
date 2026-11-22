package org.eclipse.kura.internal.useradmin.store;

import static org.junit.jupiter.api.Assertions.*;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.Arrays;
import java.util.Collections;

import org.apache.felix.useradmin.RoleFactory;
import org.apache.felix.useradmin.impl.AuthorizationImpl;
import org.apache.felix.useradmin.impl.RoleRepository;
import org.junit.jupiter.api.Test;
import org.osgi.service.useradmin.Group;
import org.osgi.service.useradmin.Role;
import org.osgi.service.useradmin.User;

class ReadOnlyRoleRepositoryStoreTest {
    Map<String, Object> config() {
        User user = (User) RoleFactory.createRole(Role.USER, "alice");
        user.getProperties().put("email", "owned@example.test");
        user.getCredentials().put("proof", new byte[] { 1, 2, 3 });
        Group group = (Group) RoleFactory.createRole(Role.GROUP, "admin-permission");
        group.addMember(user);
        return Map.of("roles.config", "[]", "users.config", "[" + RoleSerializer.serializeRole(user) + "]",
                "groups.config", "[" + RoleSerializer.serializeRole(group) + "]");
    }

    ReadOnlyRoleRepositoryStore store() {
        var store = new ReadOnlyRoleRepositoryStore(); store.update(config()); return store;
    }

    @Test void actualFelixRepositoryPreservesCredentialFilterAndPermissionReads() throws Exception {
        var store = store(); var repository = new RoleRepository(store);
        User user = (User) repository.getRoleByName("alice");
        assertTrue(user.hasCredential("proof", new byte[] { 1, 2, 3 }));
        assertFalse(user.hasCredential("proof", new byte[] { 9 }));
        assertEquals(1, store.getRoles("(email=owned@example.test)").length);
        var authorization = new AuthorizationImpl(user, repository);
        assertTrue(authorization.hasRole("admin-permission"));
        assertFalse(authorization.hasRole("ungranted"));
        assertNull(store.getRoleByName("admin"));
    }

    @Test void actualFelixWrappersCannotMutatePropertiesCredentialsMembershipOrRoles() throws Exception {
        var store = store(); var repository = new RoleRepository(store);
        User user = (User) repository.getRoleByName("alice");
        Group group = (Group) repository.getRoleByName("admin-permission");
        assertThrows(IllegalStateException.class, () -> user.getProperties().put("email", "changed"));
        assertThrows(IllegalStateException.class, () -> user.getProperties().remove("email"));
        assertThrows(IllegalStateException.class, () -> user.getCredentials().put("proof", "changed"));
        assertThrows(IllegalStateException.class, () -> user.getCredentials().remove("proof"));
        assertThrows(IllegalStateException.class, () -> group.addMember(user));
        assertThrows(IllegalStateException.class, () -> group.addRequiredMember(user));
        assertThrows(IllegalStateException.class, () -> group.removeMember(user));
        assertThrows(RuntimeException.class, () -> repository.addRole("new", Role.USER));
        assertThrows(RuntimeException.class, () -> repository.removeRole("alice"));
        assertEquals(2, store.getRoles(null).length);
        assertTrue(user.hasCredential("proof", new byte[] { 1, 2, 3 }));
    }

    @Test void actualFelixRoleInitializationNoOpsPreserveExistingIdentityAndRejectNewPermissions() throws Exception {
        var store = store(); var repository = new RoleRepository(store);
        Role existing = store.getRoleByName("admin-permission");
        assertNull(repository.addRole("admin-permission", Role.GROUP));
        // Existing names are a no-op even when the requested type differs,
        // as with the normal store. The persisted role is never replaced.
        assertNull(repository.addRole("admin-permission", Role.USER));
        assertNull(store.removeRole("absent"));
        assertFalse(repository.removeRole("absent"));
        assertSame(existing, store.getRoleByName("admin-permission"));
        assertEquals(Role.GROUP, existing.getType());
        assertThrows(RuntimeException.class, () -> repository.addRole("new-permission", Role.GROUP));
        assertThrows(RuntimeException.class, () -> repository.removeRole("admin-permission"));
        assertEquals(2, store.getRoles(null).length);
        assertTrue(new AuthorizationImpl((User) repository.getRoleByName("alice"), repository)
                .hasRole("admin-permission"));
        store.deactivate();
        assertThrows(IllegalStateException.class, () -> store.addRole("admin-permission", Role.GROUP));
    }

    @Test void returnedCredentialArraysAndMemberArraysAreDetached() {
        var store = store(); User user = (User) store.getRoleByName("alice");
        ((byte[]) user.getCredentials().get("proof"))[0] = 99;
        byte[] viaEnumeration = (byte[]) Collections.list(user.getCredentials().elements()).get(0);
        viaEnumeration[0] = 98;
        Group group = (Group) store.getRoleByName("admin-permission");
        group.getMembers()[0] = null;
        assertEquals("alice", group.getMembers()[0].getName());
        assertTrue(user.hasCredential("proof", new byte[] { 1, 2, 3 }));
    }

    @Test void missingMalformedDuplicateAndUnknownRequiredMemberNeverUseDefaultsOrStaleRoles() throws Exception {
        for (Map<String, Object> invalid : Arrays.<Map<String, Object>>asList(
                Map.of(), Map.of("roles.config", "[]", "users.config", "invalid", "groups.config", "[]"),
                Map.of("roles.config", "[]", "users.config", "[{\"name\":\"x\"},{\"name\":\"x\"}]", "groups.config", "[]"),
                Map.of("roles.config", "[]", "users.config", "[]", "groups.config",
                        "[{\"name\":\"admin\",\"requiredMembers\":[\"missing\"]}]"),
                Map.of("roles.config", "[]", "users.config", "[{\"name\":\"x\",\"credentials\":{\"proof\":[256]}}]", "groups.config", "[]"),
                Map.of("roles.config", "[]", "users.config", "[{\"name\":\"x\",\"name\":\"y\"}]", "groups.config", "[]"))) {
            var store = store();
            var error = assertThrows(IllegalArgumentException.class, () -> store.update(invalid));
            assertEquals("Persisted identity view unavailable", error.getMessage());
            assertNull(error.getCause());
            assertEquals(0, store.getRoles(null).length);
        }
    }

    @Test void changedPersistedRolesReplacePreviousViewAndDeactivateClearsIt() throws Exception {
        var store = store();
        store.update(Map.of("roles.config", "[]", "users.config", "[]", "groups.config", "[]"));
        assertNull(store.getRoleByName("alice"));
        store.update(config()); store.deactivate();
        assertEquals(0, store.getRoles(null).length);
    }

    @Test void packagedDsIsRequiredPersistedConfigLowestPriorityAndIndependentOfCoreWriter() throws Exception {
        String xml = Files.readString(Path.of("OSGI-INF/readOnlyRoles.xml"));
        assertTrue(xml.contains("configuration-policy=\"require\""));
        assertTrue(xml.contains("configuration-pid=\"org.eclipse.kura.internal.useradmin.store.RoleRepositoryStoreImpl\""));
        assertFalse(xml.contains("<reference"));
        assertFalse(xml.contains("ConfigurableComponent"));
    }
    @Test void cmCannotRaiseReadOnlyRankAndDeactivationUnregisters() {
        var context = org.mockito.Mockito.mock(org.osgi.framework.BundleContext.class);
        var registration = org.mockito.Mockito.mock(org.osgi.framework.ServiceRegistration.class);
        org.mockito.Mockito.when(context.registerService(org.mockito.ArgumentMatchers.eq(org.apache.felix.useradmin.RoleRepositoryStore.class),
                org.mockito.ArgumentMatchers.any(org.apache.felix.useradmin.RoleRepositoryStore.class),
                org.mockito.ArgumentMatchers.any())).thenReturn(registration);
        var properties = new java.util.HashMap<String, Object>(config());
        properties.put("service.ranking", Integer.MAX_VALUE);
        var store = new ReadOnlyRoleRepositoryStore(); store.activate(context, properties);
        var captured = org.mockito.ArgumentCaptor.forClass(java.util.Dictionary.class);
        org.mockito.Mockito.verify(context).registerService(org.mockito.ArgumentMatchers.eq(org.apache.felix.useradmin.RoleRepositoryStore.class),
                org.mockito.ArgumentMatchers.same(store), captured.capture());
        assertEquals(Integer.MIN_VALUE, captured.getValue().get("service.ranking"));
        assertEquals("read-only", captured.getValue().get("identity.persistence.mode"));
        store.deactivate(); org.mockito.Mockito.verify(registration).unregister();
    }

}
