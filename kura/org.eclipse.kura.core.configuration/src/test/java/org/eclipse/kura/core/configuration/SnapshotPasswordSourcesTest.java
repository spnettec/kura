/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.io.OutputStream;
import java.nio.file.Files;
import org.osgi.service.cm.Configuration;
import org.osgi.service.cm.ConfigurationAdmin;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import java.nio.file.Path;
import java.util.*;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.system.SystemService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class SnapshotPasswordSourcesTest {
    @TempDir Path directory;
    class Fixture extends ConfigurationServiceImpl {
        XmlComponentConfigurations captured;
        XmlComponentConfigurations loaded;
        @Override XmlComponentConfigurations loadEncryptedSnapshotFileContent(long id)throws org.eclipse.kura.KuraException {
            return loaded==null ? super.loadEncryptedSnapshotFileContent(id) : loaded;
        }
        void seed(ComponentConfigurationImpl configuration)throws Exception {
            loaded=new XmlComponentConfigurations();loaded.setPasswordEncoding(XmlComponentConfigurations.LOGICAL_PASSWORD_ENCODING);loaded.setConfigurations(List.of(configuration));Files.writeString(directory.resolve("snapshot_1.xml"),"owned logical fixture");
        }
        void startup()throws Exception {var method=ConfigurationServiceImpl.class.getDeclaredMethod("loadLatestSnapshotInConfigAdmin");method.setAccessible(true);method.invoke(this);}

        Fixture()throws Exception {
            setCryptoService(RollbackConvergenceTest.crypto());
            var system=mock(SystemService.class);var props=new Properties();props.setProperty("kura.snapshots.encrypt","false");
            when(system.getProperties()).thenReturn(props);when(system.getKuraSnapshotsCount()).thenReturn(100);setSystemService(system);
        }
        @Override String getSnapshotsDirectory(){return directory.toString();}
        @Override protected void marshal(OutputStream output,Object value){captured=(XmlComponentConfigurations)value;}
        @SuppressWarnings("unchecked") void scc(String pid)throws Exception{((Set<String>)ProviderPlanReadBudgetTest.field("activatedSelfConfigComponents").get(this)).add(pid);}
        void save(List<ComponentConfiguration> all,List<ComponentConfiguration> encryptedUpdates)throws Exception {
            var method=ConfigurationServiceImpl.class.getDeclaredMethod("saveSnapshot",Collection.class,Collection.class);method.setAccessible(true);method.invoke(this,all,encryptedUpdates);
            assertTrue(captured.hasLogicalPasswords());
        }
        Object secret(String pid,String key){return captured.getConfigurations().stream().filter(c->pid.equals(c.getPid())).findFirst().orElseThrow().getConfigurationProperties().get(key);}
    }
    @Test void cmCipherAndSccLogicalPasswordHaveDifferentExplicitSourceBoundaries()throws Exception {
        var core=new Fixture();core.scc("scc");
        var cm=new ComponentConfigurationImpl("cm",null,Map.of("secret",new Password("encrypted:clear")));
        var scc=new ComponentConfigurationImpl("scc",null,Map.of("secret",new Password("encrypted:logical content")));scc.setLogicalPasswords(true);
        core.save(List.of(cm,scc),List.of());
        assertEquals("clear",core.secret("cm","secret").toString());assertEquals("encrypted:logical content",core.secret("scc","secret").toString());
        assertEquals("encrypted:clear",cm.getConfigurationProperties().get("secret").toString());
    }
    @Test void mixedSccSnapshotDecryptsOnlyEncryptedUpdateFields()throws Exception {
        var core=new Fixture();core.scc("scc");
        var values=Map.<String,Object>of("keep",new Password("encrypted:logical keep"),"patch",new Password("encrypted:new logical"));
        var update=new ComponentConfigurationImpl("scc",null,Map.of("patch",values.get("patch")));
        var logical=new ComponentConfigurationImpl("scc",null,values);logical.setLogicalPasswords(true);core.save(List.of(logical),List.of(update));
        assertEquals("encrypted:logical keep",core.secret("scc","keep").toString());assertEquals("new logical",core.secret("scc","patch").toString());
        assertEquals("encrypted:new logical",update.getConfigurationProperties().get("patch").toString());
    }
    @Test void decodedLogicalSnapshotKeepsProvenanceWhenItsProviderIsAbsent()throws Exception {
        var core=new Fixture();var decoded=new ComponentConfigurationImpl("absent",null,Map.of("secret",new Password("encrypted:logical content")));decoded.setLogicalPasswords(true);
        core.save(List.of(decoded),List.of());assertEquals("encrypted:logical content",core.secret("absent","secret").toString());
    }
    @ParameterizedTest @ValueSource(booleans={false,true})
    void startupEncryptsMarkedLogicalPasswordsBeforeSingletonOrFactorySeeding(boolean factory)throws Exception {
        var core=new Fixture();var values=new HashMap<String,Object>();values.put("kura.service.pid","owned");values.put("secret",new Password("encrypted:logical"));if(factory)values.put("service.factoryPid","owned.factory");
        var decoded=new ComponentConfigurationImpl("owned",null,values);decoded.setLogicalPasswords(true);core.seed(decoded);
        var admin=mock(ConfigurationAdmin.class);var configuration=mock(Configuration.class);core.setConfigurationAdmin(admin);
        if(factory){when(configuration.getFactoryPid()).thenReturn("owned.factory");when(configuration.getPid()).thenReturn("owned.cm");when(configuration.getProperties()).thenReturn(new Hashtable<>(Map.of("kura.service.pid","owned")));when(admin.listConfigurations("(kura.service.pid=*)")).thenReturn(new Configuration[]{configuration});}
        else when(admin.getConfiguration("owned","?")).thenReturn(configuration);
        core.startup();@SuppressWarnings("rawtypes")var capture=org.mockito.ArgumentCaptor.forClass(Dictionary.class);
        if(factory)verify(configuration).updateIfDifferent(capture.capture());else verify(configuration).update(capture.capture());
        assertEquals("encrypted:encrypted:logical",capture.getValue().get("secret"));assertEquals("encrypted:logical",values.get("secret").toString());
    }
    @Test void startupAuthenticatesLegacyCipherPropertiesBeforeStoringThem()throws Exception {
        var core=new Fixture();var values=new HashMap<String,Object>();values.put("secret",new Password("encrypted:legacy"));core.seed(new ComponentConfigurationImpl("owned",null,values));core.loaded.setPasswordEncoding(null);
        var admin=mock(ConfigurationAdmin.class);var configuration=mock(Configuration.class);when(admin.getConfiguration("owned","?")).thenReturn(configuration);core.setConfigurationAdmin(admin);core.startup();
        @SuppressWarnings("rawtypes")var capture=org.mockito.ArgumentCaptor.forClass(Dictionary.class);verify(configuration).update(capture.capture());assertEquals("encrypted:legacy",capture.getValue().get("secret"));
    }

    @Test void legacySequenceAuthenticatesEachAmbiguousElementAndPreservesKnownLogicalValues() throws Exception {
        var knownLogical = new XmlConfigPropertiesAdapter.LegacyLogicalPassword("encrypted:literal".toCharArray());
        var source = new Vector<>(List.of(new Password("encrypted:stored"), new Password("legacy literal"),
                knownLogical));
        var crypto = RollbackConvergenceTest.crypto();

        var result = LegacySnapshotPasswords.logical(Map.of("secret", source, "label", "encrypted:label"), crypto);

        var passwords = assertInstanceOf(Vector.class, result.get("secret"));
        assertEquals("stored", passwords.get(0).toString());
        assertEquals("legacy literal", passwords.get(1).toString());
        assertEquals("encrypted:literal", passwords.get(2).toString());
        assertEquals("encrypted:label", result.get("label"));
        assertEquals("encrypted:stored", source.getFirst().toString());
        verify(crypto, times(2)).decryptAes(any(char[].class));
    }
    @Test void startupEncryptionFailurePreventsAnyCmSeeding()throws Exception {
        var core=new Fixture();var decoded=new ComponentConfigurationImpl("owned",null,Map.of("secret",new Password("logical")));decoded.setLogicalPasswords(true);core.seed(decoded);var crypto=RollbackConvergenceTest.crypto();when(crypto.encryptAes(any(char[].class))).thenThrow(new org.eclipse.kura.KuraException(org.eclipse.kura.KuraErrorCode.ENCODE_ERROR));core.setCryptoService(crypto);var admin=mock(ConfigurationAdmin.class);core.setConfigurationAdmin(admin);
        var error=assertThrows(java.lang.reflect.InvocationTargetException.class,core::startup);assertInstanceOf(org.eclipse.kura.KuraException.class,error.getCause());verifyNoInteractions(admin);
    }

    @Test void markedConfigurationWithoutPropertiesDoesNotBreakStartup()throws Exception {
        var core=new Fixture();var empty=new ComponentConfigurationImpl("empty",null,null);empty.setLogicalPasswords(true);core.seed(empty);var admin=mock(ConfigurationAdmin.class);core.setConfigurationAdmin(admin);core.startup();verify(admin).listConfigurations("(kura.service.pid=*)");verifyNoMoreInteractions(admin);
    }
    @Test void submittedCipherDecodeFailureCannotBeRelabelledAsLogicalSnapshotText()throws Exception {
        var core=new Fixture();core.scc("scc");var crypto=RollbackConvergenceTest.crypto();when(crypto.decryptAes(any(char[].class))).thenThrow(new org.eclipse.kura.KuraException(org.eclipse.kura.KuraErrorCode.DECODER_ERROR));core.setCryptoService(crypto);
        var encrypted=new ComponentConfigurationImpl("scc",null,Map.of("secret",new Password("encrypted:known submitted")));
        var failure=assertThrows(java.lang.reflect.InvocationTargetException.class,()->core.save(List.of(encrypted),List.of(encrypted)));assertInstanceOf(org.eclipse.kura.KuraException.class,failure.getCause());assertNull(core.captured);try(var files=Files.list(directory)){assertEquals(0,files.count());}
    }

}
