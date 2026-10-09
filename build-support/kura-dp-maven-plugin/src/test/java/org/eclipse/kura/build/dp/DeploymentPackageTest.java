/* Copyright (c) 2026 Contributors to the Eclipse Foundation.
 * SPDX-License-Identifier: EPL-2.0
 */
package org.eclipse.kura.build.dp;

import static org.junit.jupiter.api.Assertions.*;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.jar.JarOutputStream;
import java.util.jar.Manifest;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class DeploymentPackageTest {
    @TempDir Path directory;

    private Path bundle(String file, String name, String classpath) throws IOException {
        Manifest manifest = new Manifest();
        manifest.getMainAttributes().putValue("Manifest-Version", "1.0");
        manifest.getMainAttributes().putValue("Bundle-SymbolicName", name + ";singleton:=true");
        manifest.getMainAttributes().putValue("Bundle-Version", "1.2.3.test");
        manifest.getMainAttributes().putValue("Bundle-ClassPath", classpath);
        Path output = directory.resolve(file);
        try (JarOutputStream jar = new JarOutputStream(Files.newOutputStream(output), manifest)) {
            jar.putNextEntry(new JarEntry("lib/private.jar"));
            jar.write(new byte[] {1, 2, 3});
            jar.closeEntry();
        }
        return output;
    }

    @Test void preservesArchiveLayoutManifestAndExactBundleBytes() throws Exception {
        Path input = bundle("input.jar", "test.service", ".,lib/private.jar");
        Path output = directory.resolve("test.dp");
        DeploymentPackage.write(output, "kura-test.dp", "2.0.0.fixed", List.of(input));
        try (JarFile dp = new JarFile(output.toFile())) {
            assertEquals(2, dp.size());
            Manifest manifest = dp.getManifest();
            assertEquals("kura-test.dp", manifest.getMainAttributes().getValue("DeploymentPackage-SymbolicName"));
            assertEquals("2.0.0.fixed", manifest.getMainAttributes().getValue("DeploymentPackage-Version"));
            String entry = "test.service_1.2.3.test.jar";
            assertEquals("test.service", manifest.getAttributes(entry).getValue("Bundle-SymbolicName"));
            assertEquals("1.2.3.test", manifest.getAttributes(entry).getValue("Bundle-Version"));
            assertArrayEquals(Files.readAllBytes(input), dp.getInputStream(dp.getJarEntry(entry)).readAllBytes());
        }
        byte[] first = Files.readAllBytes(output);
        DeploymentPackage.write(output, "kura-test.dp", "2.0.0.fixed", List.of(input));
        assertArrayEquals(first, Files.readAllBytes(output));
    }

    @Test void rejectsMissingPrivateJar() throws Exception {
        Path input = bundle("input.jar", "test.service", ".,lib/absent.jar");
        IOException error = assertThrows(IOException.class, () -> DeploymentPackage.write(
                directory.resolve("test.dp"), "test", "1.0.0", List.of(input)));
        assertTrue(error.getMessage().contains("lib/absent.jar"));
    }

    @Test void rejectsDuplicateBundleNamesEvenWithDifferentInputFiles() throws Exception {
        Path first = bundle("first.jar", "test.service", ".");
        Path second = bundle("second.jar", "test.service", ".");
        assertThrows(IOException.class, () -> DeploymentPackage.write(directory.resolve("test.dp"),
                "test", "1.0.0", List.of(first, second)));
    }

    @Test void rejectsNonBundleAndMissingArtifacts() throws Exception {
        Path plain = directory.resolve("plain.jar");
        try (JarOutputStream ignored = new JarOutputStream(Files.newOutputStream(plain))) { }
        assertThrows(IOException.class, () -> DeploymentPackage.write(directory.resolve("test.dp"),
                "test", "1.0.0", List.of(plain)));
        assertThrows(IOException.class, () -> DeploymentPackage.write(directory.resolve("test.dp"),
                "test", "1.0.0", List.of(directory.resolve("absent.jar"))));
    }

    @Test void rejectsEmptyPackageAndInvalidVersionOrName() throws Exception {
        assertThrows(IOException.class, () -> DeploymentPackage.write(directory.resolve("test.dp"),
                "test", "1.0.0", List.of()));
        Path input = bundle("input.jar", "test.service", ".");
        assertThrows(IOException.class, () -> DeploymentPackage.write(directory.resolve("test.dp"),
                "test", "1.0.0-SNAPSHOT", List.of(input)));
        assertThrows(IOException.class, () -> DeploymentPackage.write(directory.resolve("test.dp"),
                "../test", "1.0.0", List.of(input)));
    }
}
