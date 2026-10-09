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

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.sql.SQLException;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.parallel.ResourceLock;
import org.junit.jupiter.api.parallel.Resources;

@ResourceLock(Resources.SYSTEM_OUT)
@Timeout(30)
class SqliteDebugShellTest extends SqliteDbServiceTestBase {

    @Test
    void shouldNotAllowAccessToDatabaseIfNotEnabled() throws Exception {
        givenSqliteDbService(Map.of());
        IllegalArgumentException failure = assertThrows(IllegalArgumentException.class,
                () -> query("CREATE TABLE FOO (BAR INTEGER);"));
        assertTrue(failure.getMessage().contains("is not available"));
    }

    @Test
    void shouldAllowAccessToDatabaseIfEnabled() throws Exception {
        givenSqliteDbService(Map.of("debug.shell.access.enabled", true));
        assertEquals("0 rows changed\n", query("CREATE TABLE FOO (BAR INTEGER);"));
    }

    @Test
    void shouldDisableDebugShellOnUpdate() throws Exception {
        givenSqliteDbService(Map.of("debug.shell.access.enabled", true));
        whenSqliteDbServiceIsUpdated(Map.of("debug.shell.access.enabled", false));
        assertThrows(IllegalArgumentException.class, () -> query("CREATE TABLE FOO (BAR INTEGER);"));
    }

    @Test
    void shouldEnableDebugShellOnUpdate() throws Exception {
        givenSqliteDbService(Map.of("debug.shell.access.enabled", false));
        whenSqliteDbServiceIsUpdated(Map.of("debug.shell.access.enabled", true));
        assertEquals("0 rows changed\n", query("CREATE TABLE FOO (BAR INTEGER);"));
    }

    @Test
    void shouldPrintResultSet() throws Exception {
        givenSqliteDbService(Map.of("debug.shell.access.enabled", true));
        givenExecutedQuery("CREATE TABLE FOO (T TEXT, N NUMERIC, I INTEGER, R REAL, B BLOB);");
        givenExecutedQuery("INSERT INTO FOO VALUES ('abc', 123, 12, 12.33, x'0123456789abcdef0123456789abcdef');");
        assertEquals("| T\t| N\t| I\t| R\t| B\t|\n"
                + "| abc\t| 123\t| 12\t| 12.33\t| X'0123456789ABCDEF0123456789ABCDEF'\t|\n",
                query("SELECT T, N, I, R, quote(B) AS B FROM FOO;"));
    }

    @Test
    void shouldReportFailure() throws Exception {
        givenSqliteDbService(Map.of("debug.shell.access.enabled", true));
        SQLException failure = assertThrows(SQLException.class, () -> query("SELECT * FROM NONEXISTING;"));
        assertTrue(failure.getMessage().contains("NONEXISTING"));
    }

    private String query(String sql) throws SQLException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        PrintStream previous = System.out;
        try (PrintStream capture = new PrintStream(output, true, StandardCharsets.UTF_8)) {
            System.setOut(capture);
            this.debugShell.executeQuery(dbServicePid(), sql);
            return output.toString(StandardCharsets.UTF_8).replace(System.lineSeparator(), "\n");
        } finally {
            System.setOut(previous);
        }
    }
}
