/*******************************************************************************
 * Copyright (c) 2017, 2026 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.internal.db.h2db.provider;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ScheduledFuture;

import org.eclipse.kura.KuraException;
import org.eclipse.kura.core.testutil.TestUtil;
import org.eclipse.kura.crypto.CryptoService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

public class H2DbServiceImplTest {

    @Test
    public void testUpdate() throws KuraException, SQLException {
        final String enc = "enc";
        char[] encPass = enc.toCharArray();
        String pass = "pass";
        String user = "USR";

        H2DbServiceImpl svc = new H2DbServiceImpl();
        CryptoService csMock = mock(CryptoService.class);
        when(csMock.decryptAes(any(char[].class))).thenReturn(new char[0]);
        svc.setCryptoService(csMock);
        svc.activate(Collections.emptyMap());

        Map<String, Object> props = new HashMap<>();
        props.put("db.user", user);
        props.put("db.password", enc);
        props.put("db.connection.pool.max.size", 10);
        props.put("db.connector.url", "jdbc:h2:mem:testdb");

        try {
            svc.getConnection();
        } catch (SQLException e) {
            assertTrue(e.getMessage().contains("not initialized"));
        }

        svc.updated(props);

        Connection conn = svc.getConnection();
        PreparedStatement statement = conn.prepareStatement("SELECT USER()");

        ResultSet rs = statement.executeQuery();
        rs.next();
        String result = rs.getString(1);

        assertEquals(user, result);

        svc.deactivate();
    }

    @Test
    public void testUpdateFailUrlPattern() throws KuraException, SQLException {
        String pass = "pass";
        String user = "USR";

        H2DbServiceImpl svc = new H2DbServiceImpl();
        CryptoService csMock = mock(CryptoService.class);
        when(csMock.decryptAes(any(char[].class))).thenReturn(new char[0]);
        svc.setCryptoService(csMock);
        svc.activate(Collections.emptyMap());

        try {
            Map<String, Object> props = new HashMap<>();
            props.put("db.user", user);
            props.put("db.password", pass);
            props.put("db.connection.pool.max.size", 10);
            props.put("db.connector.url", "jdb:h2:mem:testdb");

            try {
                svc.getConnection();
            } catch (SQLException e) {
                assertTrue(e.getMessage().contains("not initialized"));
            }

            try {
                svc.updated(props);
            } catch (IllegalArgumentException e) {
                assertEquals("Invalid DB URL", e.getMessage());
            }
        } finally {
            svc.deactivate();
        }
    }

    @Test
    public void testUpdateFailDriver() throws KuraException, SQLException {
        String pass = "pass";
        String user = "USR";

        H2DbServiceImpl svc = new H2DbServiceImpl();
        CryptoService csMock = mock(CryptoService.class);
        when(csMock.decryptAes(any(char[].class))).thenReturn(new char[0]);
        svc.setCryptoService(csMock);
        svc.activate(Collections.emptyMap());

        try {
            Map<String, Object> props = new HashMap<>();
            props.put("db.user", user);
            props.put("db.password", pass);
            props.put("db.connection.pool.max.size", 10);
            props.put("db.connector.url", "jdbc:h3:mem:testdb");

            try {
                svc.getConnection();
            } catch (SQLException e) {
                assertTrue(e.getMessage().contains("not initialized"));
            }

            try {
                svc.updated(props);
            } catch (IllegalArgumentException e) {
                assertEquals("JDBC driver must be h2", e.getMessage());
            }
        } finally {
            svc.deactivate();
        }
    }

    @Test
    public void testUpdateFailRemote() throws Throwable {
        final String enc = "enc";
        String user = "USR";

        H2DbServiceImpl svc = new H2DbServiceImpl();
        CryptoService csMock = mock(CryptoService.class);
        when(csMock.decryptAes(any(char[].class))).thenReturn(new char[0]);
        svc.setCryptoService(csMock);
        svc.activate(Collections.emptyMap());

        try {
            Map<String, Object> props = new HashMap<>();
            props.put("db.user", user);
            props.put("db.password", enc);
            props.put("db.connection.pool.max.size", 10);
            props.put("db.connector.url", "jdbc:h2:rmt:test");

            try {
                svc.updated(props);
            } catch (IllegalArgumentException e) {
                assertEquals("Remote databases are not supported", e.getMessage());
            }
        } finally {
            svc.deactivate();
        }
    }

    @Test
    public void testUpdateFailAnonymous() throws Throwable {
        final String enc = "enc";
        String user = "USR";

        H2DbServiceImpl svc = new H2DbServiceImpl();
        CryptoService csMock = mock(CryptoService.class);
        when(csMock.decryptAes(any(char[].class))).thenReturn(new char[0]);
        svc.setCryptoService(csMock);
        svc.activate(Collections.emptyMap());

        try {
            Map<String, Object> props = new HashMap<>();
            props.put("db.user", user);
            props.put("db.password", enc);
            props.put("db.connection.pool.max.size", 10);
            props.put("db.connector.url", "jdbc:h2:mem:");

            try {
                svc.updated(props);
            } catch (IllegalArgumentException e) {
                assertTrue(e.getMessage().startsWith("Anonymous"));
            }
        } finally {
            svc.deactivate();
        }
    }

    @Test
    public void testUpdateFailUrlOccupied() throws Throwable {
        final String enc = "enc";
        String user = "USR";
        String url = "jdbc:h2:mem:test";

        H2DbServiceImpl svc1 = new H2DbServiceImpl();
        Map<String, H2DbServiceImpl> activeInstances = (Map<String, H2DbServiceImpl>) TestUtil.getFieldValue(svc1,
                "activeInstances");
        activeInstances.put(url, svc1);

        H2DbServiceImpl svc = new H2DbServiceImpl();
        try {
            CryptoService csMock = mock(CryptoService.class);
            when(csMock.decryptAes(any(char[].class))).thenReturn(new char[0]);
            svc.setCryptoService(csMock);
            svc.activate(Collections.emptyMap());

            Map<String, Object> props = new HashMap<>();
            props.put("db.user", user);
            props.put("db.password", enc);
            props.put("db.connection.pool.max.size", 10);
            props.put("db.connector.url", url);

            try {
                svc.updated(props);
            } catch (IllegalArgumentException e) {
                assertTrue(e.getMessage().startsWith("Another H2DbService instance"));
            }
        } finally {
            svc.deactivate();
            activeInstances.remove(url);
        }
    }

    @Test
    public void testFileMaintenanceTasksRetiredOnUpdate(@TempDir Path directory) throws Exception {
        H2DbServiceImpl service = new H2DbServiceImpl();
        CryptoService crypto = mock(CryptoService.class);
        when(crypto.decryptAes(any(char[].class))).thenReturn(new char[0]);
        service.setCryptoService(crypto);
        Map<String, Object> properties = new HashMap<>();
        properties.put("db.connector.url", "jdbc:h2:file:" + directory.resolve("maintenance"));
        service.activate(properties);
        try {
            service.getConnection().close();
            var checkpoint = (ScheduledFuture<?>) TestUtil.getFieldValue(service, "checkpointTask");
            var defrag = (ScheduledFuture<?>) TestUtil.getFieldValue(service, "defragTask");
            properties.put("db.defrag.interval.minutes", 0);
            service.updated(properties);
            service.getConnection().close();
            assertTrue(checkpoint.isCancelled());
            assertTrue(defrag.isCancelled());
        } finally {
            service.deactivate();
        }
    }

    @Test
    public void testRetainedFileAfterFailedOpen(@TempDir Path directory) throws Exception {
        String url = "jdbc:h2:file:" + directory.resolve("business");
        CryptoService crypto = mock(CryptoService.class);
        when(crypto.decryptAes(any(char[].class))).thenAnswer(call -> call.getArgument(0));
        Map<String, Object> properties = Map.of("db.connector.url", url, "db.user", "USR", "db.password", "original");

        H2DbServiceImpl first = new H2DbServiceImpl();
        first.setCryptoService(crypto);
        first.activate(properties);
        try (Connection connection = first.getConnection(); var statement = connection.createStatement()) {
            statement.execute("CREATE TABLE retained_record (value_id INTEGER)");
            statement.executeUpdate("INSERT INTO retained_record VALUES (413)");
            connection.commit();
        } finally {
            first.deactivate();
        }

        Map<String, Object> unavailable = new HashMap<>(properties);
        unavailable.put("db.password", "unavailable");
        H2DbServiceImpl restarted = new H2DbServiceImpl();
        restarted.setCryptoService(crypto);
        restarted.activate(unavailable);
        try {
            assertThrows(SQLException.class, restarted::getConnection);
            assertTrue(Files.isRegularFile(directory.resolve("business.mv.db")));
            restarted.updated(properties);
            try (Connection connection = restarted.getConnection();
                    var statement = connection.createStatement();
                    var rows = statement.executeQuery("SELECT value_id FROM retained_record")) {
                assertTrue(rows.next());
                assertEquals(413, rows.getInt(1));
            }
        } finally {
            restarted.deactivate();
        }
    }

}
