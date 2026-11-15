/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import static org.junit.jupiter.api.Assertions.*;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.configuration.XmlComponentConfigurations;
import org.eclipse.kura.core.crypto.CryptoServiceImpl;
import org.eclipse.kura.internal.xml.marshaller.unmarshaller.XmlJavaComponentConfigurationsMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class SnapshotToolTest {
    @TempDir Path directory;
    final byte[] key = "0123456789abcdef".getBytes(StandardCharsets.UTF_8);
    final CryptoServiceImpl crypto = CryptoServiceImpl.forSnapshotRecovery(key, false);

    byte[] snapshot(Map<String, Object> properties) throws Exception {
        XmlComponentConfigurations configurations = new XmlComponentConfigurations();
        configurations.setConfigurations(List.of(new ComponentConfigurationImpl("test.pid", null, properties)));
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        new XmlJavaComponentConfigurationsMapper(crypto).marshal(bytes, configurations);
        return bytes.toByteArray();
    }

    @Test void actualKuraMapperOutsideOsgiPreservesAllTypesAndCdata() throws Exception {
        Map<String, Object> props = new HashMap<>();
        props.put("string", "<route>script must never run & remain data</route>");
        props.put("long", 9L); props.put("int", 4); props.put("short", (short) 3);
        props.put("byte", (byte) 2); props.put("double", 3.5); props.put("float", 2.5f);
        props.put("char", 'x'); props.put("boolean", true);
        props.put("array", new Integer[] {1, 2});
        props.put("service.factoryPid", "test.factory");
        props.put("password", new Password(crypto.encryptAes("secret-canary".toCharArray())));
        props.put("passwords", new Password[] {new Password(crypto.encryptAes("a".toCharArray())),
                new Password(crypto.encryptAes("b".toCharArray()))});
        var result = SnapshotTool.validate(snapshot(props), crypto, "authenticated");
        assertEquals(13, result.properties); assertEquals(1, result.factories);
        assertEquals(3, result.authenticated); assertEquals(0, result.legacy);
    }

    @Test void explicitKeyChoiceRejectsMissingAmbiguousAndInvalidKeys() throws Exception {
        assertThrows(IllegalArgumentException.class, () -> CryptoServiceImpl.forSnapshotRecovery(null, false));
        assertThrows(IllegalArgumentException.class, () -> CryptoServiceImpl.forSnapshotRecovery(key, true));
        assertThrows(IllegalArgumentException.class, () -> CryptoServiceImpl.forSnapshotRecovery(new byte[15], false));
        char[] encrypted = CryptoServiceImpl.forSnapshotRecovery(null, true).encryptAes("default".toCharArray());
        assertArrayEquals("default".toCharArray(), CryptoServiceImpl.forSnapshotRecovery(null, true).decryptAes(encrypted));
        byte[] supplied = key.clone();
        var isolated = CryptoServiceImpl.forSnapshotRecovery(supplied, false);
        Arrays.fill(supplied, (byte) 0);
        assertArrayEquals("clone".toCharArray(), isolated.decryptAes(crypto.encryptAes("clone".toCharArray())));
    }

    @Test void directAesPasswordAndLegacyAreDistinguishedAndWrongKeyNeverFallsBack() throws Exception {
        String direct = new String(crypto.encryptAes("secret".toCharArray()));
        byte[] xml = raw("<esf:property name=\"p\" type=\"Password\" array=\"false\" encrypted=\"true\"><esf:value>"
                + direct + "</esf:value></esf:property>");
        assertEquals(1, SnapshotTool.validate(xml, crypto, "authenticated").authenticated);
        var wrong = CryptoServiceImpl.forSnapshotRecovery(new byte[16], false);
        assertThrows(Exception.class, () -> SnapshotTool.validate(xml, wrong, "legacy"));
        byte[] wrapped = snapshot(Map.of("p", new Password(direct.toCharArray())));
        assertThrows(Exception.class, () -> SnapshotTool.validate(wrapped, wrong, "legacy"));
        byte[] legacy = snapshot(Map.of("p", new Password("legacy-clear".toCharArray())));
        assertThrows(Exception.class, () -> SnapshotTool.validate(legacy, crypto, "authenticated"));
        assertEquals(1, SnapshotTool.validate(legacy, crypto, "legacy").legacy);
    }

    @Test void cliAuthenticatesWholeSnapshotAndPreservesSourceAndKey() throws Exception {
        byte[] xml = snapshot(Map.of("number", 42));
        ByteArrayOutputStream encrypted = new ByteArrayOutputStream();
        try (var output = crypto.aesEncryptingStream(encrypted)) { output.write(xml); }
        byte[] ciphertext = encrypted.toByteArray();
        Path source = directory.resolve("snapshot.xml"); Files.write(source, ciphertext);
        Path keyPath = directory.resolve("key"); Files.write(keyPath, key);
        Files.setPosixFilePermissions(keyPath, PosixFilePermissions.fromString("rw-------"));
        ByteArrayOutputStream stdout = new ByteArrayOutputStream(), stderr = new ByteArrayOutputStream();
        String[] args = {"validate", "--input", source.toString(), "--mode", "aes-gcm", "--key-file", keyPath.toString()};
        assertEquals(0, SnapshotTool.run(args, new PrintStream(stdout), new PrintStream(stderr)));
        assertTrue(stdout.toString().contains("\"keyAuthenticated\":true"));
        assertTrue(stdout.toString().contains("\"fullRecoveryVerified\":false"));
        assertArrayEquals(ciphertext, Files.readAllBytes(source)); assertArrayEquals(key, Files.readAllBytes(keyPath));
        Files.write(keyPath, new byte[16]); stdout.reset();
        assertEquals(2, SnapshotTool.run(args, new PrintStream(stdout), new PrintStream(stderr)));
        assertEquals("", stdout.toString());
        assertFalse(stderr.toString().contains(directory.toString()));
        Files.write(keyPath, key); ciphertext[ciphertext.length - 3] ^= 1; Files.write(source, ciphertext);
        assertEquals(2, SnapshotTool.run(args, new PrintStream(stdout), new PrintStream(stderr)));
        assertEquals(2, Files.list(directory).count());
    }

    @Test void plainWithNoPasswordsDoesNotClaimKeyAuthentication() throws Exception {
        Path source = directory.resolve("snapshot.xml"); Files.write(source, snapshot(Map.of("a", "value")));
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        assertEquals(0, SnapshotTool.run(new String[] {"validate", "--input", source.toString(), "--mode", "plain",
                "--default-key"}, new PrintStream(out), System.err));
        assertTrue(out.toString().contains("\"keyAuthenticated\":false"));
    }

    @ParameterizedTest @ValueSource(strings = {
        "<esf:property name='x' type='Bogus' array='false' encrypted='false'><esf:value>1</esf:value></esf:property>",
        "<esf:property name='x' type='Boolean' array='false' encrypted='false'><esf:value>yes</esf:value></esf:property>",
        "<esf:property name='x' type='Integer' array='false' encrypted='false'><esf:value>999999999999999999</esf:value></esf:property>",
        "<esf:property name='x' type='Char' array='false' encrypted='false'><esf:value>ab</esf:value></esf:property>",
        "<esf:property name='x' type='Float' array='false' encrypted='false'><esf:value>NaN</esf:value></esf:property>",
        "<esf:property name='x' type='String' array='yes' encrypted='false'><esf:value>x</esf:value></esf:property>",
        "<esf:property name='x' type='String' array='false' encrypted='false'><esf:value>a</esf:value><esf:value>b</esf:value></esf:property>",
        "<esf:property name='x' type='String' array='false' encrypted='false'><esf:value><esf:value>x</esf:value></esf:value></esf:property>",
        "<esf:property name='x' type='String' array='false' encrypted='false'><esf:value>x</esf:value></esf:property><esf:property name='x' type='String' array='false' encrypted='false'><esf:value>x</esf:value></esf:property>",
        "<esf:property name='x' type='String' array='false' encrypted='true'><esf:value>x</esf:value></esf:property>"
    }) void rejectsLossyMalformedProperties(String properties) {
        assertThrows(Exception.class, () -> SnapshotTool.validate(raw(properties), crypto, "authenticated"));
    }

    @Test void rejectsDtdAliasesDuplicatePidsAndUnexpectedStructure() throws Exception {
        String valid = new String(raw(""), StandardCharsets.UTF_8);
        for (String malformed : List.of("<!DOCTYPE esf:configurations [<!ENTITY x SYSTEM 'file:///etc/passwd'>]>" + valid,
                valid.replace("esf:", "other:").replace("xmlns:esf", "xmlns:other"),
                valid.replace("</esf:configurations>", "<esf:configuration pid='p'><esf:properties/></esf:configuration></esf:configurations>"),
                valid.replace("<esf:properties>", "<esf:properties/><esf:properties>"),
                valid.replace("<esf:properties>", "<?execute forbidden?><esf:properties>"))) {
            assertThrows(Exception.class, () -> SnapshotTool.validate(malformed.getBytes(StandardCharsets.UTF_8), crypto, "authenticated"));
        }
    }

    @Test void rejectsSymlinksPermissiveKeysAndDuplicateOptions() throws Exception {
        Path source = directory.resolve("s.xml"); Files.write(source, snapshot(Map.of("x", 1)));
        Path link = directory.resolve("link"); Files.createSymbolicLink(link, source);
        Path keyPath = directory.resolve("key"); Files.write(keyPath, key);
        Files.setPosixFilePermissions(keyPath, PosixFilePermissions.fromString("rw-r--r--"));
        PrintStream sink = new PrintStream(new ByteArrayOutputStream());
        assertEquals(2, SnapshotTool.run(new String[] {"validate", "--input", source.toString(), "--mode", "plain", "--key-file", keyPath.toString()}, sink, sink));
        assertEquals(2, SnapshotTool.run(new String[] {"validate", "--input", link.toString(), "--mode", "plain", "--default-key"}, sink, sink));
        assertEquals(2, SnapshotTool.run(new String[] {"validate", "--input", source.toString(), "--mode", "plain", "--default-key", "--default-key"}, sink, sink));
    }

    @Test void forkedJvmHasNoOsgiLifecycleAndNeverPrintsMalformedInput() throws Exception {
        Path source = directory.resolve("private-input.xml");
        Files.write(source, snapshot(Map.of("number", 42)));
        String javaCommand = Path.of(System.getProperty("java.home"), "bin", "java").toString();
        List<String> command = new java.util.ArrayList<>(List.of(javaCommand, "-cp", System.getProperty("java.class.path"),
                SnapshotTool.class.getName(), "validate", "--input", source.toString(), "--mode", "plain", "--default-key"));
        Process process = new ProcessBuilder(command).start();
        assertTrue(process.waitFor(15, java.util.concurrent.TimeUnit.SECONDS));
        assertEquals(0, process.exitValue());
        String report = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        assertEquals(1, report.lines().count());
        assertTrue(report.startsWith("{\"schema\":1,"));
        assertEquals("", new String(process.getErrorStream().readAllBytes(), StandardCharsets.UTF_8));
        Files.writeString(source, "<private-canary-secret>");
        process = new ProcessBuilder(command).start();
        assertTrue(process.waitFor(15, java.util.concurrent.TimeUnit.SECONDS));
        assertEquals(2, process.exitValue());
        assertEquals(0, process.getInputStream().readAllBytes().length);
        assertEquals("{\"error\":\"SNAPSHOT_VALIDATION_FAILED\"}\n",
                new String(process.getErrorStream().readAllBytes(), StandardCharsets.UTF_8));
    }

    private byte[] raw(String properties) {
        return ("<esf:configurations xmlns:esf='http://eurotech.com/esf/2.0'><esf:configuration pid='p'><esf:properties>"
                + properties + "</esf:properties></esf:configuration></esf:configurations>").getBytes(StandardCharsets.UTF_8);
    }

    private byte[] logicalSnapshot(Map<String, Object> properties) throws Exception {
        var configurations = new XmlComponentConfigurations();
        configurations.setPasswordEncoding(XmlComponentConfigurations.LOGICAL_PASSWORD_ENCODING);
        configurations.setConfigurations(List.of(new ComponentConfigurationImpl("test.pid", null, properties)));
        var output = new ByteArrayOutputStream();
        new XmlJavaComponentConfigurationsMapper(crypto).marshal(output, configurations);
        return output.toByteArray();
    }

    @Test void logicalV1RequiresExplicitPolicyAndNeverGuessesCiphertext() throws Exception {
        String cipherShaped = new String(crypto.encryptAes("literal-cipher-shape".toCharArray()));
        var values = Map.<String,Object>of("password", new Password(cipherShaped),
                "array", new Password[] {new Password("非空 & <值>"), new Password("")},
                "vector", new java.util.Vector<>(List.of(new Password("journal-canary"))));
        byte[] xml = logicalSnapshot(values);
        assertThrows(Exception.class, () -> SnapshotTool.decode(xml, crypto, "authenticated"));
        assertThrows(Exception.class, () -> SnapshotTool.decode(xml, crypto, "legacy"));
        var decoded = SnapshotTool.decode(xml, crypto, "logical-v1");
        assertEquals(4, decoded.report().logical);
        assertEquals(0, decoded.report().authenticated);
        assertEquals(0, decoded.report().legacy);
        var actual = decoded.configurations().getFirst().getConfigurationProperties();
        assertEquals(values.keySet(), actual.keySet());
        assertInstanceOf(Password.class, actual.get("password"));
        assertTrue(values.get("password").toString().equals(actual.get("password").toString()));
        assertInstanceOf(Password[].class, actual.get("array"));
        assertTrue(Arrays.equals(Arrays.stream((Password[]) values.get("array")).map(Object::toString).toArray(),
                Arrays.stream((Password[]) actual.get("array")).map(Object::toString).toArray()));
        assertInstanceOf(java.util.Vector.class, actual.get("vector"));
        assertTrue(((List<?>) values.get("vector")).stream().map(Object::toString).toList()
                .equals(((List<?>) actual.get("vector")).stream().map(Object::toString).toList()));
    }

    @Test void plainLogicalV1CliDoesNotClaimCryptographicAuthentication() throws Exception {
        Path source = directory.resolve("logical.xml");
        Files.write(source, logicalSnapshot(Map.of("p", new Password("private-logical-canary"))));
        var out = new ByteArrayOutputStream(); var err = new ByteArrayOutputStream();
        assertEquals(0, SnapshotTool.run(new String[] {"validate", "--input", source.toString(), "--mode", "plain",
                "--default-key", "--password-policy", "logical-v1"}, new PrintStream(out), new PrintStream(err)));
        assertTrue(out.toString().contains("\"logicalPasswordCount\":1"));
        assertTrue(out.toString().contains("\"passwordEncoding\":\"BASE64_LOGICAL_V1\""));
        assertTrue(out.toString().contains("\"keyAuthenticated\":false"));
        assertFalse(out.toString().contains("private-logical-canary")); assertEquals("", err.toString());
    }

    @Test void authenticatedLogicalV1RequiresActualOuterAead() throws Exception {
        byte[] xml = logicalSnapshot(Map.of("p", new Password("logical-canary")));
        var encrypted = new ByteArrayOutputStream();
        try (var output = crypto.aesEncryptingStream(encrypted)) { output.write(xml); }
        Path source = directory.resolve("logical.aes"); Files.write(source, encrypted.toByteArray());
        Path keyPath = directory.resolve("key"); Files.write(keyPath, key);
        Files.setPosixFilePermissions(keyPath, PosixFilePermissions.fromString("rw-------"));
        var out = new ByteArrayOutputStream();var err = new ByteArrayOutputStream();
        String[] args = {"validate", "--input", source.toString(), "--mode", "aes-gcm", "--key-file", keyPath.toString()};
        assertEquals(0, SnapshotTool.run(args, new PrintStream(out), new PrintStream(err)));
        assertTrue(out.toString().contains("\"keyAuthenticated\":true"));
        assertTrue(out.toString().contains("\"logicalPasswordCount\":1"));
        Files.write(keyPath, new byte[16]);out.reset();
        assertEquals(2, SnapshotTool.run(args, new PrintStream(out), new PrintStream(err)));
        assertEquals("", out.toString());
    }

    @Test void logicalV1RejectsUnknownEncodingMalformedBase64AndInvalidUtf8() throws Exception {
        String valid = new String(logicalSnapshot(Map.of("p", new Password("x"))), StandardCharsets.UTF_8);
        for (String value : List.of(valid.replace("BASE64_LOGICAL_V1", "UNKNOWN_V2"),
                valid.replace("eA==", "%%%"), valid.replace("eA==", "/w=="),
                valid.replace("encrypted=\"true\"", "encrypted=\"false\""))) {
            assertThrows(Exception.class, () -> SnapshotTool.decode(value.getBytes(StandardCharsets.UTF_8), crypto, "logical-v1"));
        }
        assertThrows(Exception.class, () -> SnapshotTool.decode(snapshot(Map.of("x", 1)), crypto, "logical-v1"));
    }
}
