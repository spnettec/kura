/*******************************************************************************
 * Copyright (c) 2023 Eurotech and/or its affiliates and others
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

import static org.junit.Assert.assertEquals;

import java.io.File;
import java.util.Optional;

import org.junit.Test;
import org.mockito.Mockito;
import org.osgi.framework.BundleContext;

public class SqliteProviderActivatorTest {

    @Test
    public void shouldSetSqliteTempDirIfUnset() {
        givenBundleStorageAreaPath("/tmp/foo");

        whenActivatorIsStarted();

        thenNoExceptionIsThrown();
        thenSystemPropertyValueIs("org.sqlite.tmpdir", "/tmp/foo");
    }

    @Test
    public void shouldNotSetSqliteTempDirIfBundleStorageAreaIsNotAvailable() {
        givenNoBundleStorageArea();

        whenActivatorIsStarted();

        thenNoExceptionIsThrown();
        thenSystemPropertyValueIs("org.sqlite.tmpdir", null);
    }

    @Test
    public void shouldNotChangeSqliteTempDirIfAlreadySet() {
        givenSystemProperty("org.sqlite.tmpdir", "bar");
        givenBundleStorageAreaPath("/tmp/foo");

        whenActivatorIsStarted();

        thenNoExceptionIsThrown();
        thenSystemPropertyValueIs("org.sqlite.tmpdir", "bar");
    }

    private final BundleContext bundleContext = Mockito.mock(BundleContext.class);
    private Optional<Exception> exception = Optional.empty();

    private void givenBundleStorageAreaPath(String path) {
        Mockito.when(bundleContext.getDataFile("")).thenReturn(new File(path));
    }

    private void givenNoBundleStorageArea() {
        Mockito.when(bundleContext.getDataFile("")).thenReturn(null);
    }

    private void givenSystemProperty(final String key, final String value) {
        System.setProperty(key, value);
    }

    private void whenActivatorIsStarted() {
        try {
            new SqliteProviderActivator().start(bundleContext);
        } catch (Exception e) {
            this.exception = Optional.of(e);
        }

    }

    private void thenSystemPropertyValueIs(final String key, final String value) {
        assertEquals(value, System.getProperty(key));
    }

    private void thenNoExceptionIsThrown() {
        assertEquals(Optional.empty(), this.exception);

    }
}
