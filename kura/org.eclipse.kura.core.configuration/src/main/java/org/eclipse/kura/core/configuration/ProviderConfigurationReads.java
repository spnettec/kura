/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;

/** Bounds work launched for synchronous provider snapshots; cancellation remains cooperative. */
final class ProviderConfigurationReads implements AutoCloseable {
    static final class Unavailable extends KuraException {
        private static final long serialVersionUID = 1L;
        Unavailable(String reason) { super(KuraErrorCode.CONFIGURATION_ERROR, reason); }
    }
    interface Budget extends AutoCloseable { @Override void close(); }
    private static final class Context {
        final long deadline;
        final boolean callback;
        final Set<Object> active = new HashSet<>();
        Context(long deadline, boolean callback) { this.deadline=deadline; this.callback=callback; }
    }
    private final ThreadLocal<Context> context = new ThreadLocal<>();
    private final ConcurrentMap<Object, Task<?>> inFlight = new ConcurrentHashMap<>();
    private final AtomicBoolean closed = new AtomicBoolean();
    private final ThreadPoolExecutor executor;
    private final long timeoutNanos;

    ProviderConfigurationReads() { this(2000, 2, 2); }
    ProviderConfigurationReads(long timeoutMillis, int workers, int queued) {
        this.timeoutNanos=TimeUnit.MILLISECONDS.toNanos(timeoutMillis);
        AtomicInteger sequence=new AtomicInteger();
        this.executor=new ThreadPoolExecutor(workers, workers, 30, TimeUnit.SECONDS,
                new ArrayBlockingQueue<>(queued), action -> {
                    Thread thread=new Thread(action,"kura-configuration-provider-"+sequence.incrementAndGet());
                    thread.setDaemon(true); return thread;
                }, new ThreadPoolExecutor.AbortPolicy());
        this.executor.allowCoreThreadTimeOut(true);
    }

    Budget budget() {
        if (this.context.get()!=null) { return () -> {}; }
        this.context.set(new Context(System.nanoTime()+this.timeoutNanos,false));
        return this.context::remove;
    }

    private void requireTime(Context current) throws Unavailable {
        if (this.closed.get()) { throw new Unavailable("Provider reads are stopped"); }
        if (current.deadline-System.nanoTime()<=0) { throw new Unavailable("Provider read deadline expired"); }
    }

    <T> T read(Object key, Callable<T> operation) throws KuraException {
        try (Budget ignored=budget()) {
            Context current=this.context.get(); requireTime(current);
            if (current.callback) {
                // Aggregating read-only providers can query another provider without allocating another worker.
                // Cycles and excessive nesting fail closed instead of consuming the whole worker pool.
                if (current.active.size()>=8 || !current.active.add(key)) {
                    throw new Unavailable("Recursive provider read limit reached");
                }
                try { return call(operation); } finally { current.active.remove(key); }
            }
            Task<T> task=new Task<>(key, () -> {
                Context worker=new Context(current.deadline,true); worker.active.add(key);
                this.context.set(worker);
                try { requireTime(worker); return operation.call(); }
                finally { this.context.remove(); }
            });
            if (this.inFlight.putIfAbsent(key,task)!=null) {
                throw new Unavailable("Provider read is still running");
            }
            try { this.executor.execute(task); }
            catch (RejectedExecutionException rejected) {
                this.inFlight.remove(key,task); throw new Unavailable("Provider read capacity exhausted");
            }
            try { return task.get(Math.max(1,current.deadline-System.nanoTime()),TimeUnit.NANOSECONDS); }
            catch (TimeoutException timeout) {
                cancel(task); throw new Unavailable("Provider read deadline expired");
            } catch (InterruptedException interrupted) {
                cancel(task); Thread.currentThread().interrupt();
                throw new Unavailable("Provider read interrupted");
            } catch (CancellationException cancelled) {
                throw new Unavailable("Provider read stopped");
            } catch (ExecutionException failure) {
                Throwable cause=failure.getCause();
                if (cause instanceof KuraException kura) { throw kura; }
                if (cause instanceof RuntimeException runtime) { throw runtime; }
                if (cause instanceof Error error) { throw error; }
                throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR,cause);
            }
        }
    }

    private <T> T call(Callable<T> operation) throws KuraException {
        try { return operation.call(); }
        catch (KuraException failure) { throw failure; }
        catch (RuntimeException failure) { throw failure; }
        catch (Exception failure) { throw new KuraException(KuraErrorCode.CONFIGURATION_ERROR,failure); }
    }
    private void cancel(Task<?> task) {
        task.cancel(true);
        if (this.executor.remove(task)) { this.inFlight.remove(task.key,task); }
    }
    private final class Task<T> extends FutureTask<T> {
        private final Object key;
        Task(Object key,Callable<T> operation) { super(operation); this.key=key; }
        @Override protected void set(T result) { inFlight.remove(this.key,this); super.set(result); }
        @Override protected void setException(Throwable failure) {
            inFlight.remove(this.key,this); super.setException(failure);
        }
        @Override public void run() { try { super.run(); } finally { inFlight.remove(this.key,this); } }
    }
    @Override public void close() {
        if (!this.closed.compareAndSet(false,true)) { return; }
        for (Task<?> task:this.inFlight.values()) { cancel(task); }
        this.executor.shutdownNow();
    }
}
