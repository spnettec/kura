/*******************************************************************************
 * Copyright (c) 2021, 2022 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.log.filesystem.provider;

import static java.nio.file.StandardOpenOption.APPEND;
import static java.nio.file.StandardOpenOption.TRUNCATE_EXISTING;
import static java.util.concurrent.TimeUnit.SECONDS;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;

import org.eclipse.kura.log.LogEntry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class FilesystemLogProviderTest {

    @TempDir
    Path directory;

    private final FilesystemLogProvider provider = new FilesystemLogProvider();
    private final BlockingQueue<LogEntry> entries = new LinkedBlockingQueue<>();

    private void start(Path path) {
        this.provider.registerLogListener(this.entries::add);
        this.provider.activate(Map.of("logFilePath", path.toString()));
    }

    private void expect(String message) throws InterruptedException {
        LogEntry entry = this.entries.poll(4, SECONDS);
        assertEquals(message, entry == null ? null : entry.getProperties().get("MESSAGE"));
    }

    @AfterEach
    void stop() {
        this.provider.deactivate();
    }

    @Test
    void drainsTheRenamedFileAndReadsEvenALargerReplacementFromTheBeginning() throws Exception {
        Path log = this.directory.resolve("kura.log");
        Path alias = this.directory.resolve("retained-kura.log");
        Files.createSymbolicLink(alias, log);
        String prefix = "2026-11-21T00:00:00,010 [main] INFO ";
        Files.writeString(log, prefix + "before\n");
        start(alias);
        expect("before");
        Files.writeString(log, prefix + "tail\n", APPEND);
        Files.move(log, this.directory.resolve("previous"));
        Files.writeString(log, prefix + "after\n" + prefix + "more\n");
        expect("tail");
        expect("after");
        expect("more");
        assertNull(this.entries.poll());
    }

    @Test
    void waitsForANewFileAndForCompleteUtf8Lines() throws Exception {
        Path log = this.directory.resolve("kura.log");
        start(log);
        Thread.sleep(250);
        Files.writeString(log, "2026-11-21T00:00:00,010 [main] INFO 设备");
        Thread.sleep(250);
        assertNull(this.entries.poll());
        Files.writeString(log, "就绪\n", APPEND);
        expect("设备就绪");
    }

    @Test
    void readsFromTheBeginningAfterObservedTruncation() throws Exception {
        Path log = this.directory.resolve("kura.log");
        String prefix = "2026-11-21T00:00:00,010 [main] INFO ";
        Files.writeString(log, prefix + "a longer original message\n");
        start(log);
        expect("a longer original message");
        Files.writeString(log, prefix + "new\n", TRUNCATE_EXISTING);
        expect("new");
    }

    @Test
    void retainsAnIncompleteStackFrameUntilTheLineCompletes() throws Exception {
        Path log = this.directory.resolve("kura.log");
        Files.writeString(log, "2026-11-21T00:00:00,010 [main] ERROR failed\n    at Handler.");
        start(log);
        assertNull(this.entries.poll(300, java.util.concurrent.TimeUnit.MILLISECONDS));
        Files.writeString(log, "process()\n", APPEND);
        LogEntry entry = this.entries.poll(4, SECONDS);
        assertNotNull(entry);
        assertEquals("failed", entry.getProperties().get("MESSAGE"));
        assertEquals("at Handler.process()", entry.getProperties().get("STACKTRACE"));
    }
}
