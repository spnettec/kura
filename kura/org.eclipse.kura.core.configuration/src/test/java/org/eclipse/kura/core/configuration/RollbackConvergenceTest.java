/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.nio.file.Path;
import java.util.*;
import org.eclipse.kura.*;
import org.eclipse.kura.configuration.*;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.core.configuration.metatype.*;
import org.eclipse.kura.crypto.CryptoService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.osgi.framework.ServiceReference;

class RollbackConvergenceTest {
    @TempDir Path directory;
    static class Fixture extends RollbackPreflightTest.Fixture {
        final Map<String,Map<String,Object>> published=new HashMap<>();
        @SuppressWarnings("unchecked") Fixture(Path directory)throws Exception {
            super(directory);
            for(String pid:List.of(RollbackPreflightTest.FIRST,RollbackPreflightTest.SECOND)) {
                published.put(pid,new HashMap<>(live.get(pid)));
                ServiceReference<SelfConfiguringComponent> ref=(ServiceReference<SelfConfiguringComponent>)bundles.getServiceReferences((String)null,"(kura.service.pid="+pid+")")[0];
                SelfConfiguringComponent original=bundles.getService(ref);
                when(bundles.getService(ref)).thenReturn((SelfConfiguringComponent)()->{
                    var before=original.getConfiguration();var logical=new ComponentConfigurationImpl(pid,(Tocd)before.getDefinition(),new HashMap<>(published.get(pid)));logical.setLogicalPasswords(true);return logical;
                });
            }
        }
        Map<String,Object> target(){return snapshots.stream().filter(c->c.getPid().equals(RollbackPreflightTest.FIRST)).findFirst().orElseThrow().getConfigurationProperties();}
        void restored(){published.get(RollbackPreflightTest.FIRST).put("value","restored");}
        void assertBlocked()throws Exception {
            var rejection=assertThrows(ConfigurationRevisionService.Rejected.class,()->readRevision(RollbackPreflightTest.FIRST));
            assertEquals(ConfigurationRevisionService.Reason.CONFLICT,rejection.getReason());
            assertTrue(uncertain().isEmpty(),"successful CM rollback is pending observation, not UNKNOWN");
        }
        void writable()throws Exception{assertTrue(readRevision(RollbackPreflightTest.FIRST).revision().matches("[0-9a-f]{64}"));}
        @SuppressWarnings("unchecked") void defaultField()throws Exception {
            var definition=new Tocd();definition.setId(RollbackPreflightTest.FIRST);var value=new Tad();value.setId("value");value.setType(Tscalar.STRING);definition.addAD(value);var hidden=new Tad();hidden.setId("hidden-default");hidden.setType(Tscalar.STRING);hidden.setDefault("server-default");definition.addAD(hidden);
            ((Map<String,Tocd>)ProviderPlanReadBudgetTest.field("ocds").get(this)).put(RollbackPreflightTest.FIRST,definition);
        }
    }
    static CryptoService crypto()throws Exception {
        var crypto=mock(CryptoService.class);
        when(crypto.encryptAes(any(char[].class))).thenAnswer(i->("encrypted:"+new String((char[])i.getArgument(0))).toCharArray());
        when(crypto.decryptAes(any(char[].class))).thenAnswer(i->{String value=new String((char[])i.getArgument(0));if(!value.startsWith("encrypted:"))throw new KuraException(KuraErrorCode.DECODER_ERROR);return value.substring("encrypted:".length()).toCharArray();});
        return crypto;
    }
    @Test void aSuccessfulCmRollbackDoesNotAuthorizeTheStillOldSccView()throws Exception {
        try(var core=new Fixture(directory)) {
            core.rollback(1);core.assertBlocked();core.restored();core.writable();assertEquals(2,core.cmWrites.get());assertEquals(1,core.externalApplies.get());
        }
    }
    @Test void defaultsAbsentFromThePublicSnapshotNeedNotBePublishedByTheScc()throws Exception {
        try(var core=new Fixture(directory)) {
            core.defaultField();core.rollback(1);core.assertBlocked();core.restored();assertFalse(core.published.get(RollbackPreflightTest.FIRST).containsKey("hidden-default"));core.writable();
        }
    }
    @Test void aPublishedDefaultMustMatchThePreparedDefaultBeforeObservationCompletes()throws Exception {
        try(var core=new Fixture(directory)) {
            core.defaultField();core.rollback(1);core.restored();core.published.get(RollbackPreflightTest.FIRST).put("hidden-default","old-default");core.assertBlocked();core.published.get(RollbackPreflightTest.FIRST).put("hidden-default","server-default");core.writable();
        }
    }
    @Test void aRemovedPublishedPropertyCannotBeReintroducedByAnOldEditableView()throws Exception {
        try(var core=new Fixture(directory)) {
            core.published.get(RollbackPreflightTest.FIRST).put("obsolete","old");core.rollback(1);core.restored();core.assertBlocked();core.published.get(RollbackPreflightTest.FIRST).remove("obsolete");core.writable();
        }
    }
    @Test void runtimeIdentityIsExcludedFromTheConvergenceProjection()throws Exception {
        try(var core=new Fixture(directory)) {
            core.target().put("service.pid","old-service");core.target().put("component.id",7L);core.target().put("component.name","old-component");core.target().put("service.bundleLocation","old-location");core.rollback(1);core.restored();var values=core.published.get(RollbackPreflightTest.FIRST);values.put("service.pid","new-service");values.put("component.id",99L);values.put("component.name","new-component");values.put("service.bundleLocation","new-location");core.writable();
        }
    }
    @Test void restoredPasswordsAreEncryptedForCmAndNotMutatedInTheSnapshot()throws Exception {
        try(var core=new Fixture(directory)) {
            var crypto=crypto();core.setCryptoService(crypto);core.target().put("secret",new Password("restored-secret"));core.target().put("secret-array",new Password[]{new Password("first"),new Password("")});core.target().put("secret-list",new Vector<>(List.of(new Password("list"))));
            core.rollback(1);Map<String,Object> cm=core.live.get(RollbackPreflightTest.FIRST);assertEquals("encrypted:restored-secret",cm.get("secret"));assertArrayEquals(new String[]{"encrypted:first","encrypted:"},(String[])cm.get("secret-array"));assertEquals(new Vector<>(List.of("encrypted:list")),cm.get("secret-list"));assertEquals("restored-secret",core.target().get("secret").toString());
        }
    }
    @Test void passwordEncryptionFailureRejectsBeforeOwnerOrCmDispatch()throws Exception {
        try(var core=new Fixture(directory)) {
            var crypto=crypto();when(crypto.encryptAes(any(char[].class))).thenThrow(new KuraException(KuraErrorCode.ENCODE_ERROR));core.setCryptoService(crypto);core.target().put("secret",new Password("restored-secret"));
            assertThrows(KuraException.class,()->core.rollback(1));assertEquals(0,core.externalApplies.get());assertEquals(0,core.cmWrites.get());assertEquals(0,core.factoryDeletes.get());assertTrue(core.admissions().isEmpty());assertTrue(core.uncertain().isEmpty());assertEquals("restored-secret",core.target().get("secret").toString());
        }
    }
    @Test void scalarArrayAndCollectionPasswordsMustConvergeAsClearPublicValues()throws Exception {
        try(var core=new Fixture(directory)) {
            core.setCryptoService(crypto());core.target().put("secret",new Password("restored"));core.target().put("secret-array",new Password[]{new Password("first"),new Password("")});core.target().put("secret-list",new Vector<>(List.of(new Password("list"))));
            var publicValues=core.published.get(RollbackPreflightTest.FIRST);publicValues.put("secret",new Password("old"));publicValues.put("secret-array",new Password[]{new Password("old")});publicValues.put("secret-list",new Vector<>(List.of(new Password("old"))));core.rollback(1);core.restored();core.assertBlocked();publicValues.put("secret",new Password("restored"));publicValues.put("secret-array",new Password[]{new Password("first"),new Password("")});publicValues.put("secret-list",new Vector<>(List.of(new Password("list"))));core.writable();
        }
    }
    @Test void snapshotProjectionKeepsLogicalPasswordsAndDetachedContainers()throws Exception {
        var source=new HashMap<String,Object>();source.put("secret",new Password("encrypted:looks-like-cipher"));
        source.put("secret-array",new Password[]{new Password("first"),new Password("")});
        var prepared=RollbackConvergence.prepare(source,Map.of(),Set.of(),crypto());
        assertEquals("encrypted:encrypted:looks-like-cipher",prepared.stored().get("secret").toString());
        var logical=prepared.convergence().snapshotProperties();
        assertEquals("encrypted:looks-like-cipher",logical.get("secret").toString());
        ((Password[])logical.get("secret-array"))[0].getPassword()[0]='X';
        assertEquals("first",((Password[])prepared.convergence().snapshotProperties().get("secret-array"))[0].toString());
        assertEquals("first",((Password[])source.get("secret-array"))[0].toString());
    }
    @Test void invalidOrNullPasswordCellsFailBeforeDispatch()throws Exception {
        try(var core=new Fixture(directory)) {
            core.setCryptoService(crypto());core.target().put("secret-array",new Password[]{null});
            assertThrows(KuraException.class,()->core.rollback(1));
            assertEquals(0,core.externalApplies.get());assertEquals(0,core.cmWrites.get());assertTrue(core.admissions().isEmpty());
        }
    }
    @Test void metadataPasswordStringsRequireAuthenticatedCiphertext()throws Exception {
        assertThrows(KuraException.class,()->RollbackConvergence.prepare(Map.of("secret","clear"),Map.of(),Set.of("secret"),crypto()));
        var result=RollbackConvergence.prepare(Map.of("secret","encrypted:logical"),Map.of(),Set.of("secret"),crypto());
        assertEquals("logical",result.convergence().snapshotProperties().get("secret").toString());
        var empty=RollbackConvergence.prepare(Map.of("secret",""),Map.of(),Set.of("secret"),crypto());
        assertEquals("encrypted:",empty.stored().get("secret").toString());
    }
    @Test void unencryptedPasswordDefaultsCannotEscapeFailedEncryption()throws Exception {
        assertThrows(KuraException.class,()->RollbackConvergence.prepare(Map.of(),Map.of("secret",new Password("clear-default")),Set.of("secret"),crypto()));
        var ready=RollbackConvergence.prepare(Map.of(),Map.of("secret",new Password("encrypted:default")),Set.of("secret"),crypto());
        assertTrue(ready.convergence().matches(Map.of()));
        assertFalse(ready.convergence().matches(Map.of("secret",new Password("wrong"))));
        assertTrue(ready.convergence().matches(Map.of("secret",new Password("default"))));
    }

}
