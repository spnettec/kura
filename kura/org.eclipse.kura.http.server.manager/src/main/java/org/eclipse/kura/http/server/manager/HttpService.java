/*******************************************************************************
 * Copyright (c) 2019, 2025 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.http.server.manager;

import java.util.EventListener;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

import org.eclipse.kura.configuration.ConfigurableComponent;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.security.keystore.KeystoreChangedEvent;
import org.eclipse.kura.security.keystore.KeystoreService;
import org.osgi.service.event.Event;
import org.osgi.service.event.EventHandler;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import jakarta.servlet.http.HttpServlet;

public class HttpService implements ConfigurableComponent, EventHandler {

    private static final Logger logger = LoggerFactory.getLogger(HttpService.class);

    private HttpServiceOptions options;

    private KeystoreService keystoreService;
    private HttpServlet dispatcherServlet;
    private EventListener eventListener;

    private String keystoreServicePid;

    private JettyServerHolder jettyServerHolder;
    private boolean refreshQueued;
    private final ScheduledExecutorService executorService = Executors.newSingleThreadScheduledExecutor();
    private Future<?> restartTask = CompletableFuture.completedFuture(null);

    public void setDispatcherServlet(HttpServlet dispatcherServlet) {
        this.dispatcherServlet = dispatcherServlet;
    }

    public void setEventListener(EventListener eventListener) {
        this.eventListener = eventListener;
    }

    public synchronized void activate(Map<String, Object> properties) {
        logger.info("Activating {}", this.getClass().getSimpleName());

        this.options = new HttpServiceOptions(properties);

        if (this.keystoreService == null) {
            this.restartTask = this.executorService.schedule(this::startWithoutKeystore, 12, TimeUnit.SECONDS);
            logger.info("Activating... Done. Waiting for KeystoreService");
        } else {
            refreshHttpService();
            logger.info("Activating... Done.");
        }
    }

    public synchronized void updated(Map<String, Object> properties) {
        logger.info("Updating {}", this.getClass().getSimpleName());

        HttpServiceOptions updatedOptions = new HttpServiceOptions(properties);

        if (!this.options.equals(updatedOptions)) {
            logger.debug("Updating, new props");
            this.options = updatedOptions;

            cancelRestartTask();
            refreshHttpService();
        }

        logger.info("Updating... Done.");
    }

    public void deactivate() {
        logger.info("Deactivating {}", this.getClass().getSimpleName());

        synchronized (this) {
            if (this.executorService.isShutdown()) {
                return;
            }
            this.options = null;
            cancelRestartTask();
            this.executorService.execute(this::stopHttpService);
            this.executorService.shutdown();
        }
        awaitExecutorShutdown();
    }

    private synchronized void refreshHttpService() {
        if (this.options != null && !this.refreshQueued) {
            this.refreshQueued = true;
            this.executorService.execute(this::applyHttpConfiguration);
        }
    }

    private void applyHttpConfiguration() {
        boolean stopped = stopHttpService();
        final HttpServiceOptions currentOptions;
        final KeystoreService currentKeystore;
        synchronized (this) {
            this.refreshQueued = false;
            currentOptions = this.options;
            currentKeystore = this.keystoreService;
        }
        if (!stopped || currentOptions == null) {
            return;
        }
        try {
            logger.info("starting Jetty instance...");
            this.jettyServerHolder = new JettyServerHolder(currentOptions, Optional.ofNullable(currentKeystore),
                    this.dispatcherServlet, this.eventListener);
            logger.info("starting Jetty instance...done");
        } catch (final Exception e) {
            logger.error("Could not start Jetty Web server", e);
        }
    }

    private boolean stopHttpService() {
        if (this.jettyServerHolder == null) {
            return true;
        }
        try {
            logger.info("stopping Jetty instance...");
            this.jettyServerHolder.stop();
            this.jettyServerHolder = null;
            return true;
        } catch (final Exception e) {
            logger.error("Could not stop Jetty Web server", e);
            return false;
        }
    }

    private void awaitExecutorShutdown() {
        try {
            if (!this.executorService.awaitTermination(30, TimeUnit.SECONDS)) {
                logger.error("Timed out stopping the HTTP service executor");
            }
        } catch (final InterruptedException e) {
            Thread.currentThread().interrupt();
            logger.error("Could not stop executor", e);
        } finally {
            this.executorService.shutdownNow();
        }
    }

    private synchronized void cancelRestartTask() {
        if (!this.restartTask.isDone()) {
            this.restartTask.cancel(false);
        }
    }

    private synchronized void scheduleDeferredRestart() {
        cancelRestartTask();
        this.restartTask = this.executorService.schedule(this::refreshHttpService, 10, TimeUnit.SECONDS);
    }

    private synchronized void startWithoutKeystore() {
        if (this.options != null && this.keystoreService == null) {
            logger.warn("KeystoreService not available. Starting without HTTPS.");
            refreshHttpService();
        }
    }

    public synchronized void setKeystoreService(KeystoreService keystoreService, final Map<String, Object> properties) {
        boolean changed = this.keystoreService != keystoreService;
        this.keystoreService = keystoreService;
        this.keystoreServicePid = (String) properties.get(ConfigurationService.KURA_SERVICE_PID);

        if (this.options != null && changed) {
            cancelRestartTask();
            refreshHttpService();
        }
    }

    public synchronized void unsetKeystoreService(KeystoreService keystoreService) {
        // SCR can bind the replacement before unbinding the old service.
        if (this.keystoreService == keystoreService) {
            this.keystoreService = null;
            this.keystoreServicePid = null;
            if (this.options != null) {
                cancelRestartTask();
                refreshHttpService();
            }
        }
    }

    @Override
    public synchronized void handleEvent(final Event event) {
        if (this.options != null && this.keystoreServicePid != null
                && event instanceof KeystoreChangedEvent changed
                && this.keystoreServicePid.equals(changed.getSenderPid())) {
            scheduleDeferredRestart();
        }
    }

}
