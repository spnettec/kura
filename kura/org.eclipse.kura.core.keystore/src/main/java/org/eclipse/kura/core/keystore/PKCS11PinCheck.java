/*******************************************************************************
 * Copyright (c) 2026 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.core.keystore;

import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.AuthProvider;
import java.security.Security;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.jar.JarEntry;
import java.util.jar.JarOutputStream;

import javax.security.auth.callback.PasswordCallback;
import javax.security.auth.callback.UnsupportedCallbackException;
import javax.security.auth.login.FailedLoginException;
import javax.security.auth.login.LoginException;

final class PKCS11PinCheck {

    private static final int VERIFIED = 0;
    private static final int REJECTED = 1;
    private static final int PRE_LOGIN_FAILURE = 2;
    private static final int UNCERTAIN = 3;

    enum Result {
        VERIFIED, REJECTED, UNAVAILABLE, UNCERTAIN
    }

    private PKCS11PinCheck() {
    }

    static Result verify(String config, char[] pin) {
        final Path directory;
        try {
            directory = Files.createTempDirectory("kura-pkcs11-check-");
        } catch (IOException e) {
            return Result.UNAVAILABLE;
        }

        final Path archive = directory.resolve("pin-check.jar");
        final Path configFile = directory.resolve("provider.cfg");
        try {
            writeWorker(archive);
            Files.writeString(configFile, config);
            final Path java = Path.of(System.getProperty("java.home"), "bin", "java");
            final var worker = new ProcessBuilder(java.toString(), "-cp", archive.toString(),
                    PKCS11PinCheck.class.getName(), configFile.toString())
                    .redirectOutput(ProcessBuilder.Redirect.DISCARD)
                    .redirectError(ProcessBuilder.Redirect.DISCARD);
            worker.environment().remove("JDK_JAVA_OPTIONS");
            worker.environment().remove("JAVA_TOOL_OPTIONS");
            worker.environment().remove("_JAVA_OPTIONS");
            return waitForCheck(worker.start(), pin);
        } catch (IOException e) {
            return Result.UNAVAILABLE;
        } finally {
            delete(archive);
            delete(configFile);
            delete(directory);
        }
    }

    private static void writeWorker(Path archive) throws IOException {
        try (var jar = new JarOutputStream(Files.newOutputStream(archive))) {
            for (Class<?> type : List.of(PKCS11PinCheck.class, Result.class)) {
                String entryName = type.getName().replace('.', '/') + ".class";
                try (var code = type.getResourceAsStream("/" + entryName)) {
                    if (code == null) {
                        throw new IOException("PKCS11 verification worker class unavailable");
                    }
                    jar.putNextEntry(new JarEntry(entryName));
                    code.transferTo(jar);
                    jar.closeEntry();
                }
            }
        }
    }

    private static Result waitForCheck(Process worker, char[] pin) {
        final char[] input = pin.clone();
        final var writer = new FutureTask<Void>(() -> {
            try (var data = new DataOutputStream(worker.getOutputStream())) {
                data.writeInt(input.length);
                for (char value : input) {
                    data.writeChar(value);
                }
            } finally {
                Arrays.fill(input, '\0');
            }
            return null;
        });
        Thread.ofVirtual().start(writer);
        try {
            if (!worker.waitFor(30, TimeUnit.SECONDS)) {
                return Result.UNCERTAIN;
            }
            writer.get(1, TimeUnit.SECONDS);
            return switch (worker.exitValue()) {
            case VERIFIED -> Result.VERIFIED;
            case REJECTED -> Result.REJECTED;
            case PRE_LOGIN_FAILURE -> Result.UNAVAILABLE;
            default -> Result.UNCERTAIN;
            };
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return Result.UNCERTAIN;
        } catch (ExecutionException | TimeoutException e) {
            return Result.UNCERTAIN;
        } finally {
            if (worker.isAlive()) {
                worker.destroyForcibly();
            }
        }
    }

    private static void delete(Path path) {
        try {
            Files.deleteIfExists(path);
        } catch (IOException e) {
            path.toFile().deleteOnExit();
        }
    }

    public static void main(String[] args) {
        System.exit(readAndCheck(args[0]));
    }

    private static int readAndCheck(String config) {
        try (var input = new DataInputStream(System.in)) {
            final char[] pin = new char[input.readInt()];
            try {
                for (int i = 0; i < pin.length; i++) {
                    pin[i] = input.readChar();
                }
                return check(config, pin);
            } finally {
                Arrays.fill(pin, '\0');
            }
        } catch (IOException | IllegalArgumentException e) {
            return PRE_LOGIN_FAILURE;
        }
    }

    private static int check(String config, char[] pin) {
        final AuthProvider provider;
        try {
            provider = (AuthProvider) Security.getProvider("SunPKCS11").configure(config);
        } catch (RuntimeException e) {
            return PRE_LOGIN_FAILURE;
        }

        final var pinRequested = new AtomicBoolean();
        try {
            provider.login(null, callbacks -> {
                for (var callback : callbacks) {
                    if (!(callback instanceof PasswordCallback password)) {
                        throw new UnsupportedCallbackException(callback);
                    }
                    password.setPassword(pin);
                    pinRequested.set(true);
                }
            });
            return pinRequested.get() ? VERIFIED : UNCERTAIN;
        } catch (FailedLoginException e) {
            return REJECTED;
        } catch (LoginException | RuntimeException e) {
            return UNCERTAIN;
        }
    }
}
