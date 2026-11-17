/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.linux.clock;

import java.lang.reflect.Proxy;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import org.eclipse.kura.system.SystemService;
import org.osgi.service.event.Event;
import org.osgi.service.event.EventAdmin;

import com.google.gson.JsonObject;

/** Explicit VM fixture entrypoint; never started by ordinary JVM tests. */
public final class ClockProviderLinuxProbe {

    public static void main(String[] args) throws Exception {
        if (args.length != 3 || !System.getProperty("os.name").equals("Linux")) {
            throw new IllegalArgumentException("Expected data directory, runtime directory and outcome in a dedicated VM");
        }
        Path data = Path.of(args[0]);
        Path runtime = Path.of(args[1]);
        if (!Files.isDirectory(data) || !Files.isDirectory(runtime) || Files.exists(runtime.resolve("ready"))
                || Files.exists(runtime.resolve("result.json"))) {
            throw new IllegalStateException("Fresh owned fixture paths are required");
        }
        ClockServiceImpl service = new ClockServiceImpl();
        AtomicInteger events = new AtomicInteger();
        service.setEventAdmin(new EventAdmin() {
            @Override public void postEvent(Event event) { events.incrementAndGet(); }
            @Override public void sendEvent(Event event) { throw new AssertionError("Unexpected synchronous event"); }
        });
        service.setSystemService((SystemService) Proxy.newProxyInstance(SystemService.class.getClassLoader(),
                new Class<?>[] { SystemService.class }, (proxy, method, values) -> {
                    if (method.getName().equals("getKuraDataDirectory")) {
                        return data.toString();
                    }
                    throw new UnsupportedOperationException(method.getName());
                }));
        service.activate(Map.of("enabled", false, "clock.set.hwclock", false));
        Files.writeString(runtime.resolve("ready"), Long.toString(ProcessHandle.current().pid()));
        long until = System.nanoTime() + 120_000_000_000L;
        while (!Files.isRegularFile(runtime.resolve("dispatch"))) {
            if (System.nanoTime() > until) {
                throw new IllegalStateException("No explicit VM-only clock dispatch");
            }
            Thread.sleep(50);
        }
        long wallBefore = System.currentTimeMillis();
        long monoBefore = System.nanoTime();
        // A 1 ms correction is confined to the Parallels guest. No shared
        // OrbStack kernel or host clock may be used for this entrypoint.
        service.onClockUpdate(1, true);
        long monoAfter = System.nanoTime();
        long wallAfter = System.currentTimeMillis();
        JsonObject result = new JsonObject();
        result.addProperty("pid", ProcessHandle.current().pid());
        result.addProperty("clockEvents", events.get());
        result.addProperty("wallBeforeMillis", wallBefore);
        result.addProperty("wallAfterMillis", wallAfter);
        result.addProperty("elapsedMonotonicNs", monoAfter - monoBefore);
        result.addProperty("expected", args[2]);
        result.addProperty("clockCodeSource", ClockServiceImpl.class.getProtectionDomain().getCodeSource().getLocation().toExternalForm());
        result.addProperty("scope", "actual ClockServiceImpl and typed actor only; not complete Kura/OSGi");
        Files.writeString(runtime.resolve("result.json"), result.toString());
        if (events.get() != (args[2].equals("APPLIED") ? 1 : 0)) {
            throw new AssertionError("Clock event disagrees with requested fixture outcome");
        }
        while (!Files.isRegularFile(runtime.resolve("stop"))) {
            Thread.sleep(100);
        }
        service.deactivate();
    }
}
