package org.eclipse.kura.internal.xml.marshaller.unmarshaller;

import java.util.Stack;

import javax.xml.namespace.NamespaceContext;
import javax.xml.stream.XMLStreamException;
import javax.xml.stream.XMLStreamWriter;

public class IndentingXMLStreamWriter implements XMLStreamWriter {

    private static final Object SEEN_NOTHING = new Object();
    private static final Object SEEN_ELEMENT = new Object();
    private static final Object SEEN_DATA = new Object();

    private Object state = SEEN_NOTHING;
    private final Stack<Object> stateStack = new Stack<>();
    private final XMLStreamWriter writer;
    private String indentStep = "    ";
    private int depth = 0;

    public IndentingXMLStreamWriter(XMLStreamWriter writer) {
        this.writer = writer;
    }

    public void setIndentStep(String s) {
        this.indentStep = s;
    }

    private void onStartElement() throws XMLStreamException {
        this.stateStack.push(SEEN_ELEMENT);
        this.state = SEEN_NOTHING;
        if (this.depth > 0) {
            this.writer.writeCharacters("\n");
        }
        doIndent();
        this.depth++;
    }

    private void onEndElement() throws XMLStreamException {
        this.depth--;
        if (this.state == SEEN_ELEMENT) {
            this.writer.writeCharacters("\n");
            doIndent();
        }
        this.state = this.stateStack.pop();
    }

    private void onEmptyElement() throws XMLStreamException {
        this.state = SEEN_ELEMENT;
        if (this.depth > 0) {
            this.writer.writeCharacters("\n");
        }
        doIndent();
    }

    private void doIndent() throws XMLStreamException {
        if (this.depth > 0) {
            for (int i = 0; i < this.depth; i++) {
                this.writer.writeCharacters(this.indentStep);
            }
        }
    }

    @Override
    public void writeStartDocument() throws XMLStreamException {
        this.writer.writeStartDocument();
        this.writer.writeCharacters("\n");
    }

    @Override
    public void writeStartDocument(String version) throws XMLStreamException {
        this.writer.writeStartDocument(version);
        this.writer.writeCharacters("\n");
    }

    @Override
    public void writeStartDocument(String encoding, String version) throws XMLStreamException {
        this.writer.writeStartDocument(encoding, version);
        this.writer.writeCharacters("\n");
    }

    @Override
    public void writeStartElement(String localName) throws XMLStreamException {
        onStartElement();
        this.writer.writeStartElement(localName);
    }

    @Override
    public void writeStartElement(String namespaceURI, String localName) throws XMLStreamException {
        onStartElement();
        this.writer.writeStartElement(namespaceURI, localName);
    }

    @Override
    public void writeStartElement(String prefix, String localName, String namespaceURI) throws XMLStreamException {
        onStartElement();
        this.writer.writeStartElement(prefix, localName, namespaceURI);
    }

    @Override
    public void writeEmptyElement(String namespaceURI, String localName) throws XMLStreamException {
        onEmptyElement();
        this.writer.writeEmptyElement(namespaceURI, localName);
    }

    @Override
    public void writeEmptyElement(String prefix, String localName, String namespaceURI) throws XMLStreamException {
        onEmptyElement();
        this.writer.writeEmptyElement(prefix, localName, namespaceURI);
    }

    @Override
    public void writeEmptyElement(String localName) throws XMLStreamException {
        onEmptyElement();
        this.writer.writeEmptyElement(localName);
    }

    @Override
    public void writeEndElement() throws XMLStreamException {
        onEndElement();
        this.writer.writeEndElement();
    }

    @Override
    public void writeCharacters(String text) throws XMLStreamException {
        this.state = SEEN_DATA;
        this.writer.writeCharacters(text);
    }

    @Override
    public void writeCharacters(char[] text, int start, int len) throws XMLStreamException {
        this.state = SEEN_DATA;
        this.writer.writeCharacters(text, start, len);
    }

    @Override
    public void writeCData(String data) throws XMLStreamException {
        this.state = SEEN_DATA;
        this.writer.writeCData(data);
    }

    @Override
    public void writeEndDocument() throws XMLStreamException {
        this.writer.writeEndDocument();
    }

    @Override
    public void close() throws XMLStreamException {
        this.writer.close();
    }

    @Override
    public void flush() throws XMLStreamException {
        this.writer.flush();
    }

    @Override
    public void writeAttribute(String localName, String value) throws XMLStreamException {
        this.writer.writeAttribute(localName, value);
    }

    @Override
    public void writeAttribute(String prefix, String namespaceURI, String localName, String value)
            throws XMLStreamException {
        this.writer.writeAttribute(prefix, namespaceURI, localName, value);
    }

    @Override
    public void writeAttribute(String namespaceURI, String localName, String value) throws XMLStreamException {
        this.writer.writeAttribute(namespaceURI, localName, value);
    }

    @Override
    public void writeNamespace(String prefix, String namespaceURI) throws XMLStreamException {
        this.writer.writeNamespace(prefix, namespaceURI);
    }

    @Override
    public void writeDefaultNamespace(String namespaceURI) throws XMLStreamException {
        this.writer.writeDefaultNamespace(namespaceURI);
    }

    @Override
    public void writeComment(String data) throws XMLStreamException {
        this.writer.writeComment(data);
    }

    @Override
    public void writeProcessingInstruction(String target) throws XMLStreamException {
        this.writer.writeProcessingInstruction(target);
    }

    @Override
    public void writeProcessingInstruction(String target, String data) throws XMLStreamException {
        this.writer.writeProcessingInstruction(target, data);
    }

    @Override
    public void writeDTD(String dtd) throws XMLStreamException {
        this.writer.writeDTD(dtd);
    }

    @Override
    public void writeEntityRef(String name) throws XMLStreamException {
        this.writer.writeEntityRef(name);
    }

    @Override
    public String getPrefix(String uri) throws XMLStreamException {
        return this.writer.getPrefix(uri);
    }

    @Override
    public void setPrefix(String prefix, String uri) throws XMLStreamException {
        this.writer.setPrefix(prefix, uri);
    }

    @Override
    public void setDefaultNamespace(String uri) throws XMLStreamException {
        this.writer.setDefaultNamespace(uri);
    }

    @Override
    public void setNamespaceContext(NamespaceContext context) throws XMLStreamException {
        this.writer.setNamespaceContext(context);
    }

    @Override
    public NamespaceContext getNamespaceContext() {
        return this.writer.getNamespaceContext();
    }

    @Override
    public Object getProperty(String name) throws IllegalArgumentException {
        return this.writer.getProperty(name);
    }
}