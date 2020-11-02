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

import java.util.ArrayDeque;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;
import java.util.function.Supplier;

public class AsyncTaskQueue {

    private final ArrayDeque<Supplier<CompletableFuture<Void>>> pending = new ArrayDeque<>();
    private final AtomicBoolean enabled = new AtomicBoolean(true);
    private final AtomicBoolean running = new AtomicBoolean(false);

    private CompletableFuture<Void> inProgress = CompletableFuture.completedFuture(null);
    private Consumer<Throwable> failureHandler = ex -> {
    };

    private synchronized void runNext() {
        this.enabled.set(true);
        if (!this.pending.isEmpty()) {
            while (!this.inProgress.isDone()) {
                try {
                    wait(500);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
            this.inProgress = this.pending.pop().get();
        }
        this.enabled.set(false);
    }

    private CompletableFuture<Void> addCompletionHandler(CompletableFuture<Void> task) {
        return task.whenComplete((ok, err) -> {
            if (err != null && this.enabled.get()) {
                this.failureHandler.accept(err);
            }
            runNext();
        });
    }

    public synchronized void push(final Supplier<CompletableFuture<Void>> next) {
        if (!this.enabled.get()) {
            return;
        }
        this.pending.push(() -> addCompletionHandler(next.get()));
        if (!this.running.get()) {
            runNext();
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
