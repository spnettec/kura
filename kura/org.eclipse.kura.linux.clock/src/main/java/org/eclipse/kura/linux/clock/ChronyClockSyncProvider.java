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
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Date;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class ChronyClockSyncProvider implements ClockSyncProvider {

    private static final Logger logger = LoggerFactory.getLogger(ChronyClockSyncProvider.class);

    private final ClockPrivilegeClient clockPrivilegeClient;
    private ScheduledExecutorService schedulerExecutor;
    private ScheduledFuture<?> future;

    private ClockSyncListener listener;

    private String chronyServiceName;
    private boolean managedConfiguration;

    private volatile Date lastSyncValue;

    private long lastStepMonotonicMicros;

    ChronyClockSyncProvider(ClockPrivilegeClient clockPrivilegeClient) {
        this.clockPrivilegeClient = clockPrivilegeClient;
    }

    @Override
    public void init(ClockServiceConfig clockServiceConfig, ScheduledExecutorService scheduler,
            ClockSyncListener listener) throws KuraException {
        this.listener = listener;
        this.schedulerExecutor = scheduler;

        String unit = inspectChrony().unit();
        if (unit.isEmpty()) {
            throw new KuraException(KuraErrorCode.OS_COMMAND_ERROR, "Chrony service unavailable");
        }
        String configuration = clockServiceConfig.getChronyAdvancedConfig();
        writeConfiguration(unit, configuration);
        this.managedConfiguration = configuration != null && !configuration.isEmpty();
        this.chronyServiceName = unit;
    }

    private void writeConfiguration(String unit, String configuration) throws KuraException {
        if (configuration == null || configuration.isEmpty()) {
            return;
        }
        try {
            if (!this.clockPrivilegeClient.configureChrony(unit, configuration)) {
                throw new KuraException(KuraErrorCode.OS_COMMAND_ERROR, "Chrony configuration was not confirmed");
            }
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new KuraException(KuraErrorCode.OS_COMMAND_ERROR, error, "Interrupted during Chrony configuration");
        } catch (IllegalArgumentException error) {
            throw new KuraException(KuraErrorCode.CONFIGURATION_ATTRIBUTE_INVALID, error, "chrony.advanced.config",
                    "Invalid Chrony configuration");
        } catch (IOException error) {
            throw new KuraException(KuraErrorCode.OS_COMMAND_ERROR, error, "Unable to confirm Chrony configuration");
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

        // With a managed profile Chrony applies its own configured step policy.
        // Configuration admission does not implicitly issue another clock write.
        if (!this.managedConfiguration) {
            syncClock();
        }

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
