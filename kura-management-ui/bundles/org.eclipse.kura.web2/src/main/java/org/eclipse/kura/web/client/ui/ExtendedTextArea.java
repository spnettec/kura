package org.eclipse.kura.web.client.ui;

import org.gwtbootstrap3.client.ui.TextArea;

import com.google.gwt.core.client.Scheduler;
import com.google.gwt.core.client.Scheduler.ScheduledCommand;
import com.google.gwt.event.logical.shared.ValueChangeEvent;
import com.google.gwt.user.client.DOM;
import com.google.gwt.user.client.Event;

public class ExtendedTextArea extends TextArea {

    public ExtendedTextArea() {
        super();
        sinkEvents(Event.ONPASTE);
    }

    @Override
    public void onBrowserEvent(Event event) {
        super.onBrowserEvent(event);
        switch (DOM.eventGetType(event)) {
        case Event.ONPASTE:
        case Event.ONKEYUP:
            Scheduler.get().scheduleDeferred(new ScheduledCommand() {

                @Override
                public void execute() {
                    ValueChangeEvent.fire(ExtendedTextArea.this, getText());
                }

            });
            break;
        }
    }
}
