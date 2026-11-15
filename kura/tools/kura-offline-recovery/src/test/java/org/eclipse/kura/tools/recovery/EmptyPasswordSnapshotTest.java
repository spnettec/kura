/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import static org.junit.jupiter.api.Assertions.*;

import java.io.ByteArrayOutputStream;
import java.lang.reflect.Array;
import java.util.*;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.configuration.XmlComponentConfigurations;
import org.eclipse.kura.core.configuration.util.ComponentUtil;
import org.eclipse.kura.core.crypto.CryptoServiceImpl;
import org.eclipse.kura.internal.xml.marshaller.unmarshaller.XmlJavaComponentConfigurationsMapper;
import org.junit.jupiter.api.Test;

class EmptyPasswordSnapshotTest {
    @Test void emptyPasswordsAreAuthenticatedForScalarArrayVectorAndListWithoutDoubleEncryption() throws Exception {
        var crypto=CryptoServiceImpl.forSnapshotRecovery(null,true);
        // Legacy AES decoding deliberately accepts empty input; it is not ciphertext authentication.
        assertArrayEquals(new char[0],crypto.decryptAes(new char[0]));
        for(Object source:List.of(new Password(""),new Password[]{new Password("")},
                new Vector<>(List.of(new Password(""))),new ArrayList<>(List.of(new Password(""))))) {
            var encrypted=ComponentUtil.encryptConfigurationProperties(Map.of("secret",source),crypto,true);
            Password password=first(encrypted.get("secret"));
            assertTrue(password.getPassword().length>0,"empty cleartext must become real AES-GCM ciphertext");
            assertArrayEquals(new char[0],crypto.decryptAes(password.getPassword()));
            var again=ComponentUtil.encryptConfigurationProperties(encrypted,crypto,true);
            assertArrayEquals(password.getPassword(),first(again.get("secret")).getPassword());
            assertEquals(0,first(source).getPassword().length,"do not mutate caller's cleartext");
            byte[] xml=snapshot(encrypted.get("secret"),crypto);
            var decoded=SnapshotTool.decode(xml,crypto,"authenticated");
            assertEquals(1,decoded.report().authenticated);assertEquals(0,decoded.report().legacy);
            Object actual=decoded.configurations().getFirst().getConfigurationProperties().get("secret");
            assertEquals(source.getClass(),actual.getClass());
            assertArrayEquals(new char[0],crypto.decryptAes(first(actual).getPassword()));
        }
    }
    @Test void authenticatedCiphertextForAnEmptyPasswordCannotBecomeLegacyOnWrongKey() throws Exception {
        var crypto=CryptoServiceImpl.forSnapshotRecovery(null,true);
        byte[] xml=snapshot(new Password(crypto.encryptAes(new char[0])),crypto);
        byte[] key=new byte[16];Arrays.fill(key,(byte)23);
        var wrong=CryptoServiceImpl.forSnapshotRecovery(key,false);
        for(String policy:List.of("authenticated","legacy")) {
            assertThrows(Exception.class,()->SnapshotTool.decode(xml,wrong,policy));
        }
    }
    private static Password first(Object value) {
        if(value instanceof Password password){return password;}
        if(value instanceof Collection<?> collection){return (Password)collection.iterator().next();}
        return (Password)Array.get(value,0);
    }
    private static byte[] snapshot(Object value,CryptoServiceImpl crypto) throws Exception {
        var configurations=new XmlComponentConfigurations();
        configurations.setConfigurations(List.of(new ComponentConfigurationImpl("empty-password",null,
                Map.of("kura.service.pid","empty-password","secret",value))));
        var output=new ByteArrayOutputStream();new XmlJavaComponentConfigurationsMapper(crypto).marshal(output,configurations);
        return output.toByteArray();
    }
}
