/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import java.util.*;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.core.configuration.util.CollectionsUtil;
import org.osgi.service.cm.ConfigurationAdmin;

/** Guarded normal startup must preserve the authenticated CM password representation. */
final class StartupPasswordConvergence {
    private StartupPasswordConvergence() { }
    static Map<String,Map<String,Object>> capture(ConfigurationAdmin admin) throws KuraException {
        try {
            Map<String,Map<String,Object>> result = new HashMap<>();
            for (var value : ConfigurationRestore.capture(admin)) {
                if (result.put(value.getPid(), value.getConfigurationProperties()) != null) throw invalid();
            }
            return result;
        } catch (Exception failure) { throw invalid(); }
    }
    static Map<String,Object> preserve(Map<String,Object> logical, Map<String,Object> current, CryptoService crypto)
            throws KuraException {
        if (current == null || !Objects.equals(logical.get(ConfigurationAdmin.SERVICE_FACTORYPID),
                current.get(ConfigurationAdmin.SERVICE_FACTORYPID))) throw invalid();
        Map<String,Object> result = new HashMap<>();
        for (var entry : logical.entrySet()) {
            if (entry.getKey() == null) throw invalid();
            Object value = entry.getValue();
            result.put(entry.getKey(), RollbackConvergence.secret(value)
                    ? reuse(value, current.get(entry.getKey()), crypto) : RollbackConvergence.copy(value));
        }
        CollectionsUtil.mapToDictionary(result);
        return result;
    }
    private static Object reuse(Object logical, Object stored, CryptoService crypto) throws KuraException {
        if (logical instanceof Password password) {
            if (!(stored instanceof String cipher) || password.getPassword() == null || crypto == null) throw invalid();
            char[] plain = crypto.decryptAes(cipher.toCharArray());
            try { if (plain == null || !Arrays.equals(password.getPassword(), plain)) throw invalid(); }
            finally { if (plain != null) Arrays.fill(plain, '\0'); }
            return cipher;
        }
        if (logical instanceof Password[] passwords) {
            if (!(stored instanceof String[] strings) || passwords.length != strings.length) throw invalid();
            String[] result = new String[strings.length];
            for (int i=0; i<result.length; i++) result[i]=(String) reuse(passwords[i], strings[i], crypto);
            return result;
        }
        if (logical instanceof List<?> values && stored instanceof List<?> ciphers) {
            // Equinox can return an ordinary List for a historical Vector. Keep the admitted
            // CM representation and authenticate every element in order before seeding.
            if (values.size() != ciphers.size()) throw invalid();
            Collection<Object> result = CollectionsUtil.newCollectionLike(ciphers);
            var iterator = ciphers.iterator();
            for (Object value : values) result.add(reuse(value, iterator.next(), crypto));
            return result;
        }
        throw invalid();
    }
    private static KuraException invalid() {
        return new KuraException(KuraErrorCode.CONFIGURATION_ERROR, "Guarded normal password representation differs from admitted CM");
    }
}
