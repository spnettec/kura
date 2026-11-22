/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tests.keygeneration;

import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.Properties;

import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.crypto.CryptoService;
import org.osgi.framework.Bundle;
import org.osgi.framework.FrameworkUtil;
import org.osgi.service.component.ComponentContext;

/** Test-only DS consumer. No canonical key access and no configuration writes. */
public final class GenerationProbe {
    private static final char[] VALUE = "disposable-original-provider-value".toCharArray();
    private CryptoService crypto;
    private ConfigurationService configuration;

    public void setCrypto(CryptoService value) {
        this.crypto = value;
    }

    public void setConfiguration(ConfigurationService value) {
        this.configuration = value;
    }

    private static String digest(byte[] value) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value));
    }

    private static void implementation(Properties result, String role, Object provider) throws Exception {
        Class<?> type = provider.getClass();
        Bundle bundle = FrameworkUtil.getBundle(type);
        if (bundle == null || bundle.getState() != Bundle.ACTIVE) {
            throw new IllegalStateException("Required real provider is not active");
        }
        result.setProperty(role + "Bundle", bundle.getSymbolicName());
        result.setProperty(role + "Class", type.getName());
        result.setProperty(role + "Version", bundle.getVersion().toString());
        result.setProperty(role + "State", Integer.toString(bundle.getState()));
        try (InputStream resource = type.getResourceAsStream("/" + type.getName().replace('.', '/') + ".class")) {
            if (resource == null) {
                throw new IllegalStateException("Provider class resource unavailable");
            }
            result.setProperty(role + "ClassSha256", digest(resource.readAllBytes()));
        }
    }

    public void activate(ComponentContext context) throws Exception {
        Path directory = Path.of("/opt/eclipse/kura/data/key-generation-probe");
        Files.createDirectories(directory);
        Path original = directory.resolve("original.cipher");
        if (!Files.exists(original)) {
            char[] encrypted = this.crypto.encryptAes(VALUE);
            Files.writeString(original, new String(encrypted), StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW);
        }
        byte[] originalBytes = Files.readAllBytes(original);
        char[] originalEncrypted = new String(originalBytes, StandardCharsets.UTF_8).toCharArray();
        if (!Arrays.equals(VALUE, this.crypto.decryptAes(originalEncrypted))) {
            throw new IllegalStateException("Original provider value changed");
        }
        char[] fresh = this.crypto.encryptAes(VALUE);
        if (!Arrays.equals(VALUE, this.crypto.decryptAes(fresh))) {
            throw new IllegalStateException("Current provider round trip failed");
        }
        String freshText = new String(fresh);
        Files.writeString(directory.resolve("current.cipher"), freshText, StandardCharsets.UTF_8);
        Properties result = new Properties();
        result.setProperty("pid", Long.toString(ProcessHandle.current().pid()));
        result.setProperty("originalSha256", digest(originalBytes));
        result.setProperty("originalDecrypted", "true");
        result.setProperty("currentDecrypted", "true");
        result.setProperty("currentHasGeneration", Boolean.toString(freshText.startsWith("KURA2.")));
        result.setProperty("currentKeyId", freshText.startsWith("KURA2.") ? freshText.split("\\.", 3)[1] : "legacy");
        result.setProperty("customKey", Boolean.toString(this.crypto.hasCustomEncryptionKey()));
        result.setProperty("snapshotCount", Integer.toString(this.configuration.getSnapshots().size()));
        implementation(result, "crypto", this.crypto);
        implementation(result, "configuration", this.configuration);
        for (Bundle bundle : context.getBundleContext().getBundles()) {
            if ("org.eclipse.kura.xml.marshaller.unmarshaller.provider".equals(bundle.getSymbolicName())) {
                if (bundle.getState() != Bundle.ACTIVE) {
                    throw new IllegalStateException("Snapshot reader is not active");
                }
                result.setProperty("snapshotBundle", bundle.getSymbolicName());
                result.setProperty("snapshotState", Integer.toString(bundle.getState()));
            }
        }
        if (!result.containsKey("snapshotBundle")) {
            throw new IllegalStateException("Snapshot reader is missing");
        }
        Path temporary = Files.createTempFile(directory, ".status-", ".tmp");
        try (OutputStream output = Files.newOutputStream(temporary)) {
            result.store(output, "Disposable real OSGi provider probe; no raw keys or values");
        }
        Files.move(temporary, directory.resolve("status.properties"), StandardCopyOption.ATOMIC_MOVE,
                StandardCopyOption.REPLACE_EXISTING);
    }
}
