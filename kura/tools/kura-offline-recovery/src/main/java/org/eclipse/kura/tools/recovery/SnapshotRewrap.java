/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.Arrays;

import javax.xml.XMLConstants;
import javax.xml.transform.TransformerFactory;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamResult;

import org.eclipse.kura.core.crypto.CryptoServiceImpl;

/** Reads an authenticated snapshot on stdin and returns ciphertext only. */
public final class SnapshotRewrap {
    private static final int MAX_CIPHERTEXT = (SnapshotTool.LIMIT / 3 + 1) * 4 + 128;

    private SnapshotRewrap() { }

    public static void main(String[] args) {
        try {
            if (args.length != 2 || !args[1].matches("[0-9a-f]{64}")) {
                throw new IllegalArgumentException();
            }
            var crypto = RecoveryCrypto.loadManaged(Path.of("/etc/kura/credentials"), args[0], args[1]);
            System.out.write(rewrap(System.in.readNBytes(MAX_CIPHERTEXT + 1), crypto, args[0]));
            System.out.flush();
            if (System.out.checkError()) {
                throw new IOException();
            }
        } catch (Exception failed) {
            System.err.println("SNAPSHOT_REWRAP_FAILED");
            System.exit(2);
        }
    }

    static byte[] rewrap(byte[] source, CryptoServiceImpl crypto, String activeSha256) throws Exception {
        if (source.length > MAX_CIPHERTEXT || !activeSha256.matches("[0-9a-f]{64}")) {
            throw new IllegalArgumentException();
        }
        byte[] xml;
        try (var plain = crypto.aesDecryptingStream(new ByteArrayInputStream(source))) {
            xml = plain.readNBytes(SnapshotTool.LIMIT + 1);
        }
        try {
            var document = SnapshotTool.parse(xml);
            boolean innerChanged = SnapshotTool.rewrapAuthenticatedSnapshot(document, crypto, activeSha256);
            byte[] prefix = ("KURA2." + activeSha256 + ".").getBytes(StandardCharsets.US_ASCII);
            if (!innerChanged && Arrays.mismatch(source, 0, Math.min(source.length, prefix.length),
                    prefix, 0, prefix.length) == -1) {
                return source;
            }
            var result = new ByteArrayOutputStream();
            try (var encrypted = crypto.aesEncryptingStream(result)) {
                if (innerChanged) {
                    var tf = TransformerFactory.newDefaultInstance();
                    tf.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
                    tf.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");
                    tf.setAttribute(XMLConstants.ACCESS_EXTERNAL_STYLESHEET, "");
                    tf.newTransformer().transform(new DOMSource(document), new StreamResult(encrypted));
                } else {
                    encrypted.write(xml);
                }
            }
            byte[] wrapped = result.toByteArray();
            if (wrapped.length > MAX_CIPHERTEXT || wrapped.length < prefix.length
                    || Arrays.mismatch(wrapped, 0, prefix.length, prefix, 0, prefix.length) != -1) {
                throw new IOException();
            }
            return wrapped;
        } finally {
            Arrays.fill(xml, (byte) 0);
        }
    }
}
