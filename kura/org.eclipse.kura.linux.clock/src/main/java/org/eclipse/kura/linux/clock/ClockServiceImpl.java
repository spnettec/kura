/*******************************************************************************
 * Copyright (c) 2011, 2025 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 *  Red Hat Inc
 *******************************************************************************/
package org.eclipse.kura.linux.clock;

import java.io.IOException;
import java.util.Collections;
import java.util.Date;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.clock.ClockEvent;
import org.eclipse.kura.clock.ClockService;
import org.eclipse.kura.configuration.ConfigurableComponent;
import org.osgi.service.event.EventAdmin;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class ClockServiceImpl implements ConfigurableComponent, ClockService, ClockSyncListener {

    private static final ClockEvent EMPTY_EVENT = new ClockEvent(Collections.emptyMap());

    private static final Logger logger = LoggerFactory.getLogger(ClockServiceImpl.class);

    private EventAdmin eventAdmin;
    private org.eclipse.kura.system.SystemService systemService;
    private ClockPrivilegeClient clockPrivilegeClient;
    private ClockSyncProvider provider;
    private ClockSyncProvider callbackSource;

    private ClockServiceConfig clockServiceConfig;
    private final ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor();

    // ----------------------------------------------------------------
    //
    // Dependencies
    //
    // ----------------------------------------------------------------

    public void setEventAdmin(EventAdmin eventAdmin) {
        this.eventAdmin = eventAdmin;
    }

    public void unsetEventAdmin(EventAdmin eventAdmin) {
        this.eventAdmin = null;
    }

    public void setSystemService(org.eclipse.kura.system.SystemService systemService) {
        this.systemService = systemService;
    }

    protected ClockPrivilegeClient createClockPrivilegeClient() {
        if (this.systemService == null) {
            throw new IllegalArgumentException("SystemService is required for durable clock decisions");
        }
        return new ClockPrivilegeClient(this.systemService.getKuraDataDirectory());
    }

    private ClockPrivilegeClient clockPrivilegeClient() {
        if (this.clockPrivilegeClient == null) {
            this.clockPrivilegeClient = createClockPrivilegeClient();
        }
        return this.clockPrivilegeClient;
    }

    // ----------------------------------------------------------------
    //
    // Activation APIs
    //
    // ----------------------------------------------------------------

    protected void activate(Map<String, Object> properties) {
        logger.info("Activate. Current Time: {}", new Date());

        // save the properties
        this.clockServiceConfig = new ClockServiceConfig(properties);

        if (this.clockServiceConfig.isEnabled()) {
            // start the provider
            try {
                startClockSyncProvider();
            } catch (KuraException t) {
                logger.error("Error updating ClockService Configuration", t);
            }
        }
    }

    protected void deactivate() {
        logger.info("Deactivate...");
        try {
            stopClockSyncProvider();
        } catch (KuraException t) {
            logger.error("Error deactivating ClockSyncProvider", t);
        }
        this.scheduler.shutdown();
        try {
            if (!this.scheduler.awaitTermination(1, TimeUnit.SECONDS)) {
                this.scheduler.shutdownNow();
            }
        } catch (InterruptedException e) {
            logger.warn("Interrupted clock service scheduler shutdown!", e);
            this.scheduler.shutdownNow();
            Thread.currentThread().interrupt();
        }
    }

    public void updated(Map<String, Object> properties) {
        logger.info("Updated...");

        // save the properties
        ClockServiceConfig newClockServiceConfig = new ClockServiceConfig(properties);
        if (newClockServiceConfig.equals(this.clockServiceConfig)) {
            return;
        }
        logger.info("New configuration for Clock Service");
        // Drain any sample already being applied before publishing the new RTC selection.
        setCallbackSource(null);
        this.clockServiceConfig = newClockServiceConfig;

        if (this.clockServiceConfig.isEnabled()) {
            try {
                // start the provider
                startClockSyncProvider();
            } catch (KuraException t) {
                logger.error("Error updating ClockService Configuration", t);
            }
        } else {
            // stop the provider if it was running
            try {
                stopClockSyncProvider();
            } catch (KuraException t) {
                logger.error("Error deactivate ClockService", t);
            }
        }
    }

    // ----------------------------------------------------------------
    //
    // Master Client Management APIs
    //
    // ----------------------------------------------------------------

    @Override
    public Date getLastSync() throws KuraException {
        if (this.provider != null) {
            return this.provider.getLastSync();
        } else {
            throw new KuraException(KuraErrorCode.SERVICE_UNAVAILABLE, "Clock service not configured yet");
        }
    }

    // ----------------------------------------------------------------
    //
    // Private Methods
    //
    // ----------------------------------------------------------------

    private void startClockSyncProvider() throws KuraException {
        stopClockSyncProvider();
        String sprovider = this.clockServiceConfig.getClockProvider();

        switch (ClockProviderType.fromValue(sprovider)) {
        case JAVA_NTP:
            this.provider = new JavaNtpClockSyncProvider();
            break;
        case NTPD:
            logger.error("NTPD clock provider is not supported anymore. Use JAVA_NTP or CHRONY_ADVANCED instead.");
            return;
        case CHRONY_ADVANCED:
            this.provider = new ChronyClockSyncProvider(clockPrivilegeClient());
            break;

        default:
            throw new KuraException(KuraErrorCode.CONFIGURATION_ATTRIBUTE_INVALID);
        }

        ClockSyncProvider source = this.provider;
        source.init(this.clockServiceConfig, this.scheduler, new ClockSyncListener() {

            @Override
            public void onClockUpdate(long offset, boolean changeSystemClock) {
                onProviderUpdate(source, offset, changeSystemClock, null);
            }

            @Override
            public void applyNtpSample(long offset, Runnable recordSynchronization) {
                onProviderUpdate(source, offset, true, recordSynchronization);
            }
        });
        setCallbackSource(source);
        try {
            source.start();
        } catch (KuraException | RuntimeException e) {
            setCallbackSource(null);
            throw e;
        }
    }

    private synchronized void setCallbackSource(ClockSyncProvider source) {
        this.callbackSource = source;
    }

    private synchronized void onProviderUpdate(ClockSyncProvider source, long offset, boolean changeSystemClock,
            Runnable recordSynchronization) {
        if (source == this.callbackSource) {
            applyClockUpdate(offset, changeSystemClock, recordSynchronization);
        }
    }

    private void stopClockSyncProvider() throws KuraException {
        setCallbackSource(null);
        if (this.provider != null) {
            this.provider.stop();
            this.provider = null;
        }
    }

    /**
     * Called by the current ClockSyncProvider after each Clock synchronization
     */
    @Override
    public void onClockUpdate(long offset, boolean changeSystemClock) {
        applyClockUpdate(offset, changeSystemClock, null);
    }

    private void applyClockUpdate(long offset, boolean changeSystemClock, Runnable recordSynchronization) {

        logger.info("Clock update. Offset: {}", offset);

        // set system clock if necessary
        boolean bClockUpToDate = false;
        if (offset != 0 && changeSystemClock) {
            try {
                bClockUpToDate = clockPrivilegeClient().adjustRealtime(offset);
                if (bClockUpToDate) {
                    logger.info("System Clock Updated to {}", new Date());
                } else {
                    logger.warn("Clock sample was not applied; preserve the original broker decision");
                }
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                logger.warn("Clock broker interrupted; preserve the original decision");
            } catch (IOException | IllegalArgumentException error) {
                logger.error("Clock broker unavailable; preserve the original decision", error);
            }
        } else {
            bClockUpToDate = true;
        }

        if (this.clockServiceConfig.isHwclockEnabled() && changeSystemClock && bClockUpToDate) {
            try {
                if (clockPrivilegeClient().syncRtc(this.clockServiceConfig.getRtcFilename())) {
                    logger.info("Hardware Clock Updated");
                } else {
                    logger.warn("RTC synchronization was not applied; preserve the original broker decision");
                }
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                logger.warn("RTC broker interrupted; preserve the original decision");
            } catch (IOException | IllegalArgumentException error) {
                logger.error("RTC broker unavailable; preserve the original decision", error);
            }
        }

        // Raise the event
        if (bClockUpToDate) {
            if (recordSynchronization != null) {
                recordSynchronization.run();
            }
            this.eventAdmin.postEvent(EMPTY_EVENT);
        }
    }

}
