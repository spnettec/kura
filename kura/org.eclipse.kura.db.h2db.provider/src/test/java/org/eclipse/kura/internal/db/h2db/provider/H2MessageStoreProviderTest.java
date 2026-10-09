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
package org.eclipse.kura.internal.db.h2db.provider;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.sql.Connection;
import java.sql.Statement;
import java.util.Map;
import java.util.UUID;

import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.message.store.provider.MessageStoreProvider;
import org.eclipse.kura.message.store.provider.test.AbstractMessageStoreProviderTest;
import org.junit.jupiter.api.AfterEach;

class H2MessageStoreProviderTest extends AbstractMessageStoreProviderTest {

    private H2DbServiceImpl database;

    @Override
    protected MessageStoreProvider startDatabase() throws Exception {
        this.database = new H2DbServiceImpl();
        CryptoService crypto = mock(CryptoService.class);
        when(crypto.decryptAes(any(char[].class))).thenReturn(new char[0]);
        this.database.setCryptoService(crypto);
        this.database.activate(Map.of("db.connector.url", "jdbc:h2:mem:" + UUID.randomUUID(),
                "db.user", "sa", "db.password", "encrypted", "db.connection.pool.max.size", 2));
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
            statement.executeUpdate("ALTER TABLE \"" + table + "\" ALTER COLUMN id RESTART WITH " + value);
            connection.commit();
        }
        this.database.openMessageStore(table).store("identity-boundary", null, 1, false, 1);
    }

    @Override
    protected void ageMessages(String table, long milliseconds) throws Exception {
        try (Connection connection = this.database.getConnection(); Statement statement = connection.createStatement()) {
            for (String column : new String[] { "createdOn", "publishedOn", "confirmedOn", "droppedOn" }) {
                String value = "DATEADD('MILLISECOND', -" + milliseconds + ", " + column + ")";
                statement.executeUpdate("UPDATE \"" + table + "\" SET " + column + " = " + value);
            }
            connection.commit();
        }
    }
}
