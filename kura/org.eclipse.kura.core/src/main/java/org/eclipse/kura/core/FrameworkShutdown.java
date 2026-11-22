/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core;

import org.osgi.framework.BundleActivator;
import org.osgi.framework.BundleContext;
import org.osgi.framework.BundleException;
import org.osgi.framework.FrameworkEvent;
import org.osgi.framework.launch.Framework;

/** Stops Equinox on JVM termination when the packaged Kura profile owns it. */
public final class FrameworkShutdown implements BundleActivator {

    private static final String STOP_ON_JVM_SHUTDOWN = "kura.osgi.stopOnJvmShutdown";
    private static final long FRAMEWORK_STOP_TIMEOUT_MS = 50_000;

    private Thread shutdownHook;

    @Override
    public void start(BundleContext context) {
        if (!Boolean.parseBoolean(context.getProperty(STOP_ON_JVM_SHUTDOWN))) {
            return;
        }
        Framework framework = context.getBundle(0).adapt(Framework.class);
        if (framework == null) {
            throw new IllegalStateException("The system bundle does not expose the OSGi framework");
        }
        Thread hook = new Thread(() -> stopFramework(framework), "Kura OSGi shutdown");
        Runtime.getRuntime().addShutdownHook(hook);
        this.shutdownHook = hook;
    }

    @Override
    public void stop(BundleContext context) {
        Thread hook = this.shutdownHook;
        this.shutdownHook = null;
        if (hook == null) {
            return;
        }
        try {
            Runtime.getRuntime().removeShutdownHook(hook);
        } catch (IllegalStateException shutdownInProgress) {
            // The JVM is already running its hooks, including this framework stop.
        }
    }

    private static void stopFramework(Framework framework) {
        try {
            framework.stop();
            FrameworkEvent stopped = framework.waitForStop(FRAMEWORK_STOP_TIMEOUT_MS);
            if (stopped.getType() == FrameworkEvent.WAIT_TIMEDOUT || stopped.getType() == FrameworkEvent.ERROR) {
                System.err.println("Kura OSGi shutdown did not complete, event " + stopped.getType());
            }
        } catch (BundleException error) {
            System.err.println("Kura OSGi shutdown failed: " + error.getMessage());
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            System.err.println("Kura OSGi shutdown was interrupted");
        }
    }
}
