/*******************************************************************************
 * Copyright (c) 2017, 2026 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 ******************************************************************************/
package org.eclipse.kura.emulator.position;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.isA;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.net.MalformedURLException;
import java.net.URL;
import java.util.HashMap;
import java.util.Map;

import org.eclipse.kura.core.testutil.TestUtil;
import org.eclipse.kura.position.NmeaPosition;
import org.eclipse.kura.position.PositionLockedEvent;
import org.junit.jupiter.api.Test;
import org.osgi.framework.Bundle;
import org.osgi.framework.BundleContext;
import org.osgi.service.component.ComponentContext;
import org.osgi.service.event.EventAdmin;
import org.osgi.util.position.Position;

public class PositionServiceImplTest {

    private final java.util.List<java.util.concurrent.ScheduledExecutorService> workers = new java.util.ArrayList<>();

    @org.junit.jupiter.api.AfterEach
    void stopWorkers() throws Exception {
        for (java.util.concurrent.ScheduledExecutorService worker : workers) {
            worker.shutdownNow();
            assertTrue(worker.awaitTermination(5, java.util.concurrent.TimeUnit.SECONDS));
        }
    }

    private static final String USE_GPSD = "useGpsd";

    @Test
    public void testActivateReadDeactivate() throws Exception {
        // test service activation, wait for position, deactivate

        PositionServiceImpl svc = new PositionServiceImpl();

        Bundle bMock = initBundleMock();

        ComponentContext ccMock = initComponentContextMock(bMock);

        EventAdmin eaMock = mock(EventAdmin.class);
        svc.setEventAdmin(eaMock);

        Map<String, Object> properties = new HashMap<>();
        properties.put(USE_GPSD, true);

        svc.activate(ccMock, properties);
        workers.add((java.util.concurrent.ScheduledExecutorService) TestUtil.getFieldValue(svc, "worker"));

        verify(eaMock, timeout(5000)).postEvent(isA(PositionLockedEvent.class));

        long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(5);
        while (svc.getPosition() == null && System.nanoTime() < deadline) {
            Thread.sleep(10);
        }
        Position currentPosition = svc.getPosition();
        assertNotNull(currentPosition, "GPS worker did not publish the fixture position");
        NmeaPosition currentNmeaPosition = svc.getNmeaPosition();

        double eps = 0.0000001;
        assertEquals(Math.toRadians(39.757509), currentPosition.getLatitude().getValue(), eps);
        assertEquals(Math.toRadians(-104.902044), currentPosition.getLongitude().getValue(), eps);
        assertEquals(1602.0, currentPosition.getAltitude().getValue(), eps);

        eps *= 10.0;
        assertEquals(39.757509, currentNmeaPosition.getLatitude(), eps);
        assertEquals(-104.902044, currentNmeaPosition.getLongitude(), eps);
        assertEquals(1602.0, currentNmeaPosition.getAltitude(), eps);
    }

    @Test
    public void testUpdate() throws Exception {
        // test service update

        PositionServiceImpl svc = new PositionServiceImpl();

        Bundle bMock = initBundleMock();

        ComponentContext ccMock = initComponentContextMock(bMock);

        EventAdmin eaMock = mock(EventAdmin.class);
        svc.setEventAdmin(eaMock);

        Map<String, Object> properties = new HashMap<>();
        properties.put(USE_GPSD, true);
        svc.activate(ccMock, properties);
        workers.add((java.util.concurrent.ScheduledExecutorService) TestUtil.getFieldValue(svc, "worker"));

        properties = new HashMap<>();
        properties.put(USE_GPSD, true);
        svc.updated(properties);
        workers.add((java.util.concurrent.ScheduledExecutorService) TestUtil.getFieldValue(svc, "worker"));

        assertTrue((boolean) TestUtil.getFieldValue(svc, "useGpsd"));

        properties.put(USE_GPSD, false);
        svc.updated(properties);
        workers.add((java.util.concurrent.ScheduledExecutorService) TestUtil.getFieldValue(svc, "worker"));

        assertFalse((boolean) TestUtil.getFieldValue(svc, "useGpsd"));
    }

    private ComponentContext initComponentContextMock(Bundle bMock) {
        BundleContext bcMock = mock(BundleContext.class);
        when(bcMock.getBundle()).thenReturn(bMock);
        ComponentContext ccMock = mock(ComponentContext.class);
        when(ccMock.getBundleContext()).thenReturn(bcMock);
        return ccMock;
    }

    private Bundle initBundleMock() throws MalformedURLException {
        Bundle bMock = mock(Bundle.class);
        String name = "test.gpx";
        URL url = PositionServiceImplTest.class.getResource("/" + name);
        assertNotNull(url, "GPS fixture must be available from the Maven classpath");
        when(bMock.getResource(name)).thenReturn(url);
        return bMock;
    }
}
