/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.crypto.CryptoService;
import org.junit.jupiter.api.Test;
import java.nio.file.Path;
import org.junit.jupiter.api.io.TempDir;
import org.eclipse.kura.core.configuration.metatype.*;

class SnapshotLogicalPasswordBoundaryTest {
    @TempDir Path directory;
    static CryptoService crypto() throws Exception {
        var service=mock(CryptoService.class);
        when(service.decryptAes(any(char[].class))).thenAnswer(i->{String value=new String((char[])i.getArgument(0));if(!value.startsWith("aes:"))throw new KuraException(KuraErrorCode.DECODER_ERROR);return value.substring(4).toCharArray();});
        when(service.encodeBase64(anyString())).thenAnswer(i->Base64.getEncoder().encodeToString(((String)i.getArgument(0)).getBytes(StandardCharsets.UTF_8)));
        when(service.decodeBase64(anyString())).thenAnswer(i->new String(Base64.getDecoder().decode((String)i.getArgument(0)),StandardCharsets.UTF_8));
        return service;
    }
    static class Fixture extends ConfigurationServiceImpl {
        final XmlConfigPropertiesAdapter adapter;
        final XmlConfigPropertiesAdapted encoded;
        final boolean logical;
        Fixture(Object source) throws Exception { this(source, true); }
        Fixture(Object source, boolean logical) throws Exception {
            this.logical=logical;
            var crypto=crypto();setCryptoService(crypto);adapter=new XmlConfigPropertiesAdapter(crypto,logical);
            encoded=adapter.marshal(Map.of("secret",source));
        }
        @Override XmlComponentConfigurations loadEncryptedSnapshotFileContent(long id) throws KuraException {
            try {
                var result=new XmlComponentConfigurations();if(logical)result.setPasswordEncoding(XmlComponentConfigurations.LOGICAL_PASSWORD_ENCODING);result.setConfigurations(List.of(new ComponentConfigurationImpl("owned",null,adapter.unmarshal(encoded))));return result;
            } catch(Exception failure){throw new KuraException(KuraErrorCode.DECODER_ERROR,failure);}
        }
        Object raw()throws Exception{return loadEncryptedSnapshotFileContent(1).getConfigurations().get(0).getConfigurationProperties().get("secret");}
        Object read()throws Exception{return getSnapshot(1).get(0).getConfigurationProperties().get("secret");}
    }
    @Test void scalarLogicalPasswordMustNotBeDecryptedTwice()throws Exception {
        var expected=new Password("aes:logical content");var core=new Fixture(expected);
        assertTrue(ConfigurationRevision.sameValue(expected,core.raw()));
        assertTrue(ConfigurationRevision.sameValue(expected,core.read()));
    }
    @Test void arrayLogicalPasswordsMustNotBeDecryptedTwice()throws Exception {
        var expected=new Password[]{new Password("aes:first"),new Password("aes:second")};var core=new Fixture(expected);
        assertTrue(ConfigurationRevision.sameValue(expected,core.raw()));
        assertTrue(ConfigurationRevision.sameValue(expected,core.read()));
    }
    @Test void vectorLogicalPasswordsMustNotBeDecryptedTwice()throws Exception {
        var expected=new Vector<>(List.of(new Password("aes:first"),new Password("aes:second")));var core=new Fixture(expected);
        assertTrue(ConfigurationRevision.sameValue(expected,core.raw()));
        assertTrue(ConfigurationRevision.sameValue(expected,core.read()));
    }
    @Test void legacyBase64CmCipherStillNeedsItsExistingDecryptionPath()throws Exception {
        // The old wire bytes are identical to the scalar logical-value case above.
        var core=new Fixture(new Password("aes:legacy clear"),false);
        assertTrue(ConfigurationRevision.sameValue(new Password("legacy clear"),core.read()));
    }
    @Test void ordinaryLegacyLogicalTextRemainsReadable()throws Exception {
        var expected=new Password("ordinary logical text");var core=new Fixture(expected,false);
        assertTrue(ConfigurationRevision.sameValue(expected,core.read()));
    }
    @Test void legacyConfigurationWithoutAPropertyMapIsStillReadable()throws Exception {
        var core=new ConfigurationServiceImpl(){
            @Override XmlComponentConfigurations loadEncryptedSnapshotFileContent(long id){
                var result=new XmlComponentConfigurations();result.setConfigurations(List.of(new ComponentConfigurationImpl("empty",null,null)));return result;
            }
        };
        assertNull(core.getSnapshot(1).get(0).getConfigurationProperties());
    }

    @Test void publicSccReadDoesNotReinterpretItsStableMapLogicalPassword()throws Exception {
        try(var core=new RollbackConvergenceTest.Fixture(directory)) {
            core.setCryptoService(RollbackConvergenceTest.crypto());var published=core.published.get(RollbackPreflightTest.FIRST);
            var expected=new Password("encrypted:logical content");published.put("secret",expected);published.put("secret-array",new Password[]{expected});published.put("secret-vector",new Vector<>(List.of(expected)));
            var read=core.readRevision(RollbackPreflightTest.FIRST);
            for(String key:List.of("secret","secret-array","secret-vector"))assertTrue(ConfigurationRevision.sameValue(published.get(key),read.configuration().getConfigurationProperties().get(key)));
            assertEquals("encrypted:logical content",published.get("secret").toString());
        }
    }
    @Test void ordinaryCmPublicReadStillDecryptsStoredPasswordOnce()throws Exception {
        try(var core=new RollbackConvergenceTest.Fixture(directory)) {
            core.setCryptoService(RollbackConvergenceTest.crypto());
            @SuppressWarnings("unchecked")var scc=(Set<String>)ProviderPlanReadBudgetTest.field("activatedSelfConfigComponents").get(core);scc.remove(RollbackPreflightTest.FIRST);
            var definition=new Tocd();definition.setId(RollbackPreflightTest.FIRST);var ad=new Tad();ad.setId("secret");ad.setType(Tscalar.PASSWORD);definition.addAD(ad);
            @SuppressWarnings("unchecked")var definitions=(Map<String,Tocd>)ProviderPlanReadBudgetTest.field("ocds").get(core);definitions.put(RollbackPreflightTest.FIRST,definition);core.live.get(RollbackPreflightTest.FIRST).put("secret","encrypted:clear");
            assertEquals("clear",core.getComponentConfiguration(RollbackPreflightTest.FIRST).getConfigurationProperties().get("secret").toString());
        }
    }

}
