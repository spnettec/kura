/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.testutil.http;

import java.io.Closeable;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;

import com.sun.net.httpserver.HttpServer;

/** Local CRL/download fixture, independent of Jetty, Eclipse and production ports. */
public final class TestServer implements Closeable {
    private final HttpServer server;
    private final ExecutorService executor = Executors.newVirtualThreadPerTaskExecutor();
    private final Map<String, byte[]> resources = new ConcurrentHashMap<>();
    private final AtomicReference<CountDownLatch> stall = new AtomicReference<>();

    public TestServer(int port, Optional<Consumer<String>> listener) throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.setExecutor(executor);
        server.createContext("/", exchange -> {
            try (exchange) {
                String path = exchange.getRequestURI().getPath();
                listener.ifPresent(l -> l.accept(path));
                CountDownLatch latch = stall.getAndSet(null);
                if (latch != null) {
                    try {
                        if (!latch.await(30, TimeUnit.SECONDS)) {
                            exchange.sendResponseHeaders(504, -1);
                            return;
                        }
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        return;
                    }
                }
                byte[] body = resources.get(path);
                if (body == null) {
                    exchange.sendResponseHeaders(404, -1);
                } else {
                    exchange.getResponseHeaders().set("Content-Type", "application/pkix-crl");
                    exchange.sendResponseHeaders(200, body.length);
                    exchange.getResponseBody().write(body);
                }
            }
        });
        server.start();
    }

    public int getPort() { return server.getAddress().getPort(); }

    public void setResource(String path, byte[] body) { resources.put(path, body.clone()); }

    public CountDownLatch stallNextRequest() {
        CountDownLatch latch = new CountDownLatch(1);
        if (!stall.compareAndSet(null, latch)) {
            throw new IllegalStateException("A request is already scheduled to stall");
        }
        return latch;
    }

    @Override
    public void close() {
        CountDownLatch latch = stall.getAndSet(null);
        if (latch != null) { latch.countDown(); }
        server.stop(0);
        executor.shutdownNow();
    }
}
