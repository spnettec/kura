/*******************************************************************************
 * Copyright (c) 2018, 2026 Red Hat Inc and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Red Hat Inc
 *******************************************************************************/

package org.eclipse.kura.osgi;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.nio.file.Path;
import java.util.Map;

import org.eclipse.osgi.launch.EquinoxFactory;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.io.TempDir;
import org.osgi.framework.BundleContext;
import org.osgi.framework.Constants;
import org.osgi.framework.FrameworkEvent;
import org.osgi.framework.launch.Framework;

/** Isolated embedded framework; no workspace emulator or installed gateway is modified. */
@Timeout(30)
abstract class EquinoxTestBase {

    @TempDir
    Path storage;
    protected BundleContext context;
    private Framework framework;

    @BeforeEach
    void startFramework() throws Exception {
        this.framework = new EquinoxFactory().newFramework(Map.of(Constants.FRAMEWORK_STORAGE, this.storage.toString(),
                Constants.FRAMEWORK_STORAGE_CLEAN, Constants.FRAMEWORK_STORAGE_CLEAN_ONFIRSTINIT));
        this.framework.start();
        this.context = this.framework.getBundleContext();
    }

    @AfterEach
    void stopFramework() throws Exception {
        if (this.framework != null) {
            this.framework.stop();
            assertEquals(FrameworkEvent.STOPPED, this.framework.waitForStop(5000).getType());
        }
    }
}
