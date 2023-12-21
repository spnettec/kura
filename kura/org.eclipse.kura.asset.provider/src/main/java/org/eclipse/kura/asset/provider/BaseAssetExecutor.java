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
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicReference;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.google.common.util.concurrent.SimpleTimeLimiter;
import com.google.common.util.concurrent.TimeLimiter;

public class BaseAssetExecutor {

    private static final Logger logger = LoggerFactory.getLogger(BaseAssetExecutor.class);

    private final ExecutorService ioExecutor;
    private final boolean isIoExecutorShared;

    private final ExecutorService configExecutor;
    private final boolean isConfigExecutorShared;
    private final TimeLimiter ioTimeLimiter;
    private final TimeLimiter configTimeLimiter;

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
        this.ioTimeLimiter = SimpleTimeLimiter.create(ioExecutor);
        this.configTimeLimiter = SimpleTimeLimiter.create(configExecutor);

    }

    public <T> T runIO(final Callable<T> task, long timeOut, TimeUnit timeUnit) throws KuraException {
        try {
            return ioTimeLimiter.callWithTimeout(task, timeOut, timeUnit);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new KuraException(KuraErrorCode.IO_ERROR, "runIo interrupt error", "call Interrupted");
        } catch (TimeoutException e) {
            throw new KuraException(KuraErrorCode.IO_ERROR, "runIo timeout error", "call timeout");
        } catch (Exception e) {
            throw new KuraException(KuraErrorCode.IO_ERROR, "runIo error", "call exception");
        }

    }

    public CompletableFuture<Void> runConfig(final Runnable task, long timeOut, TimeUnit timeUnit) {

        final CompletableFuture<Void> next = new CompletableFuture<>();
        final CompletableFuture<Void> previous = this.queue.getAndSet(next);

        previous.whenComplete((ok, err) -> {
            try {
                configTimeLimiter.runWithTimeout(task, timeOut, timeUnit);
                next.complete(null);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                logger.warn("config task run interrupt failed", e);
                next.completeExceptionally(e);
            } catch (TimeoutException e) {
                logger.warn("config task run timeout failed", e);
                next.completeExceptionally(e);
            } catch (Exception e) {
                logger.warn("config task run failed", e);
                next.completeExceptionally(e);
            }
        });

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
}
