/*******************************************************************************
 * Copyright (c) 2011, 2019 Eurotech and/or its affiliates
 *
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 * Contributors:
 *     Eurotech
 *******************************************************************************/
package org.eclipse.kura.linux.net.util;

import java.io.ByteArrayOutputStream;

import org.apache.commons.io.Charsets;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.executor.Command;
import org.eclipse.kura.executor.CommandExecutorService;
import org.eclipse.kura.executor.CommandStatus;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class IwLinkTool implements LinkTool {

    private static final Logger logger = LoggerFactory.getLogger(IwLinkTool.class);

    private String interfaceName = null;
    private boolean linkDetected = false;
    private int speed = 0; // in b/s
    private String duplex = null;
    private int signal = 0;

    private CommandExecutorService executorService;

    /**
     * constructor
     *
     * @param ifaceName
     *            - interface name as {@link String}
     * @param executorService
     *            - the {@link org.eclipse.kura.executor.CommandExecutorService} used to run the command
     */
    public IwLinkTool(String ifaceName, CommandExecutorService executorService) {
        this.interfaceName = ifaceName;
        this.duplex = "half";
        this.executorService = executorService;
    }

    @Override
    public boolean get() throws KuraException {
        Command command = new Command(formIwLinkCommand(this.interfaceName));
        command.setTimeout(60);
        command.setOutputStream(new ByteArrayOutputStream());
        CommandStatus status = this.executorService.execute(command);
        int exitValue = (Integer) status.getExitStatus().getExitValue();
        if (exitValue != 0) {
            logger.warn("The iwconfig returned with exit value {}", exitValue);
            return false;
        }
        parse(new String(((ByteArrayOutputStream) status.getOutputStream()).toByteArray(), Charsets.UTF_8));
        return true;
    }

    private boolean parse(String commandOutput) {
        boolean ret = true;
        boolean proceed = true;
        for (String line : commandOutput.split("\n")) {
            line = line.trim();
            if (line.startsWith("Not connected")) {
                proceed = false;
            }
            if (!parseLine(line)) {
                ret = false;
                proceed = false;
            }
            if (!proceed) {
                break;
            }
        }
        return ret;
    }

    private boolean parseLine(String line) {
        if (line.contains("signal:")) {
            // e.g.: signal: -55 dBm
            String[] parts = line.split("\\s");
            try {
                int sig = Integer.parseInt(parts[1]);
                if (sig > -100) {     // TODO: adjust this threshold?
                    this.signal = sig;
                    this.linkDetected = true;
                }
            } catch (NumberFormatException e) {
                logger.debug("Could not parse '{}' as int in line: {}", parts[1], line);
                return false;
            }
        } else if (line.contains("tx bitrate:")) {
            // e.g.: tx bitrate: 1.0 MBit/s
            String[] parts = line.split("\\s");
            try {
                double bitrate = Double.parseDouble(parts[2]);
                if ("MBit/s".equals(parts[3])) {
                    bitrate *= 1000000;
                }
                this.speed = (int) Math.round(bitrate);
            } catch (NumberFormatException e) {
                logger.debug("Could not parse '{}' as double in line: {}", parts[2], line);
                return false;
            }
        }
        return true;
    }

    private String[] formIwLinkCommand(String ifaceName) {
        return new String[] { "iw", ifaceName, "link" };
    }

    @Override
    public String getIfaceName() {
        return this.interfaceName;
    }

    @Override
    public boolean isLinkDetected() {
        return this.linkDetected;
    }

    @Override
    public int getSpeed() {
        return this.speed;
    }

    @Override
    public String getDuplex() {
        return this.duplex;
    }

    @Override
    public int getSignal() {
        return this.signal;
    }
}
