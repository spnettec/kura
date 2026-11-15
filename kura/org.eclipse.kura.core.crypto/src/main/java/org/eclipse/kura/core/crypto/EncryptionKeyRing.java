/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.crypto;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.Key;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;

import javax.crypto.spec.SecretKeySpec;

/** Explicit retained generations. Untagged data has one designated legacy key. */
final class EncryptionKeyRing {
    static final int MAX_BYTES = 512;
    static final String CREDENTIAL = "kura_encryption_keyring";
    private static final byte[] MAGIC = "YOFC-KURA-KEYRING-v1\n".getBytes(StandardCharsets.US_ASCII);
    private final Map<String, byte[]> keys;
    private final String activeId;
    private final String legacyId;

    private EncryptionKeyRing(Map<String, byte[]> keys, String activeId, String legacyId) {
        this.keys = keys;
        this.activeId = activeId;
        this.legacyId = legacyId;
    }

    static EncryptionKeyRing parse(byte[] data) {
        require(data != null && data.length <= MAX_BYTES && data.length >= MAGIC.length + 3);
        ByteBuffer input = ByteBuffer.wrap(data);
        byte[] magic = new byte[MAGIC.length];
        input.get(magic);
        require(Arrays.equals(magic, MAGIC));
        int count = Byte.toUnsignedInt(input.get());
        int active = Byte.toUnsignedInt(input.get());
        int legacy = Byte.toUnsignedInt(input.get());
        require(count >= 2 && count <= 8 && active < count && legacy < count && active != legacy);
        Map<String, byte[]> keys = new LinkedHashMap<>();
        String activeId = null;
        String legacyId = null;
        for (int n = 0; n < count; n++) {
            require(input.hasRemaining());
            int length = Byte.toUnsignedInt(input.get());
            require((length == 16 || length == 24 || length == 32) && input.remaining() >= length);
            require(n != active || length == 32);
            byte[] key = new byte[length];
            input.get(key);
            String id = id(key);
            require(keys.putIfAbsent(id, key) == null);
            if (n == active) { activeId = id; }
            if (n == legacy) { legacyId = id; }
        }
        require(!input.hasRemaining());
        return new EncryptionKeyRing(keys, activeId, legacyId);
    }

    private static void require(boolean valid) {
        if (!valid) { throw new IllegalArgumentException("Invalid encryption key ring credential"); }
    }

    static String id(byte[] key) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(key)); }
        catch (NoSuchAlgorithmException e) { throw new IllegalStateException("SHA-256 unavailable"); }
    }

    String activeId() { return this.activeId; }
    byte[] activeBytes() { return this.keys.get(this.activeId).clone(); }
    Key legacyKey() { return key(this.legacyId); }
    Key key(String id) {
        byte[] value = this.keys.get(id);
        require(value != null);
        return new SecretKeySpec(value, "AES");
    }
}
