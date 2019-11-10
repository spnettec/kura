package org.eclipse.kura.web.client.ui;

import org.gwtbootstrap3.client.ui.base.TextBoxBase;
import org.gwtbootstrap3.client.ui.constants.Styles;

import com.google.gwt.dom.client.Document;
import com.google.gwt.dom.client.Element;
import com.google.gwt.text.shared.Parser;
import com.google.gwt.text.shared.Renderer;
import com.google.gwt.text.shared.testing.PassthroughParser;
import com.google.gwt.text.shared.testing.PassthroughRenderer;

public class KuraTextBox extends TextBoxBase {

    private String data = "";

    public KuraTextBox() {
        this(Document.get().createTextInputElement());
    }

    public KuraTextBox(final Element element) {
        this(element, PassthroughRenderer.instance(), PassthroughParser.instance());
    }

    public KuraTextBox(Element element, Renderer<String> renderer, Parser<String> parser) {
        super(element, renderer, parser);
        setStyleName(Styles.FORM_CONTROL);
    }

    public void clear() {
        super.setValue(null);
    }

    public void setData(final String data) {
        this.data = data;
    }

    public String getData() {
        return this.data;
    }

}
