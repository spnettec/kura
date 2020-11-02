/**
 * Copyright (c) 2018, 2020 Eurotech and/or its affiliates and others
 *
 *  All rights reserved. This program and the accompanying materials
 *  are made available under the terms of the Eclipse Public License v1.0
 *  which accompanies this distribution, and is available at
 *  http://www.eclipse.org/legal/epl-v10.html
 *
 */

package org.eclipse.kura.internal.driver.opcua;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.LinkedBlockingDeque;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;
import java.util.function.Supplier;

public class AsyncTaskQueue {

    private final LinkedBlockingDeque<Supplier<CompletableFuture<Void>>> pending = new LinkedBlockingDeque<>();
    private final AtomicBoolean enabled = new AtomicBoolean(true);

    private CompletableFuture<Void> inProgress = CompletableFuture.completedFuture(null);
    private Consumer<Throwable> failureHandler = ex -> {
    };

    private void runNext() {
        if (!this.pending.isEmpty()) {
            this.inProgress = this.pending.pop().get();
        }
    }

    private CompletableFuture<Void> addCompletionHandler(CompletableFuture<Void> task) {
        return task.whenCompleteAsync((ok, err) -> {
            if (err != null && this.enabled.get()) {
                this.failureHandler.accept(err);
            }
        }).thenAcceptAsync(v -> runNext());
    }

    public synchronized void push(final Supplier<CompletableFuture<Void>> next) {
        if (!this.enabled.get()) {
            return;
        }
        if (this.pending.isEmpty() && this.inProgress.isDone()) {
            this.pending.push(() -> addCompletionHandler(next.get()));
            runNext();
        } else {
            this.pending.push(() -> addCompletionHandler(next.get()));
        }
    }

    public void onFailure(Consumer<Throwable> failureHandler) {
        this.failureHandler = failureHandler;
    }

    public synchronized void close(final Supplier<CompletableFuture<Void>> last) {
        this.failureHandler = ex -> {
        };
        this.pending.clear();
        push(() -> {
            this.enabled.set(false);
            return last.get();
        });
    }
}
