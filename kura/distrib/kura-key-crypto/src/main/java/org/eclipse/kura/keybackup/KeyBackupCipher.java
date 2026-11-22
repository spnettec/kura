/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.keybackup;

import java.io.DataInputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.util.Arrays;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

import org.bouncycastle.crypto.generators.Argon2BytesGenerator;
import org.bouncycastle.crypto.params.Argon2Parameters;

/** One request per process. Passwords and plaintext travel only through private pipes. */
public final class KeyBackupCipher {
    private static final int MAX_DATA = 32768;
    private static final int MAX_PASSWORD = 1024;
    private static final int SALT_LENGTH = 16;
    private static final int NONCE_LENGTH = 12;
    private static final byte[] MAGIC = "YOFC-KURA-GATEWAY-MASTER-KEY\0\1".getBytes(StandardCharsets.US_ASCII);

    private KeyBackupCipher() {
    }

    public static void main(String[] args) {
        byte[] password = null;
        byte[] data = null;
        byte[] result = null;
        int exitCode = 0;
        try {
            if (args.length != 0) {
                throw new IOException("Arguments are not accepted");
            }
            DataInputStream input = new DataInputStream(System.in);
            if (input.readInt() != 0x4b4b4231) { // KKB1: private worker framing, not the backup format.
                throw new IOException("Invalid worker frame");
            }
            int mode = input.readUnsignedByte();
            password = readBounded(input, MAX_PASSWORD);
            data = readBounded(input, MAX_DATA);
            if (input.read() != -1 || password.length < 12 || (mode != 1 && mode != 2)) {
                throw new IOException("Invalid worker request");
            }
            result = crypt(mode == 1, password, data);
            System.out.write(result);
            System.out.flush();
        } catch (IOException | GeneralSecurityException | IllegalArgumentException e) {
            // No exception text, stack trace, password, plaintext or uploaded bytes in logs.
            System.err.println("Gateway key backup cipher refused the request");
            exitCode = 2;
        } finally {
            wipe(password);
            wipe(data);
            wipe(result);
        }
        if (exitCode != 0) {
            System.exit(exitCode);
        }
    }

    private static byte[] readBounded(DataInputStream input, int limit) throws IOException {
        int length = input.readInt();
        if (length < 1 || length > limit) {
            throw new IOException("Invalid worker field length");
        }
        byte[] value = input.readNBytes(length);
        if (value.length != length) {
            throw new IOException("Incomplete worker field");
        }
        return value;
    }

    private static byte[] crypt(boolean encrypt, byte[] password, byte[] data)
            throws GeneralSecurityException, IOException {
        byte[] salt = new byte[SALT_LENGTH];
        byte[] nonce = new byte[NONCE_LENGTH];
        byte[] derived = new byte[32];
        byte[] header = null;
        Argon2Parameters parameters = null;
        try {
            int headerLength = MAGIC.length + SALT_LENGTH + NONCE_LENGTH;
            if (encrypt) {
                SecureRandom random = new SecureRandom();
                random.nextBytes(salt);
                random.nextBytes(nonce);
                header = ByteBuffer.allocate(headerLength).put(MAGIC).put(salt).put(nonce).array();
            } else {
                if (data.length < headerLength + 16
                        || !Arrays.equals(MAGIC, Arrays.copyOf(data, MAGIC.length))) {
                    throw new IOException("Unsupported gateway backup format");
                }
                header = Arrays.copyOf(data, headerLength);
                System.arraycopy(header, MAGIC.length, salt, 0, SALT_LENGTH);
                System.arraycopy(header, MAGIC.length + SALT_LENGTH, nonce, 0, NONCE_LENGTH);
            }
            Argon2Parameters.Builder builder = new Argon2Parameters.Builder(Argon2Parameters.ARGON2_id)
                    .withVersion(Argon2Parameters.ARGON2_VERSION_13).withMemoryAsKB(19 * 1024)
                    .withIterations(2).withParallelism(1).withSalt(salt);
            try {
                parameters = builder.build();
            } finally {
                builder.clear();
            }
            Argon2BytesGenerator generator = new Argon2BytesGenerator();
            generator.init(parameters);
            generator.generateBytes(password, derived);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(encrypt ? Cipher.ENCRYPT_MODE : Cipher.DECRYPT_MODE,
                    new SecretKeySpec(derived, "AES"), new GCMParameterSpec(128, nonce));
            cipher.updateAAD(header);
            if (encrypt) {
                byte[] encrypted = cipher.doFinal(data);
                return ByteBuffer.allocate(header.length + encrypted.length).put(header).put(encrypted).array();
            }
            return cipher.doFinal(data, header.length, data.length - header.length);
        } finally {
            wipe(derived);
            wipe(salt);
            wipe(nonce);
            wipe(header);
            if (parameters != null) {
                parameters.clear();
            }
        }
    }

    private static void wipe(byte[] value) {
        if (value != null) {
            Arrays.fill(value, (byte) 0);
        }
    }
}
