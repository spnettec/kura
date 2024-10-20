/*******************************************************************************
 * Copyright (c) 2015 EclipseSource and others.
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 * Contributors:
 *    Holger Staudacher - initial API and implementation
 *    Ivan Iliev - Performance Optimizations
 ******************************************************************************/
package com.eclipsesource.jaxrs.publisher.internal;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

public class ResourcePublisher {

    private final ServletContainerBridge servletContainerBridge;
    private final ScheduledExecutorService executor;
    private long publishDelay;
    private volatile ScheduledFuture<?> scheduledFuture;

    public ResourcePublisher(ServletContainerBridge servletContainerBridge, long publishDelay) {
        this(createExecutor(), servletContainerBridge, publishDelay);
    }

    ResourcePublisher(ScheduledExecutorService executor, ServletContainerBridge servletContainerBridge,
            long publishDelay) {
        this.servletContainerBridge = servletContainerBridge;
        this.publishDelay = publishDelay;
        this.executor = executor;
    }

    private static ScheduledExecutorService createExecutor() {
        return Executors.newSingleThreadScheduledExecutor(runnable -> {
            Thread thread = new Thread(runnable, "com.eclipsesource.jaxrs.publisher.internal.ResourcePublisher");
            thread.setUncaughtExceptionHandler((thread1, exception) -> {
                throw new IllegalStateException(exception);
            });
            return thread;
        });
    }

    public void setPublishDelay(long publishDelay) {
        this.publishDelay = publishDelay;
    }

    public synchronized void schedulePublishing() {
        if (this.scheduledFuture == null || this.scheduledFuture.isDone()) {

            this.scheduledFuture = this.executor.schedule(this.servletContainerBridge, this.publishDelay,
                    TimeUnit.MILLISECONDS);
        }
    }

    public void shutdown() {
        this.executor.shutdown();
    }

    public void cancelPublishing() {
        if (this.scheduledFuture != null) {
            this.scheduledFuture.cancel(true);
        }
    }
}
