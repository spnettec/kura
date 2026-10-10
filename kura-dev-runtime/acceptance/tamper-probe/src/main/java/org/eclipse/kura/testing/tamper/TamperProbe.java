/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.testing.tamper;

import java.util.Dictionary;
import java.util.Hashtable;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import org.eclipse.kura.security.tamper.detection.TamperDetectionService;
import org.eclipse.kura.security.tamper.detection.TamperEvent;
import org.eclipse.kura.security.tamper.detection.TamperStatus;
import org.osgi.framework.BundleActivator;
import org.osgi.framework.BundleContext;
import org.osgi.framework.ServiceReference;
import org.osgi.framework.ServiceRegistration;
import org.osgi.service.event.Event;
import org.osgi.service.event.EventAdmin;
import org.osgi.service.event.EventConstants;
import org.osgi.service.event.EventHandler;

public final class TamperProbe implements BundleActivator, TamperDetectionService, EventHandler {
    private static final String PID = "fixture.tamper.mac.scr";
    private final AtomicInteger deliveredEvents = new AtomicInteger();
    private volatile boolean tampered;
    private BundleContext context;
    private ServiceRegistration<?> tamperRegistration;
    private ServiceRegistration<?> eventRegistration;
    private ServiceRegistration<?> commandRegistration;

    @Override
    public void start(BundleContext context) {
        this.context = context;
        Dictionary<String, Object> eventProperties = new Hashtable<>();
        eventProperties.put(EventConstants.EVENT_TOPIC, TamperEvent.TAMPER_EVENT_TOPIC);
        this.eventRegistration = context.registerService(EventHandler.class.getName(), this, eventProperties);
        Dictionary<String, Object> tamperProperties = new Hashtable<>();
        tamperProperties.put("kura.service.pid", PID);
        this.tamperRegistration = context.registerService(TamperDetectionService.class.getName(), this, tamperProperties);
        Dictionary<String, Object> commandProperties = new Hashtable<>();
        commandProperties.put("osgi.command.scope", "tamperprobe");
        commandProperties.put("osgi.command.function", new String[] { "trigger", "events" });
        this.commandRegistration = context.registerService(TamperProbe.class.getName(), this, commandProperties);
    }

    @Override
    public void stop(BundleContext context) {
        this.commandRegistration.unregister();
        this.tamperRegistration.unregister();
        this.eventRegistration.unregister();
        this.context = null;
    }

    @Override
    public String getDisplayName() { return "Mac SCR tamper fixture"; }

    @Override
    public TamperStatus getTamperStatus() { return new TamperStatus(this.tampered, Map.of()); }

    @Override
    public void resetTamperStatus() {
        this.tampered = false;
        publishStatus();
    }

    public String trigger() {
        this.tampered = true;
        publishStatus();
        return "triggered pid=" + PID + " events=" + this.deliveredEvents.get();
    }

    public String events() { return Integer.toString(this.deliveredEvents.get()); }

    @Override
    public void handleEvent(Event event) {
        if (PID.equals(event.getProperty(TamperEvent.SENDER_PID_PROPERTY_KEY))) {
            this.deliveredEvents.incrementAndGet();
        }
    }

    private void publishStatus() {
        ServiceReference<EventAdmin> reference = this.context.getServiceReference(EventAdmin.class);
        if (reference == null) { throw new IllegalStateException("EventAdmin unavailable"); }
        EventAdmin admin = this.context.getService(reference);
        try { admin.sendEvent(new TamperEvent(PID, getTamperStatus())); }
        finally { this.context.ungetService(reference); }
    }
}
