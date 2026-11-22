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

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.regex.Pattern;

import org.eclipse.kura.configuration.ConfigurableComponent;
import org.eclipse.kura.log.LogEntry;
import org.eclipse.kura.log.LogProvider;
import org.eclipse.kura.log.listener.LogListener;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class FilesystemLogProvider implements ConfigurableComponent, LogProvider {

    private static final Logger logger = LoggerFactory.getLogger(FilesystemLogProvider.class);
    public static final String LOG_FILEPATH_PROP_KEY = "logFilePath";

    private final List<LogListener> registeredListeners = new CopyOnWriteArrayList<>();
    private FileLogReader readerThread;

    protected void activate(Map<String, Object> properties) {
        logger.info("Activating FilesystemLogProvider...");
        updated(properties);
        logger.info("Activating FilesystemLogProvider... Done.");
    }

    protected void deactivate() {
        logger.info("Deactivating FilesystemLogProvider...");
        if (this.readerThread != null) {
            this.readerThread.interrupt();
        }
        logger.info("Deactivating FilesystemLogProvider... Done.");
    }

    public void updated(Map<String, Object> properties) {
        logger.info("Updated FilesystemLogProvider...");
        if (this.readerThread != null) {
            this.readerThread.interrupt();
        }
        this.readerThread = new FileLogReader((String) properties.get(LOG_FILEPATH_PROP_KEY));
        this.readerThread.start();
        logger.info("Updated FilesystemLogProvider... Done.");
    }

    @Override
    public void registerLogListener(LogListener listener) {
        this.registeredListeners.add(listener);
    }

    @Override
    public void unregisterLogListener(LogListener listener) {
        this.registeredListeners.remove(listener);
    }

    private final class FileLogReader extends Thread {

        private static final long SAMPLE_INTERVAL = 100;
        private static final Pattern YEAR = Pattern.compile("^[0-9]{4}");
        private final Path path;
        private final ByteBuffer buffer = ByteBuffer.allocate(8192);
        private final ByteArrayOutputStream partialLine = new ByteArrayOutputStream();
        private String message;
        private final StringBuilder stacktrace = new StringBuilder();

        FileLogReader(String filePath) {
            this.path = Path.of(filePath);
        }

        @Override
        public void run() {
            try {
                while (!isInterrupted()) {
                    try {
                        followFile();
                    } catch (NoSuchFileException e) {
                        // The appender may start later or temporarily remove the name during rollover.
                    }
                    Thread.sleep(SAMPLE_INTERVAL);
                }
            } catch (InterruptedException e) {
                interrupt();
            } catch (Exception e) {
                logger.error("Could not follow log file '{}'.", this.path, e);
            }
        }

        private void followFile() throws IOException, InterruptedException {
            BasicFileAttributes opened = attributes();
            if (!opened.isRegularFile()) {
                throw new IOException("Expected a regular log file at " + this.path);
            }
            try (FileChannel channel = FileChannel.open(this.path)) {
                if (!sameFile(opened, attributes())) {
                    return;
                }
                this.partialLine.reset();
                while (!isInterrupted()) {
                    readAvailable(channel);
                    try {
                        if (!sameFile(opened, attributes())) {
                            // Drain any final writes to the old inode before opening its replacement.
                            readAvailable(channel);
                            publishMessage();
                            return;
                        }
                    } catch (NoSuchFileException e) {
                        // Retain the open file until the new one is visible.
                    }
                    Thread.sleep(SAMPLE_INTERVAL);
                }
            }
        }

        private BasicFileAttributes attributes() throws IOException {
            return Files.readAttributes(this.path, BasicFileAttributes.class);
        }

        private boolean sameFile(BasicFileAttributes first, BasicFileAttributes second) {
            if (first.fileKey() != null || second.fileKey() != null) {
                return Objects.equals(first.fileKey(), second.fileKey());
            }
            return first.creationTime().equals(second.creationTime());
        }

        private void readAvailable(FileChannel channel) throws IOException {
            long end = channel.size();
            if (channel.position() > end) {
                publishMessage();
                channel.position(0);
                this.partialLine.reset();
            }
            while (!isInterrupted() && channel.position() < end) {
                this.buffer.clear();
                this.buffer.limit((int) Math.min(this.buffer.capacity(), end - channel.position()));
                if (channel.read(this.buffer) <= 0) {
                    break;
                }
                this.buffer.flip();
                while (this.buffer.hasRemaining()) {
                    byte value = this.buffer.get();
                    this.partialLine.write(value);
                    if (value == '\n') {
                        acceptLine(this.partialLine.toString(StandardCharsets.UTF_8));
                        this.partialLine.reset();
                    }
                }
            }
            if (this.partialLine.size() == 0) {
                publishMessage();
            }
        }

        private void acceptLine(String line) {
            // Audit records start with '<', ordinary records start with a four-digit year.
            if (this.message != null && line.length() > 4 && !line.startsWith("<")
                    && !YEAR.matcher(line).find()) {
                this.stacktrace.append(line).append('\n');
            } else {
                publishMessage();
                this.message = line;
            }
        }

        private void publishMessage() {
            if (this.message != null && !isInterrupted()) {
                for (LogListener listener : FilesystemLogProvider.this.registeredListeners) {
                    LogEntry entry = new KuraLogLineParser(this.message, this.path.toString(),
                            this.stacktrace.toString().trim()).createLogEntry();
                    listener.newLogEntry(entry);
                }
            }
            this.message = null;
            this.stacktrace.setLength(0);
        }
    }
}
