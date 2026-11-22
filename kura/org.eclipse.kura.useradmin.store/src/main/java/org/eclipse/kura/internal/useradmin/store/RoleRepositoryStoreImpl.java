/*******************************************************************************
 * Copyright (c) 2020, 2021 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.internal.useradmin.store;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.TreeMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

import org.apache.felix.useradmin.RoleFactory;
import org.apache.felix.useradmin.RoleRepositoryStore;
import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ConfigurableComponent;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.internal.useradmin.store.RoleSerializer.RoleBuilder;
import org.eclipse.kura.internal.useradmin.store.persistence.IdentityPersistence;
import org.osgi.framework.BundleContext;
import org.osgi.framework.Filter;
import org.osgi.framework.FrameworkUtil;
import org.osgi.framework.ServiceReference;
import org.osgi.service.useradmin.Group;
import org.osgi.service.useradmin.Role;
import org.osgi.service.useradmin.User;
import org.osgi.service.useradmin.UserAdmin;
import org.osgi.service.useradmin.UserAdminEvent;
import org.osgi.service.useradmin.UserAdminListener;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.eclipsesource.json.Json;
import com.eclipsesource.json.JsonArray;
import com.eclipsesource.json.JsonValue;

public class RoleRepositoryStoreImpl
        implements RoleRepositoryStore, UserAdminListener, ConfigurableComponent, IdentityPersistence {

    private static final String INTERNAL_UPDATE_ID_PROP_NAME = "internal.update.id";

    private static final Logger logger = LoggerFactory.getLogger(RoleRepositoryStoreImpl.class);

    private Map<String, Role> roles = new TreeMap<>();
    private RoleRepositoryStoreOptions options;

    private long nextUpdateId;
    private final Set<Long> updateIds = new HashSet<>();
    private final Object persistenceLock = new Object();
    private boolean committing;
    private boolean persistenceUncertain;

    private ConfigurationService configurationService;

    private final ScheduledExecutorService executorService = Executors.newSingleThreadScheduledExecutor();
    private Optional<ScheduledFuture<?>> storeTask = Optional.empty();
    private long storeGeneration;

    public void setConfigurationService(final ConfigurationService configurationService) {
        this.configurationService = configurationService;
    }

    public void activate(final Map<String, Object> properties) {
        logger.info("activating...");

        doUpdate(properties, RoleFactory::createRole);

        logger.info("activating...done");
    }

    public synchronized void update(final Map<String, Object> properties) {

        if (isSelfUpdate(properties)) {
            logger.info("Ignoring self update");
            return;
        }

        if (this.committing || this.persistenceUncertain || this.storeTask.isPresent() || !this.updateIds.isEmpty()) {
            logger.info("Ignoring update since there are uncommitted changes");
            return;
        }

        logger.info("updating...");

        final RoleBuilder roleBuilder;

        final BundleContext bundleContext = FrameworkUtil.getBundle(RoleRepositoryStoreImpl.class).getBundleContext();

        final ServiceReference<UserAdmin> userAdminRef = bundleContext.getServiceReference(UserAdmin.class);

        final UserAdmin userAdmin;

        if (userAdminRef != null) {
            userAdmin = bundleContext.getService(userAdminRef);
        } else {
            userAdmin = null;
        }

        if (userAdmin != null) {
            roleBuilder = (type, name) -> userAdmin.createRole(name, type);

            final Set<String> roleNames = new HashSet<>(this.roles.keySet());

            for (final String name : roleNames) {
                userAdmin.removeRole(name);
            }

        } else {
            roleBuilder = RoleFactory::createRole;
        }

        try {
            doUpdate(properties, roleBuilder);
        } finally {
            if (userAdmin != null) {
                bundleContext.ungetService(userAdminRef);
            }
        }

        logger.info("updating...done");
    }

    public synchronized void deactivate() {
        logger.info("deactivating...");

        this.executorService.shutdown();

        logger.info("deactivating...done");
    }

    @Override
    public synchronized Role addRole(final String name, final int type) throws Exception {

        if (this.roles.containsKey(name)) {
            return null;
        }

        final Role role = RoleFactory.createRole(type, name);

        this.roles.put(name, role);

        return role;
    }

    @Override
    public synchronized Role getRoleByName(final String name) throws Exception {
        return this.roles.get(name);
    }

    @Override
    public synchronized Role[] getRoles(final String filterString) throws Exception {

        final Optional<Filter> filter;

        if (filterString != null) {
            filter = Optional.of(FrameworkUtil.createFilter(filterString));
        } else {
            filter = Optional.empty();
        }

        final List<Role> result = new ArrayList<>();

        for (final Role role : this.roles.values()) {
            if (!filter.isPresent() || filter.get().match(role.getProperties())) {
                result.add(role);
            }
        }

        return result.toArray(new Role[result.size()]);
    }

    @Override
    public synchronized Role removeRole(final String role) throws Exception {
        return Optional.ofNullable(this.roles.remove(role)).orElse(null);
    }

    private boolean isSelfUpdate(final Map<String, Object> properties) {
        final Object id = properties.get(INTERNAL_UPDATE_ID_PROP_NAME);

        if (id instanceof Long) {
            final long updateId = (Long) id;

            if (this.updateIds.contains(updateId)) {
                this.updateIds.remove(updateId);
                return true;
            }
        }

        return false;
    }

    private long getNextUpdateId() {
        final long updateId = this.nextUpdateId++;

        this.updateIds.add(updateId);

        return updateId;
    }

    private void doUpdate(final Map<String, Object> properties, final RoleBuilder roleBuilder) {
        this.options = new RoleRepositoryStoreOptions(properties);

        try {
            this.roles = decode(this.options, roleBuilder);
        } catch (final Exception e) {
            logger.warn("failed to deserialize roles", e);
        }
    }

    private synchronized void scheduleStore() {
        if (this.persistenceUncertain || this.executorService.isShutdown()) {
            return;
        }

        if (this.storeTask.isPresent()) {
            this.storeTask.get().cancel(false);
        }

        final long generation = ++this.storeGeneration;
        this.storeTask = Optional.of(this.executorService.schedule(() -> storeScheduled(generation),
                this.options.getWriteDelayMs(), TimeUnit.MILLISECONDS));
    }

    private void storeScheduled(long generation) {
        try {
            synchronized (this.persistenceLock) {
                synchronized (this) {
                    if (generation != this.storeGeneration || this.persistenceUncertain) {
                        return;
                    }
                }
                commit(() -> {});
            }
        } catch (final Exception e) {
            logger.warn("Failed to store configuration", e);
        } finally {
            synchronized (this) {
                if (generation == this.storeGeneration) {
                    this.storeTask = Optional.empty();
                }
            }
        }
    }

    @Override
    public void commit(Change change) throws KuraException {
        synchronized (this.persistenceLock) {
            synchronized (this) {
                if (this.persistenceUncertain) {
                    throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR,
                            "The previous identity snapshot did not complete. Reload the role repository before writing.");
                }
                this.committing = true;
            }
            try {
                change.apply();
                persistCurrentRoles();
            } finally {
                synchronized (this) {
                    this.committing = false;
                }
            }
        }
    }

    private void persistCurrentRoles() throws KuraException {
        final RoleRepositoryStoreOptions newOptions;
        final Map<String, Object> properties;
        synchronized (this) {
            newOptions = serializeRoles();
            if (newOptions.equals(this.options)) {
                return;
            }
            properties = newOptions.toProperties();
            properties.put(INTERNAL_UPDATE_ID_PROP_NAME, getNextUpdateId());
        }

        // Configuration Admin can deliver the self-update while the snapshot is being saved.
        try {
            this.configurationService.updateConfiguration(RoleRepositoryStoreImpl.class.getName(), properties);
        } catch (KuraException | RuntimeException e) {
            synchronized (this) {
                // A pending UserAdmin event must not resubmit a write with an uncertain outcome.
                this.persistenceUncertain = true;
            }
            throw e;
        }
        synchronized (this) {
            this.options = newOptions;
        }
    }

    private RoleRepositoryStoreOptions serializeRoles() {
        final JsonArray rolesArray = new JsonArray();
        final JsonArray usersArray = new JsonArray();
        final JsonArray groupsArray = new JsonArray();

        for (final Role role : this.roles.values()) {
            switch (role.getType()) {
            case Role.ROLE:
                rolesArray.add(RoleSerializer.serializeRole(role));
                break;
            case Role.USER:
                usersArray.add(RoleSerializer.serializeRole(role));
                break;
            case Role.GROUP:
                groupsArray.add(RoleSerializer.serializeRole(role));
                break;
            default:
                break;
            }
        }

        return new RoleRepositoryStoreOptions(rolesArray.toString(), usersArray.toString(), groupsArray.toString(),
                this.options.getWriteDelayMs());
    }

    private final Map<String, Role> decode(final RoleRepositoryStoreOptions options, final RoleBuilder roleBuilder)
            throws DeserializationException {
        try {
            final Map<String, Role> result = new TreeMap<>();

            decode(Json.parse(options.getRolesConfig()).asArray(), Role.class, result, roleBuilder);
            decode(Json.parse(options.getUsersConfig()).asArray(), User.class, result, roleBuilder);

            final JsonArray groups = Json.parse(options.getGroupsConfig()).asArray();

            decode(groups, Group.class, result, roleBuilder);

            for (final JsonValue member : groups) {
                RoleSerializer.assignMembers(member.asObject(), result);
            }

            return result;

        } catch (final DeserializationException e) {
            throw e;
        } catch (final Exception e) {
            throw new DeserializationException("failed to deserialize role repository", e);
        }

    }

    private void decode(final JsonArray array, final Class<? extends Role> classz, final Map<String, Role> target,
            final RoleBuilder roleBuilder) throws DeserializationException {
        for (final JsonValue member : array) {
            final Role role = RoleSerializer.deserializeRole(classz, member.asObject(), roleBuilder);
            target.put(role.getName(), role);
        }
    }

    @Override
    public void roleChanged(UserAdminEvent arg0) {
        logger.debug("received event");
        scheduleStore();
    }
}
