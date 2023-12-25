package org.eclipse.kura.nm.signal.handlers;

import java.util.Objects;
import java.util.concurrent.CompletableFuture;

import org.eclipse.kura.nm.NMDbusConnector;
import org.freedesktop.dbus.exceptions.DBusException;
import org.freedesktop.dbus.interfaces.DBusSigHandler;
import org.freedesktop.dbus.types.Variant;
import org.freedesktop.networkmanager.device.Wired;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class ConnectionStateChangedHandle implements DBusSigHandler<Wired.PropertiesChanged> {

    private static final Logger logger = LoggerFactory.getLogger(ConnectionStateChangedHandle.class);
    private final NMDbusConnector nm;

    public ConnectionStateChangedHandle(NMDbusConnector connector) {
        this.nm = Objects.requireNonNull(connector);
    }

    @Override
    public void handle(Wired.PropertiesChanged s) {
        Variant<?> varConnected = s.getProperties().get("Carrier");
        if (varConnected != null) {

            if (varConnected.getValue() == Boolean.TRUE) {

                CompletableFuture.runAsync(() -> {
                    try {
                        String deviceId = ConnectionStateChangedHandle.this.nm.getInterfaceIdByDBusPath(s.getPath());
                        logger.info("{} connected!!!!", deviceId);
                        ConnectionStateChangedHandle.this.nm.apply(deviceId);
                    } catch (DBusException e) {
                        logger.error("Failed to handle connect event for device: {}. Caused by:", s.getPath(), e);
                    }
                });
            } else {

                CompletableFuture.runAsync(() -> {
                    try {
                        String deviceId = ConnectionStateChangedHandle.this.nm.getInterfaceIdByDBusPath(s.getPath());
                        logger.info("{} disConnected!!!!", deviceId);
                        ConnectionStateChangedHandle.this.nm.disconnect(deviceId);
                    } catch (DBusException e) {
                        logger.error("Failed to handle disconnect event for device: {}. Caused by:", s.getPath(), e);
                    }
                });
            }
        }

    }
}