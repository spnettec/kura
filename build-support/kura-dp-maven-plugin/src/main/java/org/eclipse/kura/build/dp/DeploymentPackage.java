/* Copyright (c) 2026 Contributors to the Eclipse Foundation.
 * SPDX-License-Identifier: EPL-2.0
 */
package org.eclipse.kura.build.dp;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.jar.Attributes;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.jar.JarOutputStream;
import java.util.jar.Manifest;

/** Bundle-only Deployment Admin packages, with the existing Kura archive layout. */
final class DeploymentPackage {
    private DeploymentPackage() { }

    static void write(Path output, String symbolicName, String version, List<Path> bundles) throws IOException {
        requireSymbolicName(symbolicName);
        requireVersion(version);
        if (bundles.isEmpty()) {
            throw new IOException("Deployment package has no bundles: " + symbolicName);
        }
        Manifest manifest = new Manifest();
        manifest.getMainAttributes().putValue("Manifest-Version", "1");
        manifest.getMainAttributes().putValue("DeploymentPackage-SymbolicName", symbolicName);
        manifest.getMainAttributes().putValue("DeploymentPackage-Version", version);
        Map<String, Path> entries = new LinkedHashMap<>();
        Map<String, Path> names = new LinkedHashMap<>();
        for (Path bundle : bundles) {
            try (JarFile jar = new JarFile(bundle.toFile())) {
                Manifest bundleManifest = jar.getManifest();
                if (bundleManifest == null) {
                    throw new IOException("Missing bundle manifest: " + bundle);
                }
                Attributes headers = bundleManifest.getMainAttributes();
                String rawName = headers.getValue("Bundle-SymbolicName");
                String name = rawName == null ? "" : rawName.split(";", 2)[0].trim();
                String bundleVersion = headers.getValue("Bundle-Version");
                requireSymbolicName(name);
                requireVersion(bundleVersion);
                if (names.putIfAbsent(name, bundle) != null) {
                    throw new IOException("Duplicate bundle symbolic name: " + name);
                }
                // Fail before producing a deployable archive with a missing private library.
                String classpath = headers.getValue("Bundle-ClassPath");
                if (classpath != null) {
                    for (String item : classpath.split(",")) {
                        String entry = item.trim().replace("\"", "");
                        if (!entry.equals(".") && jar.getJarEntry(entry) == null
                                && jar.stream().noneMatch(e -> e.getName().startsWith(entry + "/"))) {
                            throw new IOException("Missing Bundle-ClassPath entry " + entry + " in " + bundle);
                        }
                    }
                }
                String entry = name + "_" + bundleVersion + ".jar";
                entries.put(entry, bundle);
                Attributes section = new Attributes();
                section.putValue("Bundle-SymbolicName", name);
                section.putValue("Bundle-Version", bundleVersion);
                manifest.getEntries().put(entry, section);
            }
        }
        Files.createDirectories(output.toAbsolutePath().getParent());
        try (JarOutputStream archive = new JarOutputStream(Files.newOutputStream(output))) {
            JarEntry metadata = new JarEntry(JarFile.MANIFEST_NAME);
            metadata.setTime(0);
            archive.putNextEntry(metadata);
            manifest.write(archive);
            archive.closeEntry();
            for (Map.Entry<String, Path> entry : entries.entrySet()) {
                JarEntry jarEntry = new JarEntry(entry.getKey());
                jarEntry.setTime(0);
                archive.putNextEntry(jarEntry);
                Files.copy(entry.getValue(), archive);
                archive.closeEntry();
            }
        }
    }

    private static void requireSymbolicName(String name) throws IOException {
        if (name == null || !name.matches("[A-Za-z0-9_-]+(?:\\.[A-Za-z0-9_-]+)*")) {
            throw new IOException("Invalid or missing symbolic name: " + name);
        }
    }

    private static void requireVersion(String version) throws IOException {
        if (version == null || !version.matches("\\d+\\.\\d+\\.\\d+(?:\\.[A-Za-z0-9_-]+)?")) {
            throw new IOException("Invalid or missing OSGi version: " + version);
        }
    }
}
