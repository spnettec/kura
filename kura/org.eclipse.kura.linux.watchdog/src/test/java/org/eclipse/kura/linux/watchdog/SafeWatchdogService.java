/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.linux.watchdog;

import java.nio.file.Path;
import java.util.Map;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.core.system.reboot.RebootBrokerClient;

// All executable fixtures fail closed at native and operating-system boundaries.
class SafeWatchdogService extends WatchdogServiceImpl {
    @Override
    protected WatchdogServiceOptions createOptions(Map<String, Object> properties) {
        return new IsolatedWatchdogOptions(properties);
    }

    @Override
    protected WatchdogDevice createWatchdogDevice(String path) throws java.io.IOException, KuraException {
        throw new AssertionError("A test must not open a native watchdog: " + path);
    }

    @Override
    protected void stopWatchdogd() {
        throw new AssertionError("A test must not stop an operating-system service");
    }

    @Override
    protected void runCommand(String command) throws KuraException {
        throw new AssertionError("A test must not dispatch an operating-system command: " + command);
    }

    @Override
    protected Process startCommand(String command) {
        throw new AssertionError("A test must not launch an operating-system process: " + command);
    }

    @Override
    protected RebootBrokerClient.Outcome requestBrokerReboot() {
        throw new AssertionError("A test must not launch the production reboot helper");
    }

    protected final void runDefaultRebootImplementation() throws KuraException {
        super.rebootSystem();
    }

    @Override
    protected synchronized void rebootSystem() throws KuraException {
        throw new AssertionError("A test must not request an operating-system reboot");
    }
}

class IsolatedWatchdogOptions extends WatchdogServiceOptions {
    IsolatedWatchdogOptions(Map<String, Object> properties) {
        super(properties);
    }

    @Override
    public String getWatchdogEnabledTemporaryFilePath() {
        return Path.of("target", "watchdog-unit-marker").toAbsolutePath().toString();
    }
}
