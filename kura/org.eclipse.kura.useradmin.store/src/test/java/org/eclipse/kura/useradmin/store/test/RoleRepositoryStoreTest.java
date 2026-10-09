/*******************************************************************************
 * Copyright (c) 2021, 2026 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.useradmin.store.test;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.util.*;
import java.util.concurrent.*;
import java.util.function.*;

import org.apache.felix.useradmin.impl.EventDispatcher;
import org.apache.felix.useradmin.impl.RoleRepository;
import org.apache.felix.useradmin.impl.UserAdminImpl;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.internal.useradmin.store.RoleRepositoryStoreImpl;
import org.eclipse.kura.internal.useradmin.store.RoleRepositoryStoreOptions;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.MockedStatic;
import org.osgi.framework.Bundle;
import org.osgi.framework.InvalidSyntaxException;
import org.osgi.framework.ServiceReference;
import org.osgi.framework.ServiceRegistration;
import org.osgi.service.useradmin.*;

/** Actual Felix UserAdmin/roles and Kura serializer; controlled event delivery, clock and configuration boundary. */
class RoleRepositoryStoreTest {
    private RoleRepositoryStoreImpl store;
    private UserAdminImpl userAdmin;
    private final ScheduledExecutorService scheduler = mock(ScheduledExecutorService.class);
    private Map<String, Object> persisted = Map.of();
    private Runnable pendingWrite;

    @BeforeEach
    void activate() throws Exception {
        try (MockedStatic<Executors> factory = mockStatic(Executors.class, CALLS_REAL_METHODS)) {
            factory.when(Executors::newSingleThreadScheduledExecutor).thenReturn(this.scheduler);
            this.store = new RoleRepositoryStoreImpl();
        }
        when(this.scheduler.schedule(any(Runnable.class), anyLong(), any())).thenAnswer(call -> {
            assertEquals(5000L, call.getArgument(1, Long.class));
            assertEquals(TimeUnit.MILLISECONDS, call.getArgument(2));
            this.pendingWrite = call.getArgument(0);
            return mock(ScheduledFuture.class);
        });
        ConfigurationService configuration = mock(ConfigurationService.class);
        doAnswer(call -> {
            this.persisted = new HashMap<>(call.getArgument(1));
            this.store.update(this.persisted); // Normal self-update acknowledgement must not recreate roles.
            return null;
        }).when(configuration).updateConfiguration(eq(RoleRepositoryStoreImpl.class.getName()), anyMap());
        this.store.setConfigurationService(configuration);
        this.store.activate(Map.of());
        EventDispatcher dispatcher = mock(EventDispatcher.class);
        doAnswer(call -> { this.store.roleChanged(call.getArgument(0)); return null; })
                .when(dispatcher).dispatch(any(UserAdminEvent.class));
        this.userAdmin = new UserAdminImpl(new RoleRepository(this.store), dispatcher);
        ServiceRegistration registration = mock(ServiceRegistration.class);
        when(registration.getReference()).thenReturn(mock(ServiceReference.class));
        this.userAdmin.getService(mock(Bundle.class), registration);
    }

    @AfterEach
    void deactivate() {
        this.store.deactivate();
        verify(this.scheduler).shutdown();
    }

    @Test
    public void shouldHaveDefaultConfig() throws Exception {
        java.lang.reflect.Field field = RoleRepositoryStoreImpl.class.getDeclaredField("options");
        field.setAccessible(true);
        RoleRepositoryStoreOptions activated = (RoleRepositoryStoreOptions) field.get(this.store);
        final Options currentOptions = new Options(activated.toProperties());

        assertEquals("[]", currentOptions.rolesConfig);
        assertEquals("[]", currentOptions.usersConfig);
        assertEquals("[]", currentOptions.groupsConfig);
        assertEquals(5000L, currentOptions.writeDelayMs);
    }

    @Test
    public void shouldCreateEmptyUser()
            throws KuraException, InvalidSyntaxException, InterruptedException, ExecutionException, TimeoutException {
        testRoleKindConfig(k -> userAdmin.createRole("foo" + k, k), k -> "[{\"name\":\"foo" + k + "\"}]", Role.USER,
                Role.GROUP);
    }

    @SuppressWarnings("unchecked")
    @Test
    public void shouldSerializeRoleProperties()
            throws KuraException, InvalidSyntaxException, InterruptedException, ExecutionException, TimeoutException {
        testRoleKindConfig(k -> {
            final Role role = userAdmin.createRole("foo" + k, k);
            role.getProperties().put("foo", "bar");
            role.getProperties().put("boo", new byte[] { 1, 2, 3, 4 });
        }, k -> "[{\"name\":\"foo" + k + "\",\"properties\":{\"boo\":[1,2,3,4],\"foo\":\"bar\"}}]", Role.USER,
                Role.GROUP);
    }

    @Test
    public void shouldSupportRemovingRoleProperties()
            throws KuraException, InvalidSyntaxException, InterruptedException, ExecutionException, TimeoutException {
        shouldSerializeRoleProperties();

        testRoleKindConfig(k -> {
            final Role role = userAdmin.getRole("foo" + k);
            role.getProperties().remove("boo");
        }, k -> "[{\"name\":\"foo" + k + "\",\"properties\":{\"foo\":\"bar\"}}]", Role.USER, Role.GROUP);
    }

    @SuppressWarnings("unchecked")
    @Test
    public void shouldSerializeRoleCredentials()
            throws KuraException, InvalidSyntaxException, InterruptedException, ExecutionException, TimeoutException {
        testRoleKindConfig(k -> {
            final User role = (User) userAdmin.createRole("foo" + k, k);
            role.getCredentials().put("foo", "bar");
            role.getCredentials().put("boo", new byte[] { 1, 2, 3, 4 });
        }, k -> "[{\"name\":\"foo" + k + "\",\"credentials\":{\"boo\":[1,2,3,4],\"foo\":\"bar\"}}]", Role.USER,
                Role.GROUP);
    }

    @Test
    public void shouldSupportRemovingRoleCredentials()
            throws KuraException, InvalidSyntaxException, InterruptedException, ExecutionException, TimeoutException {
        shouldSerializeRoleCredentials();

        testRoleKindConfig(k -> {
            final User role = (User) userAdmin.getRole("foo" + k);
            role.getCredentials().remove("boo");
        }, k -> "[{\"name\":\"foo" + k + "\",\"credentials\":{\"foo\":\"bar\"}}]", Role.USER, Role.GROUP);
    }

    @Test
    public void shouldSupportBasicMembers()
            throws KuraException, InvalidSyntaxException, InterruptedException, ExecutionException, TimeoutException {

        final Role foo = userAdmin.createRole("foo", Role.USER);
        final Role bar = userAdmin.createRole("bar", Role.USER);
        final Role baz = userAdmin.createRole("baz", Role.GROUP);

        testRoleKindConfig(k -> {
            final Group group = (Group) userAdmin.createRole("group", Role.GROUP);
            group.addMember(foo);
            group.addMember(bar);
            group.addMember(baz);
        }, k -> "[{\"name\":\"baz\"},{\"name\":\"group\",\"basicMembers\":[\"bar\",\"baz\",\"foo\"]}]", Role.GROUP);
    }

    @Test
    public void shouldSupportRemovingBasicMembers()
            throws KuraException, InvalidSyntaxException, InterruptedException, ExecutionException, TimeoutException {

        shouldSupportBasicMembers();

        testRoleKindConfig(k -> {
            final Group group = (Group) userAdmin.getRole("group");
            group.removeMember(userAdmin.getRole("baz"));
        }, k -> "[{\"name\":\"baz\"},{\"name\":\"group\",\"basicMembers\":[\"bar\",\"foo\"]}]", Role.GROUP);
    }

    @Test
    public void shouldSupportRequiredMembers()
            throws KuraException, InvalidSyntaxException, InterruptedException, ExecutionException, TimeoutException {

        final Role foo = userAdmin.createRole("foo", Role.USER);
        final Role bar = userAdmin.createRole("bar", Role.USER);
        final Role baz = userAdmin.createRole("baz", Role.GROUP);

        testRoleKindConfig(k -> {
            final Group group = (Group) userAdmin.createRole("group", Role.GROUP);
            group.addRequiredMember(foo);
            group.addRequiredMember(bar);
            group.addRequiredMember(baz);
        }, k -> "[{\"name\":\"baz\"},{\"name\":\"group\",\"requiredMembers\":[\"bar\",\"baz\",\"foo\"]}]", Role.GROUP);
    }

    @Test
    public void shouldSupportRemovingRequiredMembers()
            throws KuraException, InvalidSyntaxException, InterruptedException, ExecutionException, TimeoutException {

        shouldSupportRequiredMembers();

        testRoleKindConfig(k -> {
            final Group group = (Group) userAdmin.getRole("group");
            group.removeMember(userAdmin.getRole("baz"));
        }, k -> "[{\"name\":\"baz\"},{\"name\":\"group\",\"requiredMembers\":[\"bar\",\"foo\"]}]", Role.GROUP);
    }

    private void testRoleKindConfig(IntConsumer setup, Function<Integer, String> expectedConfig, int... kinds) {
        for (int kind : kinds) {
            this.pendingWrite = null;
            setup.accept(kind);
            assertNotNull(this.pendingWrite, "Felix mutation did not schedule a store operation");
            this.pendingWrite.run();
            Options options = getCurrentRoleRepositoryStoreOptions();
            String actual = kind == Role.ROLE ? options.rolesConfig
                    : kind == Role.USER ? options.usersConfig : options.groupsConfig;
            assertEquals(expectedConfig.apply(kind), actual);
        }
    }

    private Options getCurrentRoleRepositoryStoreOptions() {
        return new Options(this.persisted);
    }

    private static final class Options {

        private static final String ROLES_CONFIG_ID = "roles.config";
        private static final String USERS_CONFIG_ID = "users.config";
        private static final String GROUPS_CONFIG_ID = "groups.config";
        private static final String WRITE_DELAY_MS_ID = "write.delay.ms";

        private final String rolesConfig;
        private final String usersConfig;
        private final String groupsConfig;
        private final long writeDelayMs;

        Options(final Map<String, Object> properties) {
            this.rolesConfig = (String) properties.getOrDefault(ROLES_CONFIG_ID, "[]");
            this.usersConfig = (String) properties.getOrDefault(USERS_CONFIG_ID, "[]");
            this.groupsConfig = (String) properties.getOrDefault(GROUPS_CONFIG_ID, "[]");
            this.writeDelayMs = (Long) properties.getOrDefault(WRITE_DELAY_MS_ID, 5000L);
        }
    }

}
