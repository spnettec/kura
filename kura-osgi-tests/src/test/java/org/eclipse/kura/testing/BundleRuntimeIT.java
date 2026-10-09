/*
 * Copyright (c) 2026 Contributors to the Eclipse Foundation.
 * SPDX-License-Identifier: EPL-2.0
 */
package org.eclipse.kura.testing;

import static org.junit.jupiter.api.Assertions.*;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPairGenerator;
import java.security.KeyStore.PrivateKeyEntry;
import java.security.PublicKey;
import java.security.cert.Certificate;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.jar.JarOutputStream;
import java.util.jar.Manifest;

import org.eclipse.kura.testing.osgi.EquinoxExtension;
import org.eclipse.kura.testing.osgi.EquinoxRuntime;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.osgi.framework.Bundle;

/** The test controller deliberately has no Kura business API JAR on its classpath. */
@ExtendWith(EquinoxExtension.class)
class BundleRuntimeIT {
    private static final String API = "org.eclipse.kura.api";
    private static final String JWT = "org.eclipse.kura.core.token.jwt";
    private static final String ISSUER = "org.eclipse.kura.core.token.jwt.issuer.JwtIssuingService";
    private static final String SERVICE = "org.eclipse.kura.security.token.TokenIssuingService";
    private static final Path BUNDLES = Path.of("target/it-bundles");

    private List<Bundle> install(EquinoxRuntime runtime, Path replacement) throws Exception {
        List<Bundle> bundles = new ArrayList<>();
        try (var paths = Files.list(BUNDLES)) {
            for (Path path : paths.filter(p -> p.toString().endsWith(".jar")).sorted().toList()) {
                bundles.add(runtime.install(replacement != null && path.getFileName().toString().equals(JWT + ".jar") ? replacement : path));
            }
        }
        return bundles;
    }

    private void start(EquinoxRuntime runtime, Path replacement) throws Exception {
        var bundles = install(runtime, replacement);
        runtime.resolve(bundles);
        runtime.start(bundles);
    }

    @Test void registersOnlyAfterConfigurationAndTracksDynamicKeystore(EquinoxRuntime runtime) throws Exception {
        assertThrows(ClassNotFoundException.class, () -> Class.forName(SERVICE));
        start(runtime, null);
        assertFalse(runtime.hasService(SERVICE, null), "configuration-policy=require must be respected");
        runtime.configure(ISSUER, Map.of("issuer", "osgi-test", "maximum.lifetime.seconds", 60));
        try (var service = runtime.service(SERVICE, null, Duration.ofSeconds(5))) {
            assertEquals(ISSUER, service.property("kura.service.pid"));
            assertEquals("org.eclipse.kura.api", runtime.packageProvider(JWT, "org.eclipse.kura.security.token"));
            assertNotNull(runtime.bundle(JWT).loadClass("com.auth0.jwt.JWT"), "embedded java-jwt must be loadable");
            Class<?> requestType = runtime.bundle(API).loadClass("org.eclipse.kura.security.token.TokenIssueRequest");
            Object builder = EquinoxRuntime.invoke(requestType, null, "builder", "device1");
            Object request = EquinoxRuntime.invoke(builder.getClass(), builder, "build");
            assertEquals("org.eclipse.kura.KuraException", assertThrows(Exception.class, () -> service.call("issue", request)).getClass().getName());
            var generator = KeyPairGenerator.getInstance("RSA");
            generator.initialize(2048);
            var pair = generator.generateKeyPair();
            var entry = new PrivateKeyEntry(pair.getPrivate(), new Certificate[] {new Certificate("test") {
                @Override public byte[] getEncoded() { return new byte[0]; }
                @Override public void verify(PublicKey key) { }
                @Override public void verify(PublicKey key, String provider) { }
                @Override public String toString() { return "local test certificate"; }
                @Override public PublicKey getPublicKey() { return pair.getPublic(); }
            }});
            try (var registration = runtime.register(API, "org.eclipse.kura.security.keystore.KeystoreService",
                    (proxy, method, args) -> switch (method.getName()) {
                        case "getEntry" -> entry;
                        case "hashCode" -> System.identityHashCode(proxy);
                        case "equals" -> proxy == args[0];
                        case "toString" -> "isolated mock keystore";
                        default -> null;
                    }, Map.of("kura.service.pid", "test.keystore"))) {
                eventually(() -> service.call("issue", request) instanceof String);
                runtime.configure(ISSUER, Map.of("issuer", "osgi-test", "maximum.lifetime.seconds", 30));
                eventually(() -> service.call("getMaximumLifetime").toString().equals("Optional[PT30S]"));
            }
            eventually(() -> {
                try { service.call("issue", request); return false; }
                catch (Exception e) { return e.getClass().getName().equals("org.eclipse.kura.KuraException"); }
            });
        }
    }

    @Test void attachesLocalizationFragmentAndFindsFallbackResources(EquinoxRuntime runtime) throws Exception {
        start(runtime, null);
        var host = runtime.bundle("org.eclipse.kura.localization");
        assertEquals(Bundle.RESOLVED, runtime.bundle("org.eclipse.kura.localization.resources").getState());
        Class<?> messages = host.loadClass("org.eclipse.kura.localization.resources.AssetMessages");
        Class<?> c10n = host.loadClass("com.github.rodionmoiseev.c10n.C10N");
        Object annotations = host.loadClass("com.github.rodionmoiseev.c10n.annotations.DefaultC10NAnnotations").getConstructor().newInstance();
        EquinoxRuntime.invoke(c10n, null, "configure", annotations);
        Object english = EquinoxRuntime.invoke(c10n, null, "get", messages, Locale.ENGLISH);
        assertEquals("Activating Asset...", EquinoxRuntime.invoke(messages, english, "activating"));
        Object fallback = EquinoxRuntime.invoke(c10n, null, "get", messages, Locale.CHINESE);
        // Frozen Tycho baseline returns the key for a locale without an annotation.
        assertEquals("AssetMessages.activating", EquinoxRuntime.invoke(messages, fallback, "activating"));
    }

    @Test void detectsIncorrectImportRange(EquinoxRuntime runtime) throws Exception {
        var bundles = install(runtime, fixture("range"));
        assertThrows(IllegalStateException.class, () -> runtime.resolve(bundles));
        assertEquals(Bundle.INSTALLED, runtime.bundle(JWT).getState());
    }

    @Test void detectsMissingEmbeddedLibrary(EquinoxRuntime runtime) throws Exception {
        start(runtime, fixture("embed"));
        assertThrows(ClassNotFoundException.class, () -> runtime.bundle(JWT).loadClass("com.auth0.jwt.JWT"));
    }

    @Test void detectsMissingDsDescriptor(EquinoxRuntime runtime) throws Exception {
        start(runtime, fixture("descriptor"));
        runtime.configure(ISSUER, Map.of("issuer", "test"));
        assertFalse(runtime.hasService(SERVICE, null));
        assertThrows(java.util.concurrent.TimeoutException.class, () -> runtime.service(SERVICE, null, Duration.ofMillis(200)));
    }

    @Test void detectsMissingMandatoryReference(EquinoxRuntime runtime) throws Exception {
        start(runtime, fixture("reference"));
        runtime.configure(ISSUER, Map.of("issuer", "test"));
        assertThrows(java.util.concurrent.TimeoutException.class, () -> runtime.service(SERVICE, null, Duration.ofMillis(300)));
        assertTrue(Files.readString(runtime.diagnose("missing-mandatory-keystore")).contains("missing=KeystoreService"));
    }

    private Path fixture(String mode) throws Exception {
        Path output = Path.of("target/fixtures/" + mode + ".jar");
        Files.createDirectories(output.getParent());
        try (JarFile source = new JarFile(BUNDLES.resolve(JWT + ".jar").toFile())) {
            Manifest manifest = source.getManifest();
            if (mode.equals("range")) {
                String imports = manifest.getMainAttributes().getValue("Import-Package");
                String changed = imports.replace("org.eclipse.kura;version=\"[1.8,2.0)\"", "org.eclipse.kura;version=\"[99.0,100.0)\"");
                assertNotEquals(imports, changed, "negative fixture must change the intended import");
                manifest.getMainAttributes().putValue("Import-Package", changed);
            }
            try (JarOutputStream jar = new JarOutputStream(Files.newOutputStream(output), manifest)) {
                for (JarEntry entry : source.stream().toList()) {
                    String name = entry.getName();
                    if (name.equals("META-INF/MANIFEST.MF") || entry.isDirectory()
                            || mode.equals("embed") && name.equals("lib/java-jwt.jar")
                            || mode.equals("descriptor") && name.startsWith("OSGI-INF/") && name.endsWith(".xml")) { continue; }
                    jar.putNextEntry(new JarEntry(name));
                    try (InputStream in = source.getInputStream(entry)) {
                        if (mode.equals("reference") && name.startsWith("OSGI-INF/") && name.endsWith(".xml")) {
                            jar.write(new String(in.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8)
                                    .replace("cardinality=\"0..1\"", "cardinality=\"1..1\"")
                                    .getBytes(java.nio.charset.StandardCharsets.UTF_8));
                        } else { in.transferTo(jar); }
                    }
                    jar.closeEntry();
                }
            }
        }
        return output;
    }

    private static void eventually(Callable<Boolean> assertion) throws Exception {
        long deadline = System.nanoTime() + Duration.ofSeconds(5).toNanos();
        Exception last = null;
        do {
            try { if (assertion.call()) { return; } } catch (Exception exception) { last = exception; }
            Thread.sleep(25);
        } while (System.nanoTime() < deadline);
        throw new AssertionError("Asynchronous OSGi transition did not complete", last);
    }
}
