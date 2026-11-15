/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import static org.junit.jupiter.api.Assertions.*;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;

import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.configuration.XmlComponentConfigurations;
import org.eclipse.kura.core.crypto.CryptoServiceImpl;
import org.eclipse.kura.internal.xml.marshaller.unmarshaller.XmlJavaComponentConfigurationsMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class KeyGenerationRecoveryTest {
    @TempDir Path directory;
    private final byte[] legacy = "0123456789abcdef".getBytes(StandardCharsets.US_ASCII);
    private final byte[] previous = repeated(32, (byte) 7);
    private final byte[] active = repeated(32, (byte) 19);

    private static byte[] repeated(int length, byte value) {
        byte[] bytes = new byte[length]; Arrays.fill(bytes, value); return bytes;
    }

    private byte[] ring(byte[]... keys) throws Exception {
        var output = new ByteArrayOutputStream();
        output.write("YOFC-KURA-KEYRING-v1\n".getBytes(StandardCharsets.US_ASCII));
        output.write(new byte[] {(byte) keys.length, (byte) (keys.length - 1), 0});
        for (byte[] key : keys) { output.write(key.length); output.write(key); }
        return output.toByteArray();
    }

    private String sha(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }

    private Path privateFile(String name, byte[] bytes) throws Exception {
        Path path = directory.resolve(name);
        Files.write(path, bytes);
        Files.setPosixFilePermissions(path, PosixFilePermissions.fromString("rw-------"));
        return path;
    }

    private byte[] mixedSnapshot() throws Exception {
        var old = CryptoServiceImpl.forSnapshotRecovery(legacy, false);
        var middle = CryptoServiceImpl.forKeyRingRecovery(ring(legacy, previous));
        var current = CryptoServiceImpl.forKeyRingRecovery(ring(legacy, previous, active));
        var configurations = new XmlComponentConfigurations();
        configurations.setConfigurations(List.of(new ComponentConfigurationImpl("test.generations", null, Map.of(
                "old", new Password(old.encryptAes("old-canary".toCharArray())),
                "middle", new Password(middle.encryptAes("middle-canary".toCharArray())),
                "current", new Password(current.encryptAes("current-canary".toCharArray()))))));
        var xml = new ByteArrayOutputStream();
        new XmlJavaComponentConfigurationsMapper(current).marshal(xml, configurations);
        return xml.toByteArray();
    }

    private byte[] encrypted(CryptoServiceImpl crypto, byte[] xml) throws Exception {
        var bytes = new ByteArrayOutputStream();
        try (var output = crypto.aesEncryptingStream(bytes)) { output.write(xml); }
        return bytes.toByteArray();
    }

    @Test void cliReadsMixedPasswordGenerationsInPlainLegacyAndTaggedOuterArtifacts() throws Exception {
        byte[] raw = ring(legacy, previous, active);
        Path credential = privateFile("generations", raw);
        var before = Files.readAttributes(credential, "unix:ino,size,mode,ctime", LinkOption.NOFOLLOW_LINKS);
        byte[] xml = mixedSnapshot();
        var current = CryptoServiceImpl.forKeyRingRecovery(raw);
        var versions = List.of(xml, encrypted(CryptoServiceImpl.forSnapshotRecovery(legacy, false), xml),
                encrypted(CryptoServiceImpl.forKeyRingRecovery(ring(legacy, previous)), xml), encrypted(current, xml));
        for (int n = 0; n < versions.size(); n++) {
            Path source = privateFile("snapshot-" + n, versions.get(n));
            var out = new ByteArrayOutputStream(); var err = new ByteArrayOutputStream();
            String[] args = {"validate", "--input", source.toString(), "--mode", n == 0 ? "plain" : "aes-gcm",
                    "--keyring-file", credential.toString(), "--keyring-sha256", sha(raw)};
            assertEquals(0, SnapshotTool.run(args, new PrintStream(out), new PrintStream(err)), err.toString());
            assertEquals("", err.toString());
            assertTrue(out.toString().contains("\"authenticatedPasswordCount\":3"));
            assertTrue(out.toString().contains("\"fullRecoveryVerified\":false"));
            assertArrayEquals(versions.get(n), Files.readAllBytes(source));
        }
        assertArrayEquals(raw, Files.readAllBytes(credential));
        assertEquals(before, Files.readAttributes(credential, "unix:ino,size,mode,ctime", LinkOption.NOFOLLOW_LINKS));
    }

    @Test void controlledBootstrapReadsAllGenerationsFromAnExplicitlyBoundCredential() throws Exception {
        byte[] raw = ring(legacy, previous, active);
        Path credential = privateFile("generations", raw);
        var manifest = RecoveryBootstrap.manifest(privateFile("request", request(credential, sha(raw)).getBytes(StandardCharsets.UTF_8)));
        var crypto = RecoveryBootstrap.recoveryCrypto(manifest);
        var decoded = SnapshotTool.decode(mixedSnapshot(), crypto, "authenticated");
        assertEquals(3, decoded.report().authenticated);
        Map<String, Object> values = decoded.configurations().getFirst().getConfigurationProperties();
        for (String name : List.of("old", "middle", "current")) {
            assertInstanceOf(Password.class, values.get(name));
            assertArrayEquals((name + "-canary").toCharArray(), crypto.decryptAes(((Password) values.get(name)).getPassword()));
        }
        var stored = RecoveryBootstrap.targetProperties(decoded.configurations().getFirst(), crypto);
        for (String name : values.keySet()) {
            assertArrayEquals(((Password) values.get(name)).getPassword(), ((Password) stored.get(name)).getPassword());
        }
    }

    private String request(Path ring, String expected) {
        return "schema=1\nrestore.id=rec-11111111-1111-1111-1111-111111111111\nsnapshot.path=/fixed/snapshot.xml\n"
                + "snapshot.sha256=" + "0".repeat(64) + "\nsnapshot.mode=plain\npassword.policy=authenticated\n"
                + "receipt.path=/fixed/result\ncrypto.keyring.file=" + ring + "\ncrypto.keyring.sha256=" + expected + "\n";
    }

    @Test void bootstrapRejectsAmbiguousUnboundOrNonabsoluteGenerationInputs() throws Exception {
        Path credential = privateFile("generations", ring(legacy, previous, active));
        String valid = request(credential, sha(Files.readAllBytes(credential)));
        for (String invalid : List.of(valid + "crypto.default=true\n", valid + "crypto.key.file=/key\n",
                valid.replaceAll("crypto.keyring.sha256=[^\\n]+\\n", ""),
                valid.replaceAll("crypto.keyring.file=[^\\n]+", "crypto.keyring.file=relative"),
                valid.replaceAll("crypto.keyring.sha256=[^\\n]+", "crypto.keyring.sha256=not-a-digest"))) {
            Path request = privateFile("request-" + java.util.UUID.randomUUID(), invalid.getBytes(StandardCharsets.UTF_8));
            assertThrows(Exception.class, () -> RecoveryBootstrap.manifest(request));
        }
    }

    @Test void aPresentWrongOrMalformedRingNeverFallsBackToTheActiveOrDefaultKey() throws Exception {
        byte[] raw = ring(legacy, previous, active);
        Path credential = privateFile("generations", raw);
        assertThrows(Exception.class, () -> RecoveryCrypto.load(null, credential, "0".repeat(64), false));
        byte[] altered = raw.clone(); altered[altered.length - 1] ^= 1;
        Files.write(credential, altered);
        assertThrows(Exception.class, () -> RecoveryCrypto.load(null, credential, sha(raw), false));
        for (byte[] malformed : List.of(Arrays.copyOf(raw, raw.length - 1), repeated(513, (byte) 1),
                ring(legacy, active, active))) {
            Files.write(credential, malformed);
            assertThrows(Exception.class, () -> RecoveryCrypto.load(null, credential, sha(malformed), false));
        }
    }

    @Test void managedRecoveryBindsPid1ActiveAndRingCredentialsWithoutManifestKeyPaths() throws Exception {
        byte[] raw=ring(legacy,previous,active);
        privateFile("kura_encryption_key",active); privateFile("kura_encryption_keyring",raw);
        var crypto=RecoveryCrypto.loadManaged(directory,sha(active),sha(raw));
        assertEquals(3,SnapshotTool.decode(mixedSnapshot(),crypto,"authenticated").report().authenticated);
        assertThrows(Exception.class,()->RecoveryCrypto.loadManaged(directory,sha(active),"none"));
        assertThrows(Exception.class,()->RecoveryCrypto.loadManaged(directory,"0".repeat(64),sha(raw)));
        byte[] wrong=ring(legacy,previous,repeated(32,(byte)20));
        Files.write(directory.resolve("kura_encryption_keyring"),wrong);
        assertThrows(Exception.class,()->RecoveryCrypto.loadManaged(directory,sha(active),sha(wrong)));
        Files.delete(directory.resolve("kura_encryption_keyring"));
        var single=RecoveryCrypto.loadManaged(directory,sha(active),"none");
        var encrypted=single.encryptAes("single-canary".toCharArray());
        assertArrayEquals("single-canary".toCharArray(),single.decryptAes(encrypted));
        assertThrows(Exception.class,()->RecoveryCrypto.loadManaged(directory,sha(active),sha(raw)));
    }

    @Test void managedManifestRequiresCompleteExclusiveFingerprintSelection() throws Exception {
        String base=request(directory.resolve("unused"),"0".repeat(64)).replaceAll("crypto.keyring[^\\n]+\\n","");
        String managed=base+"crypto.systemd.credentials=true\ncrypto.key.sha256="+sha(active)+"\ncrypto.ring.sha256=none\n";
        assertTrue(RecoveryBootstrap.manifest(privateFile("managed-request",managed.getBytes(StandardCharsets.UTF_8)))
                .containsKey("crypto.systemd.credentials"));
        for(String invalid:List.of(managed+"crypto.default=true\n",managed+"crypto.key.file=/key\n",
                managed.replace("crypto.ring.sha256=none\n",""),managed.replace("crypto.systemd.credentials=true\n",""),
                managed.replace("crypto.systemd.credentials=true","crypto.systemd.credentials=false"),
                managed.replace("crypto.ring.sha256=none","crypto.ring.sha256=bad"))) {
            assertThrows(Exception.class,()->RecoveryBootstrap.manifest(privateFile("invalid-managed",invalid.getBytes(StandardCharsets.UTF_8))));
        }
        // No environment credential directory is installed in unit tests; no implicit fallback.
        assertThrows(Exception.class,()->RecoveryBootstrap.recoveryCrypto(Map.of("crypto.systemd.credentials","true",
                "crypto.key.sha256",sha(active),"crypto.ring.sha256","none")));
    }

    @Test void privateGenerationInputsRejectLinksHardlinksAndPublicPermissions() throws Exception {
        byte[] raw = ring(legacy, previous, active);
        Path credential = privateFile("generations", raw);
        Path symlink = directory.resolve("symlink"); Files.createSymbolicLink(symlink, credential);
        assertThrows(Exception.class, () -> RecoveryCrypto.load(null, symlink, sha(raw), false));
        Path link = directory.resolve("hardlink"); Files.createLink(link, credential);
        assertThrows(Exception.class, () -> RecoveryCrypto.load(null, link, sha(raw), false));
        Files.delete(link);
        Files.setPosixFilePermissions(credential, PosixFilePermissions.fromString("rw-r--r--"));
        assertThrows(Exception.class, () -> RecoveryCrypto.load(null, credential, sha(raw), false));
        assertArrayEquals(raw, Files.readAllBytes(credential));
    }

    private byte[] passwordXml(String value) {
        return ("<esf:configurations xmlns:esf='http://eurotech.com/esf/2.0'><esf:configuration pid='p'><esf:properties>"
                + "<esf:property name='p' type='Password' array='false' encrypted='true'><esf:value>" + value
                + "</esf:value></esf:property></esf:properties></esf:configuration></esf:configurations>")
                .getBytes(StandardCharsets.UTF_8);
    }

    @Test void taggedPasswordAuthenticationCannotBeDowngradedByLegacyCompatibility() throws Exception {
        var crypto = CryptoServiceImpl.forKeyRingRecovery(ring(legacy, previous, active));
        String valid = new String(crypto.encryptAes("tag-canary".toCharArray()));
        assertEquals(1, SnapshotTool.validate(passwordXml(valid), crypto, "authenticated").authenticated);
        byte[] ciphertext = java.util.Base64.getDecoder().decode(valid.substring(valid.indexOf('-') + 1));
        ciphertext[ciphertext.length - 1] ^= 1;
        String tampered = valid.substring(0, valid.indexOf('-') + 1) + java.util.Base64.getEncoder().encodeToString(ciphertext);
        List<String> invalid = List.of(tampered, valid.replace(sha(active), "0".repeat(64)),
                valid.replace("KURA2.", "KURA9."), "KURA2.invalid-generation.iv-ciphertext");
        for (String candidate : invalid) {
            for (String policy : List.of("authenticated", "legacy")) {
                assertThrows(Exception.class, () -> SnapshotTool.validate(passwordXml(candidate), crypto, policy));
                String wrapped = java.util.Base64.getEncoder().encodeToString(candidate.getBytes(StandardCharsets.UTF_8));
                assertThrows(Exception.class, () -> SnapshotTool.validate(passwordXml(wrapped), crypto, policy));
            }
        }
    }

    @Test void failedGenerationCliValidationDoesNotPrintPrivateInputOrPublishFiles() throws Exception {
        byte[] raw = ring(legacy, previous, active);
        Path credential = privateFile("generations", raw);
        Path input = privateFile("snapshot", mixedSnapshot());
        var out = new ByteArrayOutputStream(); var err = new ByteArrayOutputStream();
        String[] args = {"validate", "--input", input.toString(), "--mode", "plain", "--keyring-file", credential.toString(),
                "--keyring-sha256", "0".repeat(64)};
        assertEquals(2, SnapshotTool.run(args, new PrintStream(out), new PrintStream(err)));
        assertEquals("", out.toString());
        assertEquals("{\"error\":\"SNAPSHOT_VALIDATION_FAILED\"}" + System.lineSeparator(), err.toString());
        try (var files = Files.list(directory)) { assertEquals(2, files.count()); }
        assertArrayEquals(raw, Files.readAllBytes(credential));
    }

    @Test void controlledLogicalPasswordsThatLookLikeCiphertextMustStillBeEncryptedAsLiteralValues() throws Exception {
        var crypto = CryptoServiceImpl.forKeyRingRecovery(ring(legacy, previous, active));
        String literal = new String(crypto.encryptAes("this-is-literal-password-text".toCharArray()));
        var source = new XmlComponentConfigurations();
        source.setPasswordEncoding(XmlComponentConfigurations.LOGICAL_PASSWORD_ENCODING);
        Map<String,Object> values = Map.of("scalar", new Password(literal),
                "array", new Password[] {new Password(literal), new Password("")},
                "vector", new java.util.Vector<>(List.of(new Password(literal))),
                "list", List.of(new Password(literal)));
        source.setConfigurations(List.of(new ComponentConfigurationImpl("logical.test", null, values)));
        var xml = new ByteArrayOutputStream();
        new XmlJavaComponentConfigurationsMapper(crypto).marshal(xml, source);
        var decoded = SnapshotTool.decode(xml.toByteArray(), crypto, "logical-v1");
        var stored = RecoveryBootstrap.targetProperties(decoded.configurations().getFirst(), crypto);
        assertArrayEquals(literal.toCharArray(), crypto.decryptAes(((Password) stored.get("scalar")).getPassword()));
        assertArrayEquals(literal.toCharArray(), crypto.decryptAes(((Password[]) stored.get("array"))[0].getPassword()));
        assertArrayEquals(new char[0], crypto.decryptAes(((Password[]) stored.get("array"))[1].getPassword()));
        assertInstanceOf(java.util.Vector.class, stored.get("vector"));
        assertArrayEquals(literal.toCharArray(), crypto.decryptAes(((Password) ((List<?>) stored.get("vector")).getFirst()).getPassword()));
        assertInstanceOf(List.class, stored.get("list"));
        assertFalse(stored.get("list") instanceof java.util.Vector<?>);
        assertArrayEquals(literal.toCharArray(), crypto.decryptAes(((Password) ((List<?>) stored.get("list")).getFirst()).getPassword()));
        assertArrayEquals(literal.toCharArray(), ((Password) values.get("scalar")).getPassword());
    }
}
