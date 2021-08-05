/*******************************************************************************
 * Copyright (c) 2018, 2020 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.asset.provider;

import java.util.concurrent.Callable;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicReference;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class BaseAssetExecutor {

    private static final Logger logger = LoggerFactory.getLogger(BaseAssetExecutor.class);

    private final ExecutorService ioExecutor;
    private final boolean isIoExecutorShared;

    private final ExecutorService configExecutor;
    private final boolean isConfigExecutorShared;

    private final AtomicReference<CompletableFuture<Void>> queue = new AtomicReference<>(
            CompletableFuture.completedFuture(null));

    public BaseAssetExecutor(final ExecutorService ioExecutor, final ExecutorService configExecutor) {
        this(ioExecutor, false, configExecutor, false);
    }

    public BaseAssetExecutor(final ExecutorService ioExecutor, final boolean isIoExecutorShared,
            final ExecutorService configExecutor, final boolean isConfigExecutorShared) {
        this.ioExecutor = ioExecutor;
        this.isIoExecutorShared = isIoExecutorShared;
        this.configExecutor = configExecutor;
        this.isConfigExecutorShared = isConfigExecutorShared;
    }

    public <T> CompletableFuture<T> runIO(final Callable<T> task) {
        final CompletableFuture<T> result = new CompletableFuture<>();

        this.ioExecutor.execute(() -> {
            try {
                result.complete(task.call());
            } catch (Exception e) {
                result.completeExceptionally(e);
            }
        });

        return result;
    }

    public <T> CompletableFuture<T> runIO(final Callable<T> task, long timeOut, TimeUnit timeUnit) {
        final CompletableFuture<T> result = new CompletableFuture<>();

        this.ioExecutor.execute(() -> {
            try {
                result.complete(runWithTimeout(task, timeOut, timeUnit));
            } catch (Exception e) {
                result.completeExceptionally(e);
            }
        });

        return result;
    }

    public CompletableFuture<Void> runConfig(final Runnable task) {

        final CompletableFuture<Void> next = new CompletableFuture<>();
        final CompletableFuture<Void> previous = this.queue.getAndSet(next);

        previous.whenComplete((ok, err) -> this.configExecutor.execute(() -> {
            try {
                task.run();
                next.complete(null);
            } catch (Exception e) {
                logger.warn("Asset task failed", e);
                next.completeExceptionally(e);
            }
        }));

        return next;
    }

    public CompletableFuture<Void> runConfig(final Runnable task, long timeOut, TimeUnit timeUnit) {

        final CompletableFuture<Void> next = new CompletableFuture<>();
        final CompletableFuture<Void> previous = this.queue.getAndSet(next);

        previous.whenComplete((ok, err) -> this.configExecutor.execute(() -> {
            try {
                runWithTimeout(task, timeOut, timeUnit);
                next.complete(null);
            } catch (Exception e) {
                logger.warn("Asset task failed", e);
                next.completeExceptionally(e);
            }
        }));

        return next;
    }

    public void shutdown() {
        if (!this.isIoExecutorShared) {
            this.ioExecutor.shutdown();
        }
        if (!this.isConfigExecutorShared) {
            this.configExecutor.shutdown();
        }
    }

    public static void runWithTimeout(final Runnable runnable, long timeout, TimeUnit timeUnit) throws Exception {
        runWithTimeout(new Callable<Object>() {

            @Override
            public Object call() throws Exception {
                runnable.run();
                return null;
            }
        }, timeout, timeUnit);
    }

    public static <T> T runWithTimeout(Callable<T> callable, long timeout, TimeUnit timeUnit) throws Exception {
        final ExecutorService executor = Executors.newSingleThreadExecutor();
        final Future<T> future = executor.submit(callable);
        executor.shutdown(); // This does not cancel the already-scheduled task.
        try {
            return future.get(timeout, timeUnit);
        } catch (TimeoutException e) {
            // remove this if you do not want to cancel the job in progress
            // or set the argument to 'false' if you do not want to interrupt the thread
            future.cancel(true);
            throw e;
        } catch (ExecutionException e) {
            // unwrap the root cause
            Throwable t = e.getCause();
            if (t instanceof Error) {
                throw (Error) t;
            } else if (t instanceof Exception) {
                throw (Exception) t;
            } else {
                throw new IllegalStateException(t);
            }
        }
    }

}
