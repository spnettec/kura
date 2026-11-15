/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.configuration.XmlComponentConfigurations;
import org.eclipse.kura.core.crypto.CryptoServiceImpl;
import org.eclipse.kura.internal.xml.marshaller.unmarshaller.XmlJavaComponentConfigurationsMapper;

/** Post-package probe of the actual standalone JAR/classpath; only creates disposable synthetic files. */
public final class GenerationArtifactProbe {
    public static void main(String[] args) throws Exception {
        if (args.length != 1) { throw new IllegalArgumentException("Packaged tool path required"); }
        Path jar = Path.of(args[0]).toAbsolutePath();
        Path root = Files.createTempDirectory("kura-generation-artifact-");
        try {
            byte[] old = "0123456789abcdef".getBytes(StandardCharsets.US_ASCII);
            byte[] active = new byte[32]; Arrays.fill(active, (byte) 19);
            var bytes = new ByteArrayOutputStream();
            bytes.write("YOFC-KURA-KEYRING-v1\n".getBytes(StandardCharsets.US_ASCII));
            bytes.write(new byte[] {2, 1, 0, 16}); bytes.write(old); bytes.write(32); bytes.write(active);
            byte[] raw = bytes.toByteArray();
            Path key = root.resolve("keyring"); Files.write(key, raw);
            Files.setPosixFilePermissions(key, PosixFilePermissions.fromString("rw-------"));
            var oldCrypto = CryptoServiceImpl.forSnapshotRecovery(old, false);
            var current = CryptoServiceImpl.forKeyRingRecovery(raw);
            var source = new XmlComponentConfigurations();
            source.setConfigurations(List.of(new ComponentConfigurationImpl("probe", null, Map.of(
                    "old", new Password(oldCrypto.encryptAes("old-artifact-canary".toCharArray())),
                    "new", new Password(current.encryptAes("new-artifact-canary".toCharArray()))))));
            var xml = new ByteArrayOutputStream();
            new XmlJavaComponentConfigurationsMapper(current).marshal(xml, source);
            var encrypted = new ByteArrayOutputStream();
            try (var output = current.aesEncryptingStream(encrypted)) { output.write(xml.toByteArray()); }
            Path snapshot = root.resolve("snapshot.aes"); Files.write(snapshot, encrypted.toByteArray());
            String digest = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(raw));
            Process child = new ProcessBuilder(Path.of(System.getProperty("java.home"), "bin/java").toString(),
                    "-jar", jar.toString(), "validate", "--input", snapshot.toString(), "--mode", "aes-gcm",
                    "--keyring-file", key.toString(), "--keyring-sha256", digest).start();
            if (!child.waitFor(15, TimeUnit.SECONDS)) {
                child.destroyForcibly(); child.waitFor();
                throw new IllegalStateException("Packaged validator did not terminate");
            }
            String report = new String(child.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
            if (child.exitValue() != 0 || child.getErrorStream().readAllBytes().length != 0
                    || !report.contains("\"authenticatedPasswordCount\":2")
                    || !report.contains("\"fullRecoveryVerified\":false") || report.contains("artifact-canary")
                    || !Arrays.equals(raw, Files.readAllBytes(key))) {
                throw new IllegalStateException("Packaged generation validator refused its synthetic fixture");
            }
            System.out.println("PACKAGED_GENERATION_CLI_OK");
        } finally {
            try (var paths = Files.walk(root)) {
                for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) { Files.delete(path); }
            }
        }
    }
}
