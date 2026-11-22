/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.any;
import java.util.*;
import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.core.configuration.util.CollectionsUtil;
import org.eclipse.kura.core.configuration.util.ComponentUtil;
import org.eclipse.kura.crypto.CryptoService;
import org.junit.jupiter.api.Test;

class PasswordCollectionTest {
    @Test void passwordCollectionsRetainTypeAndOrderAcrossEncryptionCmAndTypedRead() throws Exception {
        CryptoService crypto=mock(CryptoService.class);
        when(crypto.encryptAes(any(char[].class))).thenAnswer(call ->
                ("encrypted:"+new String((char[])call.getArgument(0))).toCharArray());
        when(crypto.decryptAes(any(char[].class))).thenAnswer(call -> {
            String value=new String((char[])call.getArgument(0));
            if(!value.startsWith("encrypted:")){throw new KuraException(KuraErrorCode.DECODER_ERROR);}
            return value.substring(10).toCharArray();
        });
        for (boolean vector : List.of(true,false)) {
            Collection<Password> source=vector ? new Vector<>() : new ArrayList<>();
            source.add(new Password("first"));source.add(new Password("second"));
            Map<String,Object> original=Map.of("passwords",source,"unchanged",1);
            var encrypted=ComponentUtil.encryptConfigurationProperties(original,crypto,true);
            assertNotSame(original,encrypted);
            assertEquals(source.getClass(),encrypted.get("passwords").getClass());
            assertEquals("first",source.iterator().next().toString());
            assertEquals(Set.of("passwords"),CollectionsUtil.passwordPropertyNames(encrypted));
            var dictionary=CollectionsUtil.mapToDictionary(encrypted);
            assertEquals(List.of("encrypted:first","encrypted:second"),new ArrayList<>((Collection<?>)dictionary.get("passwords")));
            var typed=CollectionsUtil.dictionaryToMap(dictionary,null,Set.of("passwords"));
            assertEquals(source.getClass(),typed.get("passwords").getClass());
            var service=new ConfigurationServiceImpl();service.setCryptoService(crypto);
            service.decryptConfigurationProperties(typed);
            assertEquals(List.of("first","second"),((Collection<?>)typed.get("passwords")).stream().map(Object::toString).toList());
            assertEquals(1,typed.get("unchanged"));
        }
    }
}
