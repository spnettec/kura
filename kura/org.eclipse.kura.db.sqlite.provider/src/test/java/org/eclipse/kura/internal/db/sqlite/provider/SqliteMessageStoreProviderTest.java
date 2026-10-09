/*******************************************************************************
 * Copyright (c) 2023, 2026 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.internal.db.sqlite.provider;

import static org.mockito.Mockito.mock;

import java.sql.Connection;
import java.sql.Statement;
import java.util.Map;

import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.message.store.provider.MessageStoreProvider;
import org.eclipse.kura.message.store.provider.test.AbstractMessageStoreProviderTest;
import org.junit.jupiter.api.AfterEach;

class SqliteMessageStoreProviderTest extends AbstractMessageStoreProviderTest {

    private SqliteDbServiceImpl database;

    @Override
    protected MessageStoreProvider startDatabase() throws Exception {
        this.database = new SqliteDbServiceImpl();
        this.database.setCryptoService(mock(CryptoService.class));
        this.database.setDebugShell(mock(SqliteDebugShell.class));
        this.database.activate(Map.of("db.mode", "IN_MEMORY", "db.defrag.enabled", false,
                "db.wal.checkpoint.enabled", false));
        return this.database;
    }

    @AfterEach
    void closeDatabase() {
        if (this.database != null) {
            this.database.deactivate();
        }
    }

    @Override
    protected void setLastMessageId(String table, int value) throws Exception {
        try (Connection connection = this.database.getConnection(); Statement statement = connection.createStatement()) {
            statement.executeUpdate("UPDATE sqlite_sequence SET seq = " + value + " WHERE name = '" + table + "'");
        }
    }

    @Override
    protected void ageMessages(String table, long milliseconds) throws Exception {
        try (Connection connection = this.database.getConnection(); Statement statement = connection.createStatement()) {
            for (String column : new String[] { "createdOn", "publishedOn", "confirmedOn", "droppedOn" }) {
                String value = column + " - " + milliseconds;
                statement.executeUpdate("UPDATE \"" + table + "\" SET " + column + " = " + value);
            }
        }
    }
}
