/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.lang.reflect.InvocationTargetException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Vector;

import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.core.crypto.CryptoServiceImpl;
import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.system.SystemService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class SnapshotKeyGenerationTest {
    @TempDir Path directory;
    private static final byte[] OLD="rv;ipse329183!@#".getBytes(StandardCharsets.UTF_8);
    private static final byte[] NEW="0123456789abcdef0123456789abcdef".getBytes(StandardCharsets.US_ASCII);
    private static final String XML="<?xml version=\"1.0\"?><configurations/>";

    private static CryptoServiceImpl rotating() {
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        bytes.writeBytes("YOFC-KURA-KEYRING-v1\n".getBytes(StandardCharsets.US_ASCII));
        bytes.write(2);bytes.write(1);bytes.write(0);
        for(byte[] key:new byte[][]{OLD,NEW}){bytes.write(key.length);bytes.writeBytes(key);}
        return CryptoServiceImpl.forKeyRingRecovery(bytes.toByteArray());
    }

    private static final class ReadFixture extends ConfigurationServiceImpl {
        private final CryptoService crypto;
        private final Map<String,Object> source;
        private final boolean logical;
        ReadFixture(CryptoService crypto,Map<String,Object> source,boolean logical){
            this.crypto=crypto;this.source=source;this.logical=logical;setCryptoService(crypto);
        }
        @Override XmlComponentConfigurations loadEncryptedSnapshotFileContent(long id)throws KuraException{
            try{
                XmlConfigPropertiesAdapter adapter=new XmlConfigPropertiesAdapter(this.crypto,this.logical);
                XmlComponentConfigurations result=new XmlComponentConfigurations();
                if(this.logical){result.setPasswordEncoding(XmlComponentConfigurations.LOGICAL_PASSWORD_ENCODING);}
                result.setConfigurations(List.of(new ComponentConfigurationImpl("owned",null,
                        adapter.unmarshal(adapter.marshal(this.source)))));
                return result;
            }catch(Exception e){throw KuraException.internalError(e);}
        }
    }

    @ParameterizedTest @ValueSource(booleans={false,true})
    void oldAndNewCmPasswordShapesRemainReadableAfterRotation(boolean current)throws Exception{
        CryptoServiceImpl writer=current?rotating():CryptoServiceImpl.forSnapshotRecovery(OLD,false);
        String clear="原密码 / retained";
        Password cipher=new Password(writer.encryptAes(clear.toCharArray()));
        Map<String,Object> source=Map.of("scalar",cipher,"array",new Password[]{cipher},"vector",new Vector<>(List.of(cipher)));
        Map<String,Object> decoded=new ReadFixture(rotating(),source,false).getSnapshot(1).get(0).getConfigurationProperties();
        assertTrue(ConfigurationRevision.sameValue(new Password(clear),decoded.get("scalar")));
        assertTrue(ConfigurationRevision.sameValue(new Password[]{new Password(clear)},decoded.get("array")));
        assertTrue(ConfigurationRevision.sameValue(new Vector<>(List.of(new Password(clear))),decoded.get("vector")));
        assertEquals(cipher,source.get("scalar"));
    }

    @Test void logicalPasswordThatLooksLikeNewCiphertextIsNotDecryptedTwice()throws Exception{
        Password logical=new Password(new String(rotating().encryptAes("logical text".toCharArray())));
        Map<String,Object> decoded=new ReadFixture(rotating(),Map.of("secret",logical),true)
                .getSnapshot(1).get(0).getConfigurationProperties();
        assertTrue(ConfigurationRevision.sameValue(logical,decoded.get("secret")));
    }

    @ParameterizedTest @ValueSource(strings={"default","true","false"})
    void keyGenerationsRespectTheExistingSnapshotEncryptionSetting(String setting)throws Exception{
        CryptoServiceImpl crypto=rotating();
        Properties properties=new Properties();
        if(!setting.equals("default")){properties.setProperty("kura.snapshots.encrypt",setting);}
        SystemService system=mock(SystemService.class);
        when(system.getProperties()).thenReturn(properties);
        when(system.getKuraSnapshotsDirectory()).thenReturn(this.directory.toString());
        ConfigurationServiceImpl service=new ConfigurationServiceImpl(){
            @Override protected void marshal(OutputStream output,Object value)throws KuraException{
                try{output.write(XML.getBytes(StandardCharsets.UTF_8));}catch(IOException e){throw KuraException.internalError(e);}
            }
        };
        service.setSystemService(system);service.setCryptoService(crypto);
        var method=ConfigurationServiceImpl.class.getDeclaredMethod("writeSnapshot",long.class,XmlComponentConfigurations.class);
        method.setAccessible(true);
        XmlComponentConfigurations configurations=new XmlComponentConfigurations();
        configurations.setConfigurations(List.of(new ComponentConfigurationImpl("fixture",null,Map.of("value","synthetic"))));
        try{method.invoke(service,7L,configurations);}
        catch(InvocationTargetException e){throw (Exception)e.getCause();}
        Path file=this.directory.resolve("snapshot_7.xml");
        assertEquals(java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"),Files.getPosixFilePermissions(file));
        String written=Files.readString(file);
        if(setting.equals("false")){assertEquals(XML,written);}
        else{
            assertTrue(written.startsWith("KURA2."));
            assertArrayEquals(XML.toCharArray(),crypto.decryptAes(written.toCharArray()));
        }
    }
}
