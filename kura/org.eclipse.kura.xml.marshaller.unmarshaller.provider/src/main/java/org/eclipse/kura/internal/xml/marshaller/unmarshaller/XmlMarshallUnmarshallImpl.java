/*******************************************************************************
 * Copyright (c) 2017, 2021 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 *******************************************************************************/
package org.eclipse.kura.internal.xml.marshaller.unmarshaller;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;

import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.parsers.ParserConfigurationException;
import javax.xml.stream.FactoryConfigurationError;
import javax.xml.stream.XMLInputFactory;
import javax.xml.stream.XMLStreamConstants;
import javax.xml.stream.XMLStreamReader;
import javax.xml.transform.OutputKeys;
import javax.xml.transform.Transformer;
import javax.xml.transform.TransformerException;
import javax.xml.transform.TransformerFactory;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamResult;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.metatype.MetaData;
import org.eclipse.kura.core.configuration.XmlComponentConfigurations;
import org.eclipse.kura.core.configuration.XmlSnapshotIdResult;
import org.eclipse.kura.core.configuration.metatype.Tmetadata;
import org.eclipse.kura.core.inventory.resources.ContainerImages;
import org.eclipse.kura.core.inventory.resources.DockerContainers;
import org.eclipse.kura.core.inventory.resources.SystemBundles;
import org.eclipse.kura.core.inventory.resources.SystemDeploymentPackages;
import org.eclipse.kura.core.inventory.resources.SystemPackages;
import org.eclipse.kura.core.inventory.resources.SystemResourcesInfo;
import org.eclipse.kura.marshalling.Marshaller;
import org.eclipse.kura.marshalling.Unmarshaller;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.w3c.dom.Document;
import org.xml.sax.SAXException;

public class XmlMarshallUnmarshallImpl implements Marshaller, Unmarshaller {

    private static final Logger logger = LoggerFactory.getLogger(XmlMarshallUnmarshallImpl.class);
    private static final String VALUE_CONSTANT = "value";

    @Override
    public String marshal(Object object) throws KuraException {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        try {
            marshal(object, buffer);
        } catch (Exception e) {
            throw new KuraException(KuraErrorCode.ENCODE_ERROR, VALUE_CONSTANT);
        }
        return buffer.toString();
    }

    @Override
    public void marshal(Object object, OutputStream outputStream) throws Exception {
        if (object instanceof XmlComponentConfigurations) {
            new XmlJavaComponentConfigurationsMapper().marshal(outputStream, object);
            outputStream.flush();
            return;
        }
        try {
            DocumentBuilderFactory docFactory = DocumentBuilderFactory.newInstance();
            docFactory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
            docFactory.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");
            docFactory.setAttribute(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "");
            DocumentBuilder docBuilder = docFactory.newDocumentBuilder();

            // root elements
            Document doc = docBuilder.newDocument();
            doc.setXmlStandalone(true);

            if (object instanceof XmlSnapshotIdResult) {
                // Resulting xml:
                // <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
                // <esf:snapshot-ids xmlns:ocd="http://www.osgi.org/xmlns/metatype/v1.2.0"
                // xmlns:esf="http://eurotech.com/esf/2.0">
                // <esf:snapshotIds>1434122113492</esf:snapshotIds>
                // <esf:snapshotIds>1434122124387</esf:snapshotIds>
                // </esf:snapshot-ids>

                new XmlJavaSnapshotIdResultMapper().marshal(doc, object);

            } else if (object instanceof XmlComponentConfigurations) {
                new XmlJavaComponentConfigurationsMapper().marshal(doc, object);
            } else if (object instanceof SystemDeploymentPackages) {
                // Expected resulting xml:
                // <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
                // <packages>
                // <package>
                // <name>org.eclipse.kura.demo.heater</name>
                // <version>1.2.0.qualifier</version>
                // <bundles>
                // <bundle>
                // <name>org.eclipse.kura.demo.heater</name>
                // <version>1.0.1</version>
                // </bundle>
                // </bundles>
                // </package>
                // </packages>

                new XmlJavaPackagesMapper().marshal(doc, object);

            } else if (object instanceof SystemBundles) {
                // Expected resulting xml:
                // <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
                // <bundles>
                // <bundle>
                // <name>org.eclipse.osgi</name>
                // <version>3.8.1.v20120830-144521</version>
                // <id>0</id>
                // <state>ACTIVE</state>
                // </bundle>
                // </bundles>

                new XmlJavaBundlesMapper().marshal(doc, object);

            } else if (object instanceof SystemPackages) {
                // Expected resulting xml:
                // <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
                // <systemPackages>
                // <systemPackage>
                // <name>rfkill</name>
                // <version>2.33.1-0.1</version>
                // <type>DEB</type>
                // </systemPackage>
                // </systemPackages>

                new XmlJavaSystemPackagesMapper().marshal(doc, object);

            } else if (object instanceof SystemResourcesInfo) {
                // Expected resulting xml:
                // <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
                // <inventory>
                // <resource>
                // <name>rfkill</name>
                // <version>2.33.1-0.1</version>
                // <type>DEB</type>
                // </resource>
                // </inventory>

                new XmlJavaSystemResourcesMapper().marshal(doc, object);
            } else if (object instanceof DockerContainers) {
                // Expected resulting xml:
                // <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
                // <inventory>
                // <resource>
                // <name>example_container</name>
                // <version>imageName:imagetag</version>
                // <type>DOCKER</type>
                // </resource>
                // </inventory>

                new XmlJavaDockerContainersMapper().marshal(doc, object);
            } else if (object instanceof ContainerImages) {
                // Expected resulting xml:
                // <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
                // <inventory>
                // <resource>
                // <name>example_image</name>
                // <version>imagetag</version>
                // <type>CONTAINER_IMAGE</type>
                // </resource>
                // </inventory>

                new XmlJavaContainerImagesMapper().marshal(doc, object);
            }

            // write the content into xml file
            TransformerFactory transformerFactory = TransformerFactory.newInstance();
            transformerFactory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
            transformerFactory.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");
            transformerFactory.setAttribute(XMLConstants.ACCESS_EXTERNAL_STYLESHEET, "");

            Transformer transformer = transformerFactory.newTransformer();
            transformer.setOutputProperty(OutputKeys.INDENT, "yes");
            transformer.setOutputProperty("{http://xml.apache.org/xslt}indent-amount", "4");
            DOMSource source = new DOMSource(doc);

            StreamResult result = new StreamResult(outputStream); // System.out
            transformer.transform(source, result);
            outputStream.flush();
        } catch (ParserConfigurationException pce) {
            logger.warn("Parser Exception", pce);
        } catch (TransformerException tfe) {
            logger.warn("Transformer Exception", tfe);
        }
    }

    // un-marshalling
    @Override
    public <T> T unmarshal(String s, Class<T> clazz) throws KuraException {
        ByteArrayInputStream sr = new ByteArrayInputStream(s.getBytes());
        return unmarshal(sr, clazz);
    }

    @SuppressWarnings("unchecked")
    @Override
    public <T> T unmarshal(InputStream inputStream, Class<T> clazz) throws KuraException {
        if (clazz.equals(XmlComponentConfigurations.class)) {
            try {
                XMLInputFactory factory = XMLInputFactory.newInstance();
                factory.setProperty(XMLInputFactory.IS_SUPPORTING_EXTERNAL_ENTITIES, Boolean.FALSE);
                factory.setProperty(XMLInputFactory.SUPPORT_DTD, Boolean.FALSE);
                factory.setProperty(XMLInputFactory.IS_COALESCING, true);
                XMLStreamReader r = factory.createXMLStreamReader(inputStream);
                List<ComponentConfiguration> cnfs = new ArrayList<>();
                while (r.hasNext()) {
                    int event = r.getEventType();
                    if (event == XMLStreamConstants.START_ELEMENT && r.getLocalName().equals("configuration")) {
                        ComponentConfiguration cnf = new XmlJavaComponentConfigurationsMapper().paraConfiguration(r);
                        cnfs.add(cnf);
                    }
                    r.next();
                }
                XmlComponentConfigurations xcc = new XmlComponentConfigurations();
                xcc.setConfigurations(cnfs);
                return (T) xcc;
            } catch (Exception e) {
                throw new KuraException(KuraErrorCode.DECODER_ERROR, e);
            }
        }
        DocumentBuilderFactory factory = null;
        DocumentBuilder parser = null;

        try {
            factory = DocumentBuilderFactory.newInstance();
            if (factory == null) {
                throw KuraException.internalError("null DocumentBuilderFactory Instance");
            }
            factory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
            factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");
            factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "");
            parser = factory.newDocumentBuilder();
        } catch (FactoryConfigurationError fce) {
            // The implementation is not available or cannot be instantiated
            logger.error("Parser Factory configuration Error");
            throw fce;
        } catch (ParserConfigurationException pce) {
            // the parser cannot be created with the specified configuration
            logger.error("Parser configuration exception");
            throw new FactoryConfigurationError(pce);
        }

        // parse the document
        Document doc = null;
        try {
            doc = parser.parse(inputStream);
            if (doc == null) {
                throw KuraException.internalError("null doc");
            }
            doc.getDocumentElement().normalize();
        } catch (SAXException | IOException | IllegalArgumentException se) {
            throw new KuraException(KuraErrorCode.DECODER_ERROR, VALUE_CONSTANT, se);
        }

        // identify the correct parser that has to execute
        if (clazz.equals(XmlComponentConfigurations.class)) {
            try {
                // Snapshot parser
                return new XmlJavaComponentConfigurationsMapper().unmarshal(doc);
            } catch (Exception e) {
                throw new KuraException(KuraErrorCode.DECODER_ERROR, VALUE_CONSTANT, e);
            }
        } else if (clazz.equals(MetaData.class) || clazz.equals(Tmetadata.class)) {
            // MetaData parser
            return new XmlJavaMetadataMapper().unmarshal(doc);
        } else {
            throw new IllegalArgumentException("Class not supported!");
        }
    }
}
