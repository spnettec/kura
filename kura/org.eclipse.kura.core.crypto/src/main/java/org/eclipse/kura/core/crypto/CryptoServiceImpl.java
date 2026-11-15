/*******************************************************************************
 * Copyright (c) 2011, 2025 Eurotech and/or its affiliates and others
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

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.UnsupportedEncodingException;
import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CharsetDecoder;
import java.nio.charset.CharsetEncoder;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.security.InvalidAlgorithmParameterException;
import java.security.InvalidKeyException;
import java.security.Key;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Base64;
import java.util.Optional;
import java.util.Properties;

import javax.crypto.BadPaddingException;
import javax.crypto.Cipher;
import javax.crypto.CipherOutputStream;
import javax.crypto.IllegalBlockSizeException;
import javax.crypto.NoSuchPaddingException;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.system.SystemService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class CryptoServiceImpl implements CryptoService {

    private static final Logger logger = LoggerFactory.getLogger(CryptoServiceImpl.class);

    private static final String PARAMETER_EXCEPTION_CAUSE = "parameter";
    private static final String DECRYPT_EXCEPTION_CAUSE = "decrypt";
    private static final String VALUE_EXCEPTION_CAUSE = "value";

    private static final String ALGORITHM = "AES";
    private static final String CIPHER = "AES/GCM/NoPadding";
    private static final int AUTH_TAG_LENGTH_BIT = 128;
    private static final int IV_SIZE = 12;
    private static final String ENCRYPTED_STRING_SEPARATOR = "-";
    private static final byte[] DEFAULT_SECRET_KEY = "rv;ipse329183!@#".getBytes(StandardCharsets.UTF_8);
    private static final String SECRET_KEY_CREDENTIAL_ID = "kura_encryption_key";
    private static final String SECRET_KEY_SYSTEM_PROPERTY_NAME = "org.eclipse.kura.core.crypto.secretKey";
    private static final String SECRET_KEY_ENV_VAR_NAME = "KURA_CRYPTO_SECRET_KEY";

    private String keystorePasswordPath;

    private final SecureRandom random = new SecureRandom();
    private SystemService systemService;
    private Optional<byte[]> secretKey;
    private EncryptionKeyRing keyRing;
    private static final String KEYED_HEADER = "KURA2.";
    private static final int MAX_HEADER_BYTES = 87;

    /**
     * Explicit, non-OSGi AES context for the short-lived snapshot recovery tool.
     * No environment/credential lookup and no fallback from an invalid supplied key.
     * The default deployment key is available only through an explicit choice.
     */
    public static CryptoServiceImpl forSnapshotRecovery(byte[] key, boolean useDefaultKey) {
        if (useDefaultKey == (key != null)
                || (!useDefaultKey && key.length != 16 && key.length != 24 && key.length != 32)) {
            throw new IllegalArgumentException("Explicit valid snapshot key or default-key choice required");
        }
        CryptoServiceImpl result = new CryptoServiceImpl();
        result.secretKey = Optional.of((useDefaultKey ? DEFAULT_SECRET_KEY : key).clone());
        return result;
    }

    /** Explicit private recovery material; no default key, environment or trial decryption. */
    public static CryptoServiceImpl forKeyRingRecovery(byte[] credential) {
        return forKeyRingRecovery(credential, null);
    }

    /** Pair the ring with a separately loaded active credential; never select a different writer key. */
    public static CryptoServiceImpl forKeyRingRecovery(byte[] credential, byte[] expectedActiveKey) {
        CryptoServiceImpl result = new CryptoServiceImpl();
        result.keyRing = EncryptionKeyRing.parse(credential);
        if (expectedActiveKey != null && !MessageDigest.isEqual(expectedActiveKey, result.keyRing.activeBytes())) {
            throw new IllegalArgumentException("Active recovery credential does not match key ring");
        }
        result.secretKey = Optional.of(result.keyRing.activeBytes());
        return result;
    }

    public void setSystemService(SystemService systemService) {
        this.systemService = systemService;
    }

    public void unsetSystemService(SystemService systemService) {
        this.systemService = null;
    }

    protected void activate() {

        boolean loadedRing = SystemdCredentialLoader.fromEnv().map(this::loadKeyRing).orElse(false);
        if (!loadedRing) {
            this.keyRing = null;
            this.secretKey = loadCustomEncryptionKey().filter(CryptoServiceImpl::isEncryptionKeyValid);
        }

        this.keystorePasswordPath = this.systemService.getKuraDataDirectory() + File.separator + "store.save";
    }

    // Called only for fixed systemd credential IDs; publish fields after complete validation.
    boolean loadKeyRing(SystemdCredentialLoader loader) {
        try {
            Optional<byte[]> data = loader.loadCredential(EncryptionKeyRing.CREDENTIAL, EncryptionKeyRing.MAX_BYTES);
            if (!data.isPresent()) { return false; }
            EncryptionKeyRing ring = EncryptionKeyRing.parse(data.get());
            byte[] active = loader.loadCredential(SECRET_KEY_CREDENTIAL_ID, 32)
                    .orElseThrow(() -> new IllegalArgumentException("Active encryption credential required"));
            if (!MessageDigest.isEqual(active, ring.activeBytes())) {
                throw new IllegalArgumentException("Encryption credentials do not match");
            }
            this.secretKey = Optional.of(active.clone());
            this.keyRing = ring;
            return true;
        } catch (IOException | IllegalArgumentException e) {
            throw new IllegalStateException("Cannot load encryption key ring credentials");
        }
    }

    private String encryptionHeader(byte[] iv) {
        return (this.keyRing == null ? "" : KEYED_HEADER + this.keyRing.activeId() + ".") + base64Encode(iv);
    }

    private void authenticateHeader(Cipher cipher, String header) {
        if (header.startsWith(KEYED_HEADER)) {
            cipher.updateAAD(header.getBytes(StandardCharsets.US_ASCII));
        }
    }

    private Cipher decryptionCipher(String header) throws KuraException {
        try {
            String encodedIv = header;
            Key key;
            if (header.startsWith(KEYED_HEADER)) {
                String[] parts = header.split("\\.", -1);
                if (parts.length != 3 || !parts[1].matches("[0-9a-f]{64}")) {
                    throw new IllegalArgumentException();
                }
                encodedIv = parts[2];
                if (this.keyRing != null) { key = this.keyRing.key(parts[1]); }
                else {
                    key = generateKey();
                    if (!EncryptionKeyRing.id(key.getEncoded()).equals(parts[1])) {
                        throw new IllegalArgumentException();
                    }
                }
            } else { key = this.keyRing == null ? generateKey() : this.keyRing.legacyKey(); }
            byte[] iv = base64Decode(encodedIv);
            if (encodedIv.length() != 16 || iv.length != IV_SIZE) { throw new IllegalArgumentException(); }
            Cipher cipher = Cipher.getInstance(CIPHER);
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(AUTH_TAG_LENGTH_BIT, iv));
            authenticateHeader(cipher, header);
            return cipher;
        } catch (NoSuchAlgorithmException | NoSuchPaddingException e) {
            throw new KuraException(KuraErrorCode.OPERATION_NOT_SUPPORTED, DECRYPT_EXCEPTION_CAUSE);
        } catch (InvalidKeyException | InvalidAlgorithmParameterException | IllegalArgumentException e) {
            throw new KuraException(KuraErrorCode.DECODER_ERROR, VALUE_EXCEPTION_CAUSE);
        }
    }

    // A padded Base64 decoder can otherwise stop before trailing encoded bytes.
    private static final class CompleteDecodedStream extends InputStream {
        private final InputStream encoded;
        private final InputStream decoded;
        CompleteDecodedStream(InputStream encoded) {
            this.encoded = encoded;
            this.decoded = Base64.getDecoder().wrap(encoded);
        }
        private int complete(int count) throws IOException {
            if (count == -1 && this.encoded.read() != -1) {
                throw new IOException("Trailing ciphertext bytes");
            }
            return count;
        }
        @Override public int read() throws IOException { return complete(this.decoded.read()); }
        @Override public int read(byte[] bytes, int offset, int length) throws IOException {
            return complete(this.decoded.read(bytes, offset, length));
        }
        @Override public void close() throws IOException { this.decoded.close(); }
    }

    private Optional<byte[]> loadCustomEncryptionKey() {
        try {
            final Optional<SystemdCredentialLoader> loader = SystemdCredentialLoader.fromEnv();

            if (loader.isPresent()) {

                final Optional<byte[]> keyFromSystemd = loader.get().loadCredential(SECRET_KEY_CREDENTIAL_ID);

                if (keyFromSystemd.isPresent()) {
                    logger.debug("using key from systemd");
                    return Optional.of(keyFromSystemd.get());
                }
            }

        } catch (final Exception e) {
            logger.warn("Unexpected exception loading encryption provided by systemd", e);
        }

        return Optional.ofNullable(System.getProperty(SECRET_KEY_SYSTEM_PROPERTY_NAME)).filter(k -> !k.isEmpty())
                .map(k -> {
                    logger.debug("using key from system properties");
                    return k.getBytes(StandardCharsets.UTF_8);
                })
                .or(() -> Optional.ofNullable(System.getenv(SECRET_KEY_ENV_VAR_NAME)).filter(k -> !k.isEmpty())
                        .map(k -> {
                            logger.debug("using key from environment variable {}", SECRET_KEY_ENV_VAR_NAME);
                            return k.getBytes(StandardCharsets.UTF_8);
                        }));
    }

    private static boolean isEncryptionKeyValid(final byte[] key) {

        return (key.length == 16 || key.length == 24 || key.length == 32) && !Arrays.equals(key, DEFAULT_SECRET_KEY);
    }

    @Override
    public boolean hasCustomEncryptionKey() {
        return this.secretKey != null && this.secretKey.filter(CryptoServiceImpl::isEncryptionKeyValid).isPresent();
    }

    @Override
    public char[] encryptAes(char[] value) throws KuraException {

        try {
            Key key = generateKey();
            Cipher c = Cipher.getInstance(CIPHER);
            byte[] iv = new byte[IV_SIZE];
            this.random.nextBytes(iv);
            c.init(Cipher.ENCRYPT_MODE, key, new GCMParameterSpec(AUTH_TAG_LENGTH_BIT, iv));
            String header = encryptionHeader(iv);
            authenticateHeader(c, header);
            byte[] encryptedBytes = c.doFinal(charArrayToByteArray(value));
            String encryptedMessage = base64Encode(encryptedBytes);

            return (header + ENCRYPTED_STRING_SEPARATOR + encryptedMessage).toCharArray();
        } catch (NoSuchAlgorithmException | NoSuchPaddingException e) {
            throw new KuraException(KuraErrorCode.OPERATION_NOT_SUPPORTED, "encrypt");
        } catch (InvalidKeyException | IllegalBlockSizeException | BadPaddingException | CharacterCodingException e) {
            throw new KuraException(KuraErrorCode.ENCODE_ERROR, VALUE_EXCEPTION_CAUSE);
        } catch (InvalidAlgorithmParameterException e) {
            throw new KuraException(KuraErrorCode.ENCODE_ERROR, PARAMETER_EXCEPTION_CAUSE);
        }

    }

    @Override
    public OutputStream aesEncryptingStream(OutputStream stream) throws KuraException {
        try {
            Key key = generateKey();
            Cipher c = Cipher.getInstance(CIPHER);

            byte[] iv = new byte[IV_SIZE];
            this.random.nextBytes(iv);
            c.init(Cipher.ENCRYPT_MODE, key, new GCMParameterSpec(AUTH_TAG_LENGTH_BIT, iv));

            String header = encryptionHeader(iv);
            authenticateHeader(c, header);
            stream.write(header.getBytes(StandardCharsets.US_ASCII));
            stream.write(ENCRYPTED_STRING_SEPARATOR.getBytes(StandardCharsets.UTF_8));

            final OutputStream base64Encoder = Base64.getEncoder().wrap(stream);

            return new CipherOutputStream(base64Encoder, c);

        } catch (NoSuchAlgorithmException | NoSuchPaddingException e) {
            throw new KuraException(KuraErrorCode.OPERATION_NOT_SUPPORTED, "encrypt");
        } catch (IOException e) {
            throw new KuraException(KuraErrorCode.IO_ERROR, e);
        } catch (InvalidAlgorithmParameterException e) {
            throw new KuraException(KuraErrorCode.ENCODE_ERROR, PARAMETER_EXCEPTION_CAUSE);
        } catch (InvalidKeyException e) {
            throw new KuraException(KuraErrorCode.ENCODE_ERROR, VALUE_EXCEPTION_CAUSE);
        }
    }

    private byte[] charArrayToByteArray(char[] value) throws CharacterCodingException {

        ByteBuffer byteBuffer;
        try {
            byteBuffer = getUtf8Encoder().encode(CharBuffer.wrap(value));
        } catch (CharacterCodingException e) {
            // fallback for backward compatibility
            byteBuffer = ByteBuffer.wrap(new String(value).getBytes());
        }
        byte[] encodedBytes = new byte[byteBuffer.limit()];
        byteBuffer.get(encodedBytes);

        return encodedBytes;
    }

    private char[] byteArrayToCharArray(byte[] value) throws CharacterCodingException {
        CharBuffer charBuffer;
        try {
            charBuffer = getUtf8Decoder().decode(ByteBuffer.wrap(value));
        } catch (CharacterCodingException e) {
            // fallback for backward compatibility
            charBuffer = CharBuffer.wrap(new String(value).toCharArray());
        }
        char[] decodedChar = new char[charBuffer.limit()];
        charBuffer.get(decodedChar);

        return decodedChar;
    }

    private CharsetEncoder getUtf8Encoder() {
        CharsetEncoder encoder = StandardCharsets.UTF_8.newEncoder();
        encoder.onMalformedInput(CodingErrorAction.REPORT);
        encoder.onUnmappableCharacter(CodingErrorAction.REPORT);

        return encoder;
    }

    private CharsetDecoder getUtf8Decoder() {
        CharsetDecoder decoder = StandardCharsets.UTF_8.newDecoder();
        decoder.onMalformedInput(CodingErrorAction.REPORT);
        decoder.onUnmappableCharacter(CodingErrorAction.REPORT);

        return decoder;
    }
    
    @Override
    public void encryptAes(InputStream value, OutputStream out) throws KuraException {
        // Authentication finalization is part of success; never swallow close failures.
        try (OutputStream encrypted = aesEncryptingStream(out)) {
            value.transferTo(encrypted);
        } catch (IOException e) {
            throw new KuraException(KuraErrorCode.ENCODE_ERROR, VALUE_EXCEPTION_CAUSE);
        }
    }

    private byte[] base64Decode(String internalStringValue) {
        return Base64.getDecoder().decode(internalStringValue);
    }

    private String base64Encode(byte[] encryptedBytes) {
        return Base64.getEncoder().encodeToString(encryptedBytes);
    }

    @Override
    public void decryptAes(InputStream value, OutputStream out) throws KuraException {
        try (InputStream decrypted = aesDecryptingStream(value)) {
            decrypted.transferTo(out);
            out.flush();
        } catch (IOException e) {
            throw new KuraException(KuraErrorCode.DECODER_ERROR, VALUE_EXCEPTION_CAUSE);
        }
    }

    @Override
    public char[] decryptAes(char[] encryptedValue) throws KuraException {
        if (encryptedValue.length == 0) { return new char[0]; }
        try {
            String[] parts = new String(encryptedValue).split(ENCRYPTED_STRING_SEPARATOR, -1);
            if (parts.length != 2 || parts[0].length() > MAX_HEADER_BYTES) {
                throw new KuraException(KuraErrorCode.DECODER_ERROR, VALUE_EXCEPTION_CAUSE);
            }
            byte[] encrypted = base64Decode(parts[1]);
            if (encrypted.length < AUTH_TAG_LENGTH_BIT / 8) {
                throw new KuraException(KuraErrorCode.DECODER_ERROR, VALUE_EXCEPTION_CAUSE);
            }
            return byteArrayToCharArray(decryptionCipher(parts[0]).doFinal(encrypted));
        } catch (BadPaddingException | IllegalBlockSizeException | CharacterCodingException | IllegalArgumentException e) {
            throw new KuraException(KuraErrorCode.DECODER_ERROR, VALUE_EXCEPTION_CAUSE);
        }
    }

    @Override
    public InputStream aesDecryptingStream(InputStream encryptedStream) throws KuraException {
        try {
            BufferedInputStream buffered = new BufferedInputStream(encryptedStream);
            ByteArrayOutputStream header = new ByteArrayOutputStream();
            int value;
            while ((value = buffered.read()) != '-') {
                if (value < 0 || value > 127 || header.size() >= MAX_HEADER_BYTES) {
                    throw new KuraException(KuraErrorCode.DECODER_ERROR, VALUE_EXCEPTION_CAUSE);
                }
                header.write(value);
            }
            Cipher cipher = decryptionCipher(header.toString(StandardCharsets.US_ASCII));
            buffered.mark(1);
            if (buffered.read() == -1) { throw new KuraException(KuraErrorCode.DECODER_ERROR, VALUE_EXCEPTION_CAUSE); }
            buffered.reset();
            return new AuthenticatedDecryptingStream(new CompleteDecodedStream(buffered), cipher,
                    decryptionCipher(header.toString(StandardCharsets.US_ASCII)));
        } catch (IOException | IllegalArgumentException e) {
            throw new KuraException(KuraErrorCode.DECODER_ERROR, VALUE_EXCEPTION_CAUSE);
        }
    }

    @Override
    public String encodeBase64(String stringValue) throws UnsupportedEncodingException {
        if (stringValue == null) {
            return null;
        }

        return base64Encode(stringValue.getBytes(StandardCharsets.UTF_8));
    }

    @Override
    public String decodeBase64(String encodedValue) throws NoSuchAlgorithmException, UnsupportedEncodingException {
        if (encodedValue == null) {
            return null;
        }

        return new String(base64Decode(encodedValue), StandardCharsets.UTF_8);
    }

    @Override
    public char[] getKeyStorePassword(String keyStorePath) {
        Properties props = new Properties();
        char[] password = null;

        File f = new File(this.keystorePasswordPath);
        if (!f.exists()) {
            return "changeit".toCharArray();
        }

        try (FileInputStream fis = new FileInputStream(this.keystorePasswordPath);) {
            props.load(fis);
            Object value = props.get(keyStorePath);
            if (value != null) {
                String encryptedPassword = (String) value;
                password = decryptAes(encryptedPassword.toCharArray());
            }
        } catch (FileNotFoundException e) {
            logger.warn("File not found exception while getting keystore password - ", e);
        } catch (IOException e) {
            logger.warn("IOException while getting keystore password - ", e);
        } catch (KuraException e) {
            logger.warn("KuraException while getting keystore password - ", e);
        }

        return password;
    }

    @Override
    public void setKeyStorePassword(String keyStorePath, char[] password) throws KuraException {
        Properties props = new Properties();
        try (FileInputStream fis = new FileInputStream(this.keystorePasswordPath)) {
            props.load(fis);
        } catch (IOException e) {
            // Not loading from an existing file
        }
        char[] encryptedPassword = encryptAes(password);
        props.put(keyStorePath, new String(encryptedPassword));

        try (FileOutputStream fos = new FileOutputStream(this.keystorePasswordPath);) {
            props.store(fos, "Do not edit this file. It's automatically generated by Kura");
            fos.flush();
        } catch (IOException e) {
            throw new KuraException(KuraErrorCode.INTERNAL_ERROR, e);
        }
    }

    @Override
    public boolean isFrameworkSecure() {
        return false;
    }

    private Key generateKey() {

        if (!this.secretKey.isPresent()) {
            boolean encryptSnapshots = true;
            try {
                if (this.systemService != null && this.systemService.getProperties() != null) {
                    encryptSnapshots = Boolean.parseBoolean(
                            this.systemService.getProperties().getProperty("kura.snapshots.encrypt", "true"));
                }
            } catch (Exception e) {
                // ignore — fall back to default (warn)
            }
            if (encryptSnapshots) {
                logger.warn("A user defined encryption key has not been provided or is invalid."
                        + " The default well known key is in use."
                        + " Please reinstall Kura and provide a valid encryption key of length 16, 24, or 32 bytes (characters)"
                        + " as explained in the Eclipse Kura documentation.");
            } else {
                logger.info("A user defined encryption key has not been provided."
                        + " Using default key for password encryption (kura.snapshots.encrypt is disabled).");
            }
            return new SecretKeySpec(DEFAULT_SECRET_KEY, ALGORITHM);
        }

        return new SecretKeySpec(this.secretKey.get(), ALGORITHM);
    }

    @Override
    public String hash(String s, String algorithm) throws NoSuchAlgorithmException, UnsupportedEncodingException {
        MessageDigest messageDigest = MessageDigest.getInstance(algorithm);
        messageDigest.reset();
        messageDigest.update(s.getBytes(StandardCharsets.UTF_8));

        byte[] encodedBytes = messageDigest.digest();
        return base64Encode(encodedBytes);
    }
}
