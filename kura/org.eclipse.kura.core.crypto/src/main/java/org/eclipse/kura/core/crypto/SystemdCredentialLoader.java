/*******************************************************************************
 * Copyright (c) 2025 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 ******************************************************************************/
package org.eclipse.kura.core.crypto;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.Optional;

public class SystemdCredentialLoader {

    private static final String CREDENTIALS_DIRECTORY_ENV = "CREDENTIALS_DIRECTORY";
    private final File credentialRoot;

    public SystemdCredentialLoader(final File credentialRoot) {
        this.credentialRoot = credentialRoot;
    }

    public static Optional<SystemdCredentialLoader> fromEnv() {
        return Optional.ofNullable(System.getenv(CREDENTIALS_DIRECTORY_ENV)).map(File::new).filter(File::isDirectory)
                .map(SystemdCredentialLoader::new);
    }

    public Optional<byte[]> loadCredential(final String name) throws IOException {

        final File credentialFile = new File(this.credentialRoot, name);

        if (!credentialFile.exists()) {
            return Optional.empty();
        }

        try (final InputStream in = new FileInputStream(credentialFile);
                final ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            final byte[] buf = new byte[1024];

            for (int rd = in.read(buf); rd != -1; rd = in.read(buf)) {
                out.write(buf, 0, rd);
            }

            return Optional.of(out.toByteArray());
        }
    }

    /** Fixed credential names only; fail closed for present unsafe or oversized files. */
    Optional<byte[]> loadCredential(final String name, final int maximumBytes) throws IOException {
        if (!name.matches("[A-Za-z0-9_.-]{1,128}") || maximumBytes <= 0) {
            throw new IOException("Invalid bounded credential request");
        }
        Path path = this.credentialRoot.toPath().resolve(name);
        if (Files.notExists(path, LinkOption.NOFOLLOW_LINKS)) { return Optional.empty(); }
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) {
            throw new IOException("Credential must be a regular file");
        }
        try (InputStream in = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
            byte[] data = in.readNBytes(maximumBytes + 1);
            if (data.length > maximumBytes) { throw new IOException("Credential size exceeds bound"); }
            return Optional.of(data);
        }
    }

}
