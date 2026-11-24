/* Copyright (c) 2026 YOFC IOT and others. SPDX-License-Identifier: EPL-2.0 */
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Comparator;
import java.util.List;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.jar.JarOutputStream;

// Build the Linux ARM64 variant of Xerial's JNI from the matching Maven sources.
class SqlcipherDriver {
    private static final String JNI = "org/sqlite/native/Linux/aarch64/libsqlitejdbc.so";

    public static void main(String[] args) throws Exception {
        if (!System.getProperty("os.name").equals("Linux") || !System.getProperty("os.arch").equals("aarch64")) {
            throw new IOException("Build the SQLCipher deployment package on GNU/Linux ARM64");
        }
        Path input = Path.of(args[0]).toAbsolutePath();
        Path work = Files.createTempDirectory(input, "build-");
        try {
            Path driver = input.resolve("driver.jar");
            try (var sources = new JarFile(input.resolve("sources.jar").toFile())) {
                for (String file : List.of("NativeDB.java", "NativeDB.c")) {
                    try (var stream = sources.getInputStream(sources.getJarEntry("org/sqlite/core/" + file))) {
                        Files.copy(stream, work.resolve(file));
                    }
                }
            }
            Path jdk = Path.of(System.getProperty("java.home"));
            run(work, jdk.resolve("bin/javac").toString(), "-proc:none", "-cp", driver.toString(), "-h", ".", "-d", ".", "NativeDB.java");
            Files.move(work.resolve("org_sqlite_core_NativeDB.h"), work.resolve("NativeDB.h"));
            Path cflags = packageFlags(work, "--cflags");
            Path libs = packageFlags(work, "--libs");
            run(work, "cc", "-O2", "-fPIC", "-shared", "-Wl,-z,defs", "-I" + jdk.resolve("include"),
                    "-I" + jdk.resolve("include/linux"), "@" + cflags, "NativeDB.c",
                    "@" + libs, "-o", "libsqlitejdbc.so");
            Path output = work.resolve("sqlcipher-jdbc.jar");
            writeJar(driver, work.resolve("libsqlitejdbc.so"), output);
            verifyEngine(output);
            Files.move(output, input.resolve("sqlcipher-jdbc.jar"), StandardCopyOption.ATOMIC_MOVE,
                    StandardCopyOption.REPLACE_EXISTING);
        } finally {
            try (var paths = Files.walk(work)) {
                for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) {
                    Files.delete(path);
                }
            }
        }
    }

    private static Path packageFlags(Path work, String option) throws Exception {
        Path flags = work.resolve("sqlcipher" + option);
        // Compiler response files preserve pkg-config's argument escaping.
        var process = new ProcessBuilder("pkg-config", option, "sqlcipher")
                .redirectOutput(flags.toFile())
                .redirectError(ProcessBuilder.Redirect.INHERIT).start();
        if (process.waitFor() != 0) {
            throw new IOException("Cannot read SQLCipher compiler options using pkg-config " + option);
        }
        return flags;
    }

    private static void run(Path directory, String... command) throws Exception {
        var process = new ProcessBuilder(command).directory(directory.toFile()).inheritIO().start();
        if (process.waitFor() != 0) {
            throw new IOException("Failed to compile the SQLCipher JNI using " + command[0]);
        }
    }

    private static void verifyEngine(Path driver) throws Exception {
        try (var loader = new java.net.URLClassLoader(new java.net.URL[] {driver.toUri().toURL()},
                ClassLoader.getPlatformClassLoader())) {
            var jdbc = (java.sql.Driver) loader.loadClass("org.sqlite.JDBC").getConstructor().newInstance();
            try (var connection = jdbc.connect("jdbc:sqlite::memory:", new java.util.Properties());
                    var statement = connection.createStatement(); var rows = statement.executeQuery("PRAGMA cipher_version")) {
                if (!rows.next() || !rows.getString(1).startsWith("4.")) {
                    throw new IOException("The packaged driver requires SQLCipher 4");
                }
            }
        }
    }

    private static void entry(JarOutputStream out, String name) throws IOException {
        JarEntry entry = new JarEntry(name);
        entry.setTimeLocal(java.time.LocalDateTime.of(2000, 1, 1, 0, 0));
        out.putNextEntry(entry);
    }

    private static void writeJar(Path driver, Path nativeLibrary, Path output) throws IOException {
        try (var jar = new JarFile(driver.toFile()); var out = new JarOutputStream(Files.newOutputStream(output))) {
            var manifest = jar.getManifest();
            var headers = manifest.getMainAttributes();
            headers.putValue("Bundle-Name", "SQLite JDBC with system SQLCipher (Linux ARM64)");
            headers.putValue("Bundle-Version", headers.getValue("Bundle-Version") + "_sqlcipher");
            headers.putValue("Require-Capability", headers.getValue("Require-Capability")
                    + ",osgi.native;filter:=\"(&(osgi.native.osname=Linux)(|(osgi.native.processor=aarch64)(osgi.native.processor=arm64)))\"");
            entry(out, JarFile.MANIFEST_NAME);
            manifest.write(out);
            out.closeEntry();
            for (var original : jar.stream().toList()) {
                String name = original.getName();
                if (original.isDirectory() || name.equals(JarFile.MANIFEST_NAME) || name.startsWith("org/sqlite/native/")) {
                    continue;
                }
                entry(out, name);
                try (var stream = jar.getInputStream(original)) {
                    stream.transferTo(out);
                }
                out.closeEntry();
            }
            entry(out, JNI);
            Files.copy(nativeLibrary, out);
            out.closeEntry();
        }
    }
}
