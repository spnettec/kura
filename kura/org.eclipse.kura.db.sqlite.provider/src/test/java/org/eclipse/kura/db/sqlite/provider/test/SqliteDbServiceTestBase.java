/*******************************************************************************
 * Copyright (c) 2022, 2026 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 ******************************************************************************/
package org.eclipse.kura.db.sqlite.provider.test;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.Statement;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.internal.db.sqlite.provider.SqliteDbServiceImpl;
import org.eclipse.kura.internal.db.sqlite.provider.SqliteDebugShell;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.MockedStatic;

/** Actual native SQLite and Hikari pool; controlled maintenance clock and explicit service bindings. */
class SqliteDbServiceTestBase {

    @TempDir
    Path directory;
    protected final SqliteDebugShell debugShell = new SqliteDebugShell();
    protected Optional<Exception> exception = Optional.empty();
    private final List<SqliteDbServiceImpl> databases = new ArrayList<>();
    private final List<ScheduledExecutorService> executors = new ArrayList<>();
    private final List<Tick> ticks = new ArrayList<>();
    private final Map<Path, Long> fileSizes = new HashMap<>();
    private Map<String, Object> properties;
    private SqliteDbServiceImpl database;
    private record Tick(Runnable task, long initialSeconds, AtomicBoolean shutdown) { }

    protected void givenSqliteDbService(Map<String, Object> options) {
        this.properties = new HashMap<>(options);
        this.properties.put("kura.service.pid", "sqlite-test-" + UUID.randomUUID());
        this.database = new SqliteDbServiceImpl();
        this.databases.add(this.database);
        this.database.setCryptoService(mock(CryptoService.class));
        this.database.setDebugShell(this.debugShell);
        withMaintenanceClock(() -> this.database.activate(this.properties));
        this.debugShell.setDbService(this.database, this.properties);
    }

    protected void whenSqliteDbServiceIsUpdated(Map<String, Object> updates) {
        this.properties.putAll(updates);
        withMaintenanceClock(() -> this.database.updated(this.properties));
    }

    private void withMaintenanceClock(Runnable action) {
        try (MockedStatic<Executors> factory = mockStatic(Executors.class, CALLS_REAL_METHODS)) {
            factory.when(Executors::newSingleThreadScheduledExecutor).thenAnswer(call -> {
                ScheduledExecutorService executor = mock(ScheduledExecutorService.class);
                this.executors.add(executor);
                AtomicBoolean shutdown = new AtomicBoolean();
                doAnswer(ignored -> { shutdown.set(true); return null; }).when(executor).shutdown();
                when(executor.awaitTermination(anyLong(), any())).thenReturn(true);
                when(executor.scheduleWithFixedDelay(any(Runnable.class), anyLong(), anyLong(), any()))
                        .thenAnswer(schedule -> {
                            long initial = schedule.getArgument(1);
                            assertEquals(initial, schedule.getArgument(2, Long.class));
                            assertEquals(TimeUnit.SECONDS, schedule.getArgument(3));
                            this.ticks.add(new Tick(schedule.getArgument(0), initial, shutdown));
                            return mock(ScheduledFuture.class);
                        });
                return executor;
            });
            action.run();
        }
    }

    protected void whenMaintenanceIntervalElapses(long duration, TimeUnit unit) {
        for (Tick tick : this.ticks) {
            if (!tick.shutdown().get() && tick.initialSeconds() <= unit.toSeconds(duration)) {
                tick.task().run();
            }
        }
    }

    @AfterEach
    void cleanup() {
        try {
            for (SqliteDbServiceImpl service : this.databases) {
                service.deactivate();
                this.debugShell.unsetDbService(service);
            }
        } finally {
            for (ScheduledExecutorService executor : this.executors) {
                verify(executor).shutdown();
            }
        }
    }

    protected void whenAConnectionIsRequested() {
        try (Connection connection = this.database.getConnection()) {
            assertFalse(connection.isClosed());
        } catch (Exception failure) {
            this.exception = Optional.of(failure);
        }
    }

    protected void whenQueryIsPerformed(String sql) {
        try (Connection connection = this.database.getConnection(); Statement statement = connection.createStatement()) {
            statement.executeUpdate(sql);
        } catch (Exception failure) {
            this.exception = Optional.of(failure);
        }
    }

    protected void givenExecutedQuery(String sql) {
        whenQueryIsPerformed(sql);
        thenNoExceptionIsThrown();
    }

    protected void givenInitialFileSize(String path) throws IOException {
        this.fileSizes.put(Path.of(path), Files.size(Path.of(path)));
    }

    protected void thenFileExists(String path) { assertTrue(Files.exists(Path.of(path)), path); }
    protected void thenFileDoesNotExist(String path) { assertFalse(Files.exists(Path.of(path)), path); }
    protected void thenFileSizeIs(String path, int size) throws IOException { assertEquals(size, Files.size(Path.of(path))); }
    protected void thenFileSizeIsNotZero(String path) throws IOException { assertNotEquals(0, Files.size(Path.of(path))); }
    protected void thenFileSizeDecreased(String path) throws IOException {
        assertTrue(Files.size(Path.of(path)) < this.fileSizes.get(Path.of(path)), "Database file did not shrink");
    }
    protected void thenFileSizeDidNotChange(String path) throws IOException {
        assertEquals(this.fileSizes.get(Path.of(path)).longValue(), Files.size(Path.of(path)));
    }
    protected void thenNoExceptionIsThrown() { assertEquals(Optional.empty(), this.exception); }
    protected void thenExceptionIsThrown() {
        assertTrue(this.exception.isPresent());
        this.exception = Optional.empty();
    }
    protected <E extends Exception> void thenExceptionIsThrown(Class<E> type, String message) {
        assertTrue(this.exception.isPresent());
        assertInstanceOf(type, this.exception.get());
        assertTrue(this.exception.get().getMessage().contains(message));
        this.exception = Optional.empty();
    }
    protected String temporaryDirectory() { return this.directory.toString(); }
    protected String dbServicePid() { return (String) this.properties.get("kura.service.pid"); }
    protected String largeText(int size) { return "a".repeat(size); }
    protected Map<String, Object> map(Object... pairs) {
        Map<String, Object> result = new HashMap<>();
        for (int i = 0; i < pairs.length; i += 2) {
            result.put((String) pairs[i], pairs[i + 1]);
        }
        return result;
    }
}
