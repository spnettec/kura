/*******************************************************************************
 * Copyright (c) 2021 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.linux.clock;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Date;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.crypto.CryptoService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class ChronyClockSyncProvider implements ClockSyncProvider {

    private static final Logger logger = LoggerFactory.getLogger(ChronyClockSyncProvider.class);

    private final ClockPrivilegeClient clockPrivilegeClient;
    private ScheduledExecutorService schedulerExecutor;
    private ScheduledFuture<?> future;

    private ClockSyncListener listener;

    private String chronyConfig;

    private String chronyServiceName;

    private volatile Date lastSyncValue;

    private long lastStepMonotonicMicros;

    private final Path[] chronyConfigLocations = new Path[] { Paths.get("/etc/chrony.conf"),
            Paths.get("/etc/chrony/chrony.conf") };

    private final CryptoService cryptoService;

    ChronyClockSyncProvider(CryptoService cryptoService, ClockPrivilegeClient clockPrivilegeClient) {
        this.cryptoService = cryptoService;
        this.clockPrivilegeClient = clockPrivilegeClient;
    }

    @Override
    public void init(ClockServiceConfig clockServiceConfig, ScheduledExecutorService scheduler,
            ClockSyncListener listener) throws KuraException {
        this.listener = listener;
        this.schedulerExecutor = scheduler;

        this.chronyConfig = clockServiceConfig.getChronyAdvancedConfig();

        String unit = inspectChrony().unit();
        if (unit.isEmpty()) {
            throw new KuraException(KuraErrorCode.OS_COMMAND_ERROR, "Chrony service unavailable");
        }
        this.chronyServiceName = unit;

        writeConfiguration();
    }

    private void writeConfiguration() throws KuraException {

        if (this.chronyConfig != null && !this.chronyConfig.isEmpty()) {

            Path chronyConfigLocation = null;

            for (Path loc : this.chronyConfigLocations) {
                if (Files.exists(loc)) {
                    chronyConfigLocation = loc;
                    break;
                }
            }

            if (chronyConfigLocation == null) {
                throw new KuraException(KuraErrorCode.CONFIGURATION_ATTRIBUTE_INVALID, "chrony configuration", "....");
            }

            try {
                String chronyConfigLocationContent = new String(Files.readAllBytes(chronyConfigLocation),
                        StandardCharsets.UTF_8);

                if (this.cryptoService.sha256Hash(this.chronyConfig)
                        .equals(this.cryptoService.sha256Hash(chronyConfigLocationContent))) {

                    logger.debug("chrony configuration not changed");
                    return;
                }

                String chronyConfigLocationBackup = chronyConfigLocation.toString() + ".bak";

                logger.info("Saving previous chrony configuration file at {}", chronyConfigLocationBackup);
                Files.copy(chronyConfigLocation, Paths.get(chronyConfigLocationBackup),
                        StandardCopyOption.REPLACE_EXISTING);
                Files.write(chronyConfigLocation, this.chronyConfig.getBytes());
            } catch (IOException e) {
                logger.error("Unable to write chrony configuration file at {}", chronyConfigLocation, e);
            } catch (NoSuchAlgorithmException e) {
                logger.error("Unable to get files hash", e);
            }
        }

    }

    @Override
    public void start() throws KuraException {

        if (!inspectSelectedChrony().active()) {
            logger.info("chrony service down, trying to start...");

            boolean startChronyd = controlChronyd(true);
            if (!startChronyd) {
                logger.error("Unable to start chrony service.");
                throw new KuraException(KuraErrorCode.OS_COMMAND_ERROR, "Unable to start chrony service.");
            }
        } else {
            logger.info("chrony service is up.");
        }

        syncClock();

        this.future = this.schedulerExecutor.scheduleAtFixedRate(this::readAndUpdateSyncInfo, 0, 60, TimeUnit.SECONDS);

    }

    protected boolean syncClock() {

        try {
            if (this.clockPrivilegeClient.stepChrony(this.chronyServiceName)) {
                logger.info("Chrony acknowledged the clock step request");
                readAndUpdateSyncInfo();
                return true;
            }
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
        } catch (IOException error) {
            logger.debug("Unable to confirm the Chrony clock step request", error);
        }
        return false;
    }

    private synchronized void readAndUpdateSyncInfo() {
        ClockPrivilegeClient.ChronyStep step;
        try {
            step = this.clockPrivilegeClient.latestChronyStep();
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            return;
        } catch (IOException error) {
            logger.debug("Unable to read the latest Chrony step", error);
            return;
        }
        if (step.monotonicMicros() <= this.lastStepMonotonicMicros) {
            return;
        }
        logger.info("Last Chrony step was at {}", Instant.EPOCH.plus(step.realtimeMicros(), ChronoUnit.MICROS));
        this.lastStepMonotonicMicros = step.monotonicMicros();
        this.lastSyncValue = new Date(TimeUnit.MICROSECONDS.toMillis(step.realtimeMicros()));
        this.listener.onClockUpdate(0, false);
    }

    @Override
    public void stop() throws KuraException {
        try {
            if (this.chronyServiceName != null) {
                logger.info("Stopping chrony service...");
                if (controlChronyd(false)) {
                    logger.info("chrony service stopped");
                } else {
                    logger.warn("Unable to stop chrony service");
                }
            }
        } finally {
            if (this.future != null) {
                this.future.cancel(true);
            }
        }
    }

    @Override
    public Date getLastSync() {
        return this.lastSyncValue;
    }

    private boolean controlChronyd(boolean running) throws KuraException {
        try {
            return this.clockPrivilegeClient.setChronyRunning(this.chronyServiceName, running);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new KuraException(KuraErrorCode.OS_COMMAND_ERROR, error, "Interrupted during Chrony service control");
        } catch (IOException error) {
            throw new KuraException(KuraErrorCode.OS_COMMAND_ERROR, error, "Unable to confirm Chrony service control");
        }
    }

    private ClockPrivilegeClient.ChronyStatus inspectSelectedChrony() throws KuraException {
        ClockPrivilegeClient.ChronyStatus status = inspectChrony();
        if (!status.unit().equals(this.chronyServiceName)) {
            throw new KuraException(KuraErrorCode.OS_COMMAND_ERROR, "Selected Chrony service changed");
        }
        return status;
    }

    private ClockPrivilegeClient.ChronyStatus inspectChrony() throws KuraException {
        try {
            return this.clockPrivilegeClient.inspectChrony();
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new KuraException(KuraErrorCode.OS_COMMAND_ERROR, error, "Interrupted while inspecting Chrony");
        } catch (IOException error) {
            throw new KuraException(KuraErrorCode.OS_COMMAND_ERROR, error, "Unable to inspect Chrony");
        }

    }
}
