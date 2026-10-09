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
package org.eclipse.kura.core.system;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.io.StringWriter;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.*;

import org.eclipse.kura.system.SystemService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.api.parallel.ResourceLock;
import org.junit.jupiter.api.parallel.Resources;
import org.mockito.MockedStatic;
import org.osgi.service.component.ComponentContext;

@ResourceLock(Resources.SYSTEM_PROPERTIES)
abstract class SystemServiceTestBase {
    @TempDir
    Path directory;
    protected final ComponentContext context = mock(ComponentContext.class);
    private Properties original;
    private final List<SystemServiceImpl> services = new ArrayList<>();
    private final List<ScheduledExecutorService> schedulers = new ArrayList<>();
    private final List<ScheduledFuture<?>> tasks = new ArrayList<>();

    @BeforeEach
    void isolateProperties() {
        this.original = System.getProperties();
        Properties isolated = new Properties();
        isolated.putAll(this.original);
        isolated.keySet().removeIf(key -> key.toString().startsWith("kura.")
                || key.equals("dpa.configuration") || key.equals("log4j.configuration"));
        System.setProperties(isolated);
        System.setProperty("org.eclipse.kura.core.dontExitOnFailure", "true");
    }

    protected SystemServiceImpl resourceService(Map<String, String> defaults) throws Exception {
        Properties properties = new Properties();
        properties.putAll(defaults);
        StringWriter writer = new StringWriter();
        properties.store(writer, "test fixture");
        return new SystemServiceImpl() {
            @Override
            protected String readResource(String resource) {
                return resource.equals(SystemService.KURA_PROPS_FILE) ? writer.toString() : "";
            }
        };
    }

    protected SystemServiceImpl fileService() {
        return new SystemServiceImpl() {
            @Override
            protected String readResource(String resource) { return null; }
        };
    }

    protected void activate(SystemServiceImpl service) throws Exception {
        this.services.add(service);
        ScheduledExecutorService scheduler = mock(ScheduledExecutorService.class);
        ScheduledFuture<?> task = mock(ScheduledFuture.class);
        this.schedulers.add(scheduler);
        this.tasks.add(task);
        doReturn(task).when(scheduler).scheduleAtFixedRate(any(Runnable.class), eq(5000L), eq(30000L), eq(TimeUnit.MILLISECONDS));
        when(scheduler.awaitTermination(5000, TimeUnit.MILLISECONDS)).thenReturn(true);
        try (MockedStatic<Executors> executors = mockStatic(Executors.class, CALLS_REAL_METHODS)) {
            executors.when(() -> Executors.newSingleThreadScheduledExecutor(any(ThreadFactory.class)))
                    .thenReturn(scheduler);
            service.activate(this.context);
        }
        verify(scheduler).scheduleAtFixedRate(any(Runnable.class), eq(5000L), eq(30000L), eq(TimeUnit.MILLISECONDS));
    }

    @AfterEach
    void restoreProperties() {
        try {
            this.services.forEach(service -> service.deactivate(this.context));
            this.schedulers.forEach(scheduler -> verify(scheduler).shutdown());
            this.tasks.forEach(task -> verify(task).cancel(true));
        } finally {
            System.setProperties(this.original);
        }
    }
}
