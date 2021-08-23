/*******************************************************************************
 * Copyright (c) 2019, 2021 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.core.linux.executor.unprivileged;

import static java.lang.Thread.currentThread;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.StringReader;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.Properties;
import java.util.function.Consumer;

import org.apache.commons.io.IOUtils;
import org.eclipse.kura.core.internal.linux.executor.ExecutorUtil;
import org.eclipse.kura.core.linux.executor.LinuxExitStatus;
import org.eclipse.kura.core.linux.executor.LinuxSignal;
import org.eclipse.kura.executor.Command;
import org.eclipse.kura.executor.CommandStatus;
import org.eclipse.kura.executor.Pid;
import org.eclipse.kura.executor.Signal;
import org.eclipse.kura.executor.UnprivilegedExecutorService;
import org.eclipse.kura.system.SystemService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class UnprivilegedExecutorServiceImpl implements UnprivilegedExecutorService {

    private static final Logger logger = LoggerFactory.getLogger(UnprivilegedExecutorServiceImpl.class);
    private static final LinuxSignal DEFAULT_SIGNAL = LinuxSignal.SIGTERM;
    private ExecutorUtil executorUtil;

    protected void activate() {
        logger.info("activate...");
        String user = "unknown";
        try {
            user = getCommandUsername();
        } catch (IOException e) {
        }

        if ("unknown".equals(user)) {
            this.executorUtil = new ExecutorUtil();
        } else {
            this.executorUtil = new ExecutorUtil(user);
        }
    }

    protected void deactivate() {
        logger.info("deactivate...");
    }

    @Override
    public CommandStatus execute(Command command) {
        if (command.getCommandLine() == null || command.getCommandLine().length == 0) {
            return buildErrorStatus(command);
        }
        if (command.getSignal() == null) {
            command.setSignal(DEFAULT_SIGNAL);
        }
        return this.executorUtil.executeUnprivileged(command);
    }

    @Override
    public void execute(Command command, Consumer<CommandStatus> callback) {
        if (command.getCommandLine() == null || command.getCommandLine().length == 0) {
            callback.accept(buildErrorStatus(command));
            return;
        }
        if (command.getSignal() == null) {
            command.setSignal(DEFAULT_SIGNAL);
        }
        this.executorUtil.executeUnprivileged(command, callback);
    }

    @Override
    public boolean stop(Pid pid, Signal signal) {
        boolean isStopped = false;
        if (signal == null) {
            isStopped = this.executorUtil.stopUnprivileged(pid, DEFAULT_SIGNAL);
        } else {
            isStopped = this.executorUtil.stopUnprivileged(pid, signal);
        }
        return isStopped;
    }

    @Override
    public boolean kill(String[] commandLine, Signal signal) {
        boolean isKilled = false;
        if (signal == null) {
            isKilled = this.executorUtil.killUnprivileged(commandLine, DEFAULT_SIGNAL);
        } else {
            isKilled = this.executorUtil.killUnprivileged(commandLine, signal);
        }
        return isKilled;
    }

    @Override
    public boolean isRunning(Pid pid) {
        return this.executorUtil.isRunning(pid);
    }

    @Override
    public boolean isRunning(String[] commandLine) {
        return this.executorUtil.isRunning(commandLine);
    }

    @Override
    public Map<String, Pid> getPids(String[] commandLine) {
        return this.executorUtil.getPids(commandLine);
    }

    private CommandStatus buildErrorStatus(Command command) {
        CommandStatus status = new CommandStatus(command, new LinuxExitStatus(1));
        ByteArrayOutputStream err = new ByteArrayOutputStream();
        try {
            err.write("The commandLine cannot be empty or not defined".getBytes(StandardCharsets.UTF_8));
        } catch (IOException e) {
            logger.error("Cannot write to error stream", e);
        }
        status.setErrorStream(err);
        return status;
    }

    private String getCommandUsername() throws IOException {
        String kuraConfig = System.getProperty(SystemService.KURA_CONFIG);
        String kuraProps = readResource(SystemService.KURA_PROPS_FILE);
        Properties kuraDefaults = new Properties();
        if (kuraProps != null) {
            kuraDefaults.load(new StringReader(kuraProps));
            logger.info("Loaded Jar Resource kura.properties.");
        } else if (kuraConfig != null) {
            loadKuraDefaults(kuraDefaults, kuraConfig);
        } else {
            logger.error("Could not locate kura.properties file");
        }
        // load custom kura properties
        // look for kura_custom.properties as resource in the classpath
        // if not found, look for such file in the kura.user.config directory
        Properties kuraCustomProps = new Properties();
        String kuraCustomConfig = System.getProperty(SystemService.KURA_CUSTOM_CONFIG);
        String kuraCustomProperties = readResource(SystemService.KURA_CUSTOM_PROPS_FILE);

        if (kuraCustomProperties != null) {
            kuraCustomProps.load(new StringReader(kuraCustomProperties));
            logger.info("Loaded Jar Resource: {}", SystemService.KURA_CUSTOM_PROPS_FILE);
        } else if (kuraCustomConfig != null) {
            loadKuraCustom(kuraCustomProps, kuraCustomConfig);
        }

        // Override defaults with values from kura_custom.properties
        kuraDefaults.putAll(kuraCustomProps);
        String userName = kuraDefaults.getProperty(SystemService.KEY_COMMAND_USER);
        if (userName == null) {
            return "unknown";
        }
        return userName;

    }

    private void loadKuraCustom(Properties kuraCustomProps, String kuraCustomConfig) {
        try {
            final URL kuraConfigUrl = new URL(kuraCustomConfig);
            try (InputStream in = kuraConfigUrl.openStream()) {
                kuraCustomProps.load(in);
            }
            logger.info("Loaded URL kura_custom.properties: {}", kuraCustomConfig);
        } catch (Exception e) {
            logger.warn("Could not open kuraCustomConfig URL: ", e);
        }
    }

    private void loadKuraDefaults(Properties kuraDefaults, String kuraConfig) {
        try {
            final URL kuraConfigUrl = new URL(kuraConfig);
            try (InputStream in = kuraConfigUrl.openStream()) {
                kuraDefaults.load(in);
            }
            logger.info("Loaded URL kura.properties: {}", kuraConfig);
        } catch (Exception e) {
            logger.warn("Could not open kuraConfig URL", e);
        }
    }

    private String readResource(String resource) throws IOException {
        if (resource == null) {
            return null;
        }

        final URL resourceUrl = currentThread().getContextClassLoader().getResource(resource);

        if (resourceUrl == null) {
            return null;
        }

        return IOUtils.toString(resourceUrl, StandardCharsets.UTF_8);
    }

}
