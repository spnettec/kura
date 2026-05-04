package org.eclipse.kura.web.client.ui;

import org.gwtbootstrap3.client.ui.Anchor;

public class KuraAnchor extends Anchor {

    private String data = "";

    public KuraAnchor() {
        super();
    }

    public KuraAnchor(final String text, String data, final String href) {
        super(href);
        setText(text);
        this.data = data;
    }

    public void setData(final String data) {
        this.data = data;
    }

    public String getData() {
        return this.data;
    }

}
