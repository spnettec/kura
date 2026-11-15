/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.io.PrintStream;
import java.nio.channels.Channels;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermission;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Set;

import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.stream.XMLInputFactory;
import javax.xml.stream.XMLStreamConstants;

import org.eclipse.kura.core.configuration.XmlComponentConfigurations;
import org.eclipse.kura.core.crypto.CryptoServiceImpl;
import org.eclipse.kura.internal.xml.marshaller.unmarshaller.XmlJavaComponentConfigurationsMapper;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.xml.sax.ErrorHandler;
import org.xml.sax.SAXParseException;

/** Read-only, short-lived validation. No OSGi framework, business activation or file publication. */
public final class SnapshotTool {
    static final int LIMIT = 32 * 1024 * 1024;
    private static final String NS = "http://eurotech.com/esf/2.0";
    private static final Set<String> TYPES = Set.of("String", "Long", "Double", "Float", "Integer", "Byte",
            "Char", "Boolean", "Short", "Password");

    private SnapshotTool() { }

    public static void main(String[] args) {
        System.exit(run(args, System.out, System.err));
    }

    static int run(String[] args, PrintStream out, PrintStream err) {
        try {
            Map<String, String> options = options(args);
            byte[] key = options.containsKey("--key-file") ? readKey(Path.of(options.get("--key-file"))) : null;
            CryptoServiceImpl crypto;
            try {
                crypto = CryptoServiceImpl.forSnapshotRecovery(key, options.containsKey("--default-key"));
            } finally {
                if (key != null) {
                    Arrays.fill(key, (byte) 0);
                }
            }
            byte[] artifact = read(Path.of(options.get("--input")), LIMIT);
            byte[] xml = artifact;
            boolean encrypted = options.get("--mode").equals("aes-gcm");
            if (encrypted) {
                try (InputStream in = crypto.aesDecryptingStream(new ByteArrayInputStream(artifact))) {
                    xml = bounded(in, LIMIT);
                }
            }
            try {
                Result result = decode(xml, crypto, options.getOrDefault("--password-policy", "authenticated"),
                        false, encrypted).report();
                String sha = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(artifact));
                out.printf("{\"schema\":1,\"artifactSha256\":\"%s\",\"mode\":\"%s\","
                        + "\"configurationCount\":%d,\"factoryCount\":%d,\"propertyCount\":%d,"
                        + "\"passwordValueCount\":%d,\"authenticatedPasswordCount\":%d,"
                        + "\"legacyPasswordCount\":%d,%s\"keyAuthenticated\":%s,"
                        + "\"fullRecoveryVerified\":false}%n", sha, options.get("--mode"), result.configurations,
                        result.factories, result.properties, result.passwords, result.authenticated,
                        result.legacy, result.logicalEncoding ? "\"logicalPasswordCount\":" + result.logical
                                + ",\"passwordEncoding\":\"BASE64_LOGICAL_V1\"," : "",
                        encrypted || result.authenticated > 0);
            } finally {
                Arrays.fill(xml, (byte) 0);
                Arrays.fill(artifact, (byte) 0);
            }
            return 0;
        } catch (Exception failure) {
            // Exception messages may contain XML values, passwords or host paths. Never print them.
            err.println("{\"error\":\"SNAPSHOT_VALIDATION_FAILED\"}");
            return 2;
        }
    }

    private static Map<String, String> options(String[] args) {
        require(args.length > 0 && args[0].equals("validate"));
        Map<String, String> result = new HashMap<>();
        for (int i = 1; i < args.length; i++) {
            String name = args[i];
            require(Set.of("--input", "--mode", "--key-file", "--default-key", "--password-policy").contains(name));
            require(!result.containsKey(name));
            if (name.equals("--default-key")) {
                result.put(name, "true");
            } else {
                require(++i < args.length && !args[i].startsWith("--"));
                result.put(name, args[i]);
            }
        }
        require(result.containsKey("--input") && Set.of("plain", "aes-gcm").contains(result.getOrDefault("--mode", "")));
        require(result.containsKey("--key-file") != result.containsKey("--default-key"));
        require(Set.of("authenticated", "legacy", "logical-v1").contains(result.getOrDefault("--password-policy", "authenticated")));
        return result;
    }

    private static byte[] readKey(Path path) throws Exception {
        Set<PosixFilePermission> permissions = Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS);
        require(!permissions.contains(PosixFilePermission.GROUP_READ)
                && !permissions.contains(PosixFilePermission.GROUP_WRITE)
                && !permissions.contains(PosixFilePermission.GROUP_EXECUTE)
                && !permissions.contains(PosixFilePermission.OTHERS_READ)
                && !permissions.contains(PosixFilePermission.OTHERS_WRITE)
                && !permissions.contains(PosixFilePermission.OTHERS_EXECUTE));
        byte[] key = read(path, 32);
        if (key.length != 16 && key.length != 24 && key.length != 32) {
            Arrays.fill(key, (byte) 0);
            throw new IllegalArgumentException();
        }
        return key;
    }

    private static byte[] read(Path path, int limit) throws Exception {
        require(path.isAbsolute() && Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS));
        try (var channel = Files.newByteChannel(path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS);
                InputStream in = Channels.newInputStream(channel)) {
            return bounded(in, limit);
        }
    }

    private static byte[] bounded(InputStream in, int limit) throws Exception {
        byte[] bytes = in.readNBytes(limit + 1);
        require(bytes.length > 0 && bytes.length <= limit);
        return bytes;
    }

    record Decoded(Result report, java.util.List<org.eclipse.kura.configuration.ComponentConfiguration> configurations) { }

    static Result validate(byte[] xml, CryptoServiceImpl crypto, String passwordPolicy) throws Exception {
        return decode(xml, crypto, passwordPolicy).report();
    }

    static Decoded decode(byte[] xml, CryptoServiceImpl crypto, String passwordPolicy) throws Exception {
        return decode(xml, crypto, passwordPolicy, false);
    }

    static Decoded decodeAuthenticatedArtifact(byte[] xml, CryptoServiceImpl crypto, String passwordPolicy)
            throws Exception {
        return decode(xml, crypto, passwordPolicy, false, true);
    }

    /** Not an upload policy: bootstrap must first authenticate the exact retained inverse source. */
    static Decoded decodeRetainedCmBackup(byte[] xml, CryptoServiceImpl crypto, String passwordPolicy) throws Exception {
        return decode(xml, crypto, passwordPolicy, true);
    }

    private static Decoded decode(byte[] xml, CryptoServiceImpl crypto, String passwordPolicy, boolean allowEmpty)
            throws Exception {
        return decode(xml, crypto, passwordPolicy, allowEmpty, false);
    }

    private static Decoded decode(byte[] xml, CryptoServiceImpl crypto, String passwordPolicy, boolean allowEmpty,
            boolean artifactAuthenticated) throws Exception {
        require(Set.of("authenticated", "legacy", "logical-v1").contains(passwordPolicy));
        require(xml.length > 0 && xml.length <= LIMIT);
        preflight(xml);
        DocumentBuilderFactory factory = DocumentBuilderFactory.newDefaultInstance();
        factory.setNamespaceAware(true);
        factory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
        factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");
        factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "");
        factory.setXIncludeAware(false);
        factory.setExpandEntityReferences(false);
        var builder = factory.newDocumentBuilder();
        builder.setErrorHandler(new ErrorHandler() {
            public void warning(SAXParseException e) throws SAXParseException { throw e; }
            public void error(SAXParseException e) throws SAXParseException { throw e; }
            public void fatalError(SAXParseException e) throws SAXParseException { throw e; }
        });
        var document = builder.parse(new ByteArrayInputStream(xml));
        Element root = document.getDocumentElement();
        element(root, "configurations", Set.of("passwordEncoding"));
        Result result = new Result();
        result.logicalEncoding = root.hasAttribute("passwordEncoding");
        require(!result.logicalEncoding || root.getAttribute("passwordEncoding").equals("BASE64_LOGICAL_V1"));
        require(!result.logicalEncoding || !passwordPolicy.equals("legacy"));
        require(!passwordPolicy.equals("logical-v1") || result.logicalEncoding);
        Set<String> pids = new HashSet<>();
        for (Element configuration : children(root)) {
            element(configuration, "configuration", Set.of("pid"));
            String pid = configuration.getAttribute("pid");
            require(!pid.isBlank() && pid.length() <= 1024 && pids.add(pid) && ++result.configurations <= 4096);
            List<Element> groups = children(configuration);
            require(groups.size() == 1);
            Element properties = groups.getFirst();
            element(properties, "properties", Set.of());
            Set<String> names = new HashSet<>();
            for (Element property : children(properties)) {
                element(property, "property", Set.of("name", "type", "array", "encrypted", "container"));
                String name = property.getAttribute("name");
                String type = property.getAttribute("type");
                require(!name.isBlank() && name.length() <= 1024 && names.add(name) && TYPES.contains(type));
                require(++result.properties <= 65536);
                boolean array = flag(property, "array");
                String container = property.getAttribute("container");
                require(!property.hasAttribute("container") || array
                        && Set.of("PRIMITIVE_ARRAY", "VECTOR", "LIST").contains(container));
                require(!container.equals("PRIMITIVE_ARRAY") || !Set.of("String", "Password").contains(type));
                boolean encoded = flag(property, "encrypted");
                require(!encoded || type.equals("Password"));
                List<Element> values = children(property);
                require(array || values.size() <= 1);
                require(values.size() <= 65536);
                if (name.equals("service.factoryPid")) {
                    require(type.equals("String") && !array && values.size() == 1
                            && !values.getFirst().getTextContent().isBlank());
                    result.factories++;
                }
                for (Element value : values) {
                    require(++result.values <= 65536);
                    element(value, "value", Set.of());
                    require(children(value).isEmpty());
                    String text = value.getTextContent();
                    require(text.length() <= 1024 * 1024);
                    if (type.equals("Boolean")) {
                        require(text.equals("true") || text.equals("false"));
                    } else if (type.equals("Char")) {
                        require(text.length() == 1);
                    } else if (type.equals("Float") || type.equals("Double")) {
                        require(Double.isFinite(Double.parseDouble(text)));
                        if (type.equals("Float")) {
                            require(Float.isFinite(Float.parseFloat(text)));
                        }
                    } else if (type.equals("Password")) {
                        result.passwords++;
                          if (result.logicalEncoding) {
                              require(encoded && (passwordPolicy.equals("logical-v1")
                                      || passwordPolicy.equals("authenticated") && artifactAuthenticated));
                              byte[] clear = java.util.Base64.getDecoder().decode(text);
                              try {
                                  java.nio.charset.StandardCharsets.UTF_8.newDecoder()
                                          .onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
                                          .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT)
                                          .decode(java.nio.ByteBuffer.wrap(clear));
                              } finally { Arrays.fill(clear, (byte) 0); }
                              result.logical++;
                          } else if (authenticated(text, encoded, crypto)) {
                            result.authenticated++;
                        } else {
                            require(passwordPolicy.equals("legacy"));
                            result.legacy++;
                        }
                    }
                }
            }
        }
        require(allowEmpty || result.configurations > 0);
        // Conversion and container reconstruction remain the real Kura implementation.
        XmlComponentConfigurations mapped = new XmlJavaComponentConfigurationsMapper(crypto).unmarshal(document);
        require(mapped.getConfigurations().size() == result.configurations);
        return new Decoded(result, mapped.getConfigurations());
    }

    private static boolean authenticated(String value, boolean encoded, CryptoServiceImpl crypto) throws Exception {
        if (!encoded) {
            return false;
        }
        String candidate = value;
        if (!candidate.contains("-")) {
            candidate = new String(crypto.decodeBase64(candidate));
        }
        // A ciphertext-shaped value must authenticate even with explicit legacy compatibility.
        if (candidate.matches("(?s)[A-Za-z0-9+/]{16}-.*")) {
            char[] plaintext = crypto.decryptAes(candidate.toCharArray());
            Arrays.fill(plaintext, '\0');
            return true;
        }
        return false;
    }

    private static void preflight(byte[] xml) throws Exception {
        XMLInputFactory factory = XMLInputFactory.newDefaultFactory();
        factory.setProperty(XMLInputFactory.SUPPORT_DTD, false);
        factory.setProperty("javax.xml.stream.isSupportingExternalEntities", false);
        factory.setXMLResolver((a, b, c, d) -> { throw new IllegalArgumentException(); });
        var reader = factory.createXMLStreamReader(new ByteArrayInputStream(xml));
        int depth = 0;
        int events = 0;
        try {
            while (reader.hasNext()) {
                int event = reader.next();
                require(++events <= 400000);
                require(event != XMLStreamConstants.DTD && event != XMLStreamConstants.ENTITY_REFERENCE
                        && event != XMLStreamConstants.PROCESSING_INSTRUCTION);
                if (event == XMLStreamConstants.START_ELEMENT) {
                    require(++depth <= 5 && reader.getAttributeCount() <= 5 && reader.getNamespaceCount() <= 8);
                } else if (event == XMLStreamConstants.END_ELEMENT) {
                    depth--;
                }
            }
        } finally {
            reader.close();
        }
    }

    private static void element(Element element, String name, Set<String> attributes) {
        require(element.getTagName().equals("esf:" + name) && NS.equals(element.getNamespaceURI()));
        var attrs = element.getAttributes();
        for (int i = 0; i < attrs.getLength(); i++) {
            Node attr = attrs.item(i);
            if (XMLConstants.XMLNS_ATTRIBUTE_NS_URI.equals(attr.getNamespaceURI())) {
                require((attr.getNodeValue().equals(NS) && attr.getNodeName().equals("xmlns:esf"))
                        || (element.getLocalName().equals("configurations")
                                && attr.getNodeName().equals("xmlns:ocd")
                                && attr.getNodeValue().equals("http://www.osgi.org/xmlns/metatype/v1.2.0")));
            } else {
                require(attr.getNamespaceURI() == null && attributes.contains(attr.getNodeName()));
            }
        }
        for (String attribute : attributes) {
            require(attribute.equals("array") || attribute.equals("encrypted") || attribute.equals("container")
                    || attribute.equals("passwordEncoding")
                    || element.hasAttribute(attribute));
        }
    }

    private static List<Element> children(Element element) {
        List<Element> result = new ArrayList<>();
        for (Node node = element.getFirstChild(); node != null; node = node.getNextSibling()) {
            if (node instanceof Element child) {
                result.add(child);
            } else {
                require(node.getNodeType() == Node.TEXT_NODE || node.getNodeType() == Node.CDATA_SECTION_NODE
                        || node.getNodeType() == Node.COMMENT_NODE);
                if (!element.getLocalName().equals("value") && node.getNodeType() != Node.COMMENT_NODE) {
                    require(node.getTextContent().isBlank());
                }
            }
        }
        return result;
    }

    private static boolean flag(Element element, String attribute) {
        String value = element.hasAttribute(attribute) ? element.getAttribute(attribute) : "false";
        require(value.equals("true") || value.equals("false"));
        return value.equals("true");
    }

    private static void require(boolean condition) {
        if (!condition) {
            throw new IllegalArgumentException();
        }
    }

    static final class Result {
        boolean logicalEncoding;
        int logical;
        int configurations;
        int factories;
        int properties;
        int values;
        int passwords;
        int authenticated;
        int legacy;
    }
}
