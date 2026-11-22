/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import java.util.Collection;
import java.util.HashMap;
import java.util.Map;

import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.core.configuration.util.CollectionsUtil;
import org.eclipse.kura.crypto.CryptoService;

/** Resolves legacy snapshot passwords one element at a time before using them as logical values. */
public final class LegacySnapshotPasswords {
    private LegacySnapshotPasswords() { }

    /** Whether the XML adapter has already established that this is a logical value. */
    public static boolean isKnownLogical(Password password) {
        return password instanceof XmlConfigPropertiesAdapter.LegacyLogicalPassword;
    }

    static Map<String, Object> logical(Map<String, Object> source, CryptoService crypto) {
        Map<String, Object> result = source;
        for (var entry : source.entrySet()) {
            Object value = entry.getValue();
            Object decoded = logicalValue(value, crypto);
            if (decoded != value) {
                if (result == source) {
                    result = new HashMap<>(source);
                }
                result.put(entry.getKey(), decoded);
            }
        }
        return result;
    }

    private static Object logicalValue(Object value, CryptoService crypto) {
        if (value instanceof Password password) {
            return logicalPassword(password, crypto);
        }
        if (value instanceof Password[] array) {
            Password[] decoded = new Password[array.length];
            for (int i = 0; i < array.length; i++) {
                decoded[i] = array[i] == null ? null : logicalPassword(array[i], crypto);
            }
            return decoded;
        }
        if (CollectionsUtil.isPasswordCollection(value)) {
            Collection<?> original = (Collection<?>) value;
            Collection<Password> decoded = CollectionsUtil.newCollectionLike(original);
            for (Object element : original) {
                decoded.add(logicalPassword((Password) element, crypto));
            }
            return decoded;
        }
        return value;
    }

    private static Password logicalPassword(Password password, CryptoService crypto) {
        char[] value = password.getPassword();
        if (!isKnownLogical(password) && crypto != null && value != null && value.length != 0) {
            try {
                char[] authenticated = crypto.decryptAes(value);
                if (authenticated != null) {
                    return new Password(authenticated);
                }
            } catch (KuraException historicalLogicalValue) {
                // Legacy Base64 literals are still supported. A ciphertext-looking string alone proves nothing.
            }
        }
        return new Password(value == null ? null : value.clone());
    }
}
