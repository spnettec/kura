/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.nio.file.*;
import java.io.IOException;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.eclipse.kura.*;
import org.eclipse.kura.configuration.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.osgi.framework.ServiceReference;
import org.osgi.service.cm.*;

class RollbackPreflightTest {
    static final String FIRST="first.provider", SECOND="second.provider", EXTRA="factory.extra", EXTERNAL="owned.external";
    @TempDir Path directory;
    static class Fixture extends ProviderPlanReadBudgetTest.Fixture {
        final Path directory;
        final ConfigurationAdmin admin=mock(ConfigurationAdmin.class);
        final Map<String,Map<String,Object>> live=new HashMap<>();
        final List<ComponentConfiguration> snapshots=new ArrayList<>();
        final AtomicInteger externalApplies=new AtomicInteger(),cmWrites=new AtomicInteger(),factoryDeletes=new AtomicInteger(),metadataReads=new AtomicInteger();
        boolean forbidReadsAfterDispatch,failCmWrite;
        Throwable ownerFailure;
        Fixture(Path directory) throws Exception {
            this.directory=directory;Files.createDirectories(directory);Files.writeString(directory.resolve("snapshot_1.xml"),"fixture snapshot bytes");
            List<Configuration> configurations=new ArrayList<>();
            for(String pid:List.of(FIRST,SECOND)) {
                live.put(pid,new HashMap<>(Map.of("value","current",ConfigurationService.KURA_SERVICE_PID,pid)));
                var c=mock(Configuration.class);when(c.getPid()).thenReturn(pid);when(admin.getConfiguration(pid,"?")).thenReturn(c);
                when(c.getProperties()).thenAnswer(i->new Hashtable<>(live.get(pid)));
                doAnswer(i->{cmWrites.incrementAndGet();@SuppressWarnings("unchecked") Dictionary<String,Object> values=i.getArgument(0);Map<String,Object> copy=new HashMap<>();for(var keys=values.keys();keys.hasMoreElements();){String key=keys.nextElement();copy.put(key,values.get(key));}live.put(pid,copy);if(failCmWrite)throw new IOException("after CM mutation");return null;}).when(c).update(any());
                configurations.add(c);snapshots.add(new ComponentConfigurationImpl(pid,null,new HashMap<>(Map.of("value","restored",ConfigurationService.KURA_SERVICE_PID,pid))));
                @SuppressWarnings("unchecked") ServiceReference<SelfConfiguringComponent> reference=(ServiceReference<SelfConfiguringComponent>)bundles.getServiceReferences((String)null,"(kura.service.pid="+pid+")")[0];
                SelfConfiguringComponent original=bundles.getService(reference);
                SelfConfiguringComponent provider=()->{metadataReads.incrementAndGet();if(forbidReadsAfterDispatch&&externalApplies.get()>0)throw new AssertionError("metadata read after external apply");var base=original.getConfiguration();return new ComponentConfigurationImpl(pid,(org.eclipse.kura.core.configuration.metatype.Tocd)base.getDefinition(),new HashMap<>(live.get(pid)));};
                when(bundles.getService(reference)).thenReturn(provider);
            }
            var factory=mock(Configuration.class);when(factory.getPid()).thenReturn(EXTRA);when(factory.getFactoryPid()).thenReturn("owned.factory");when(factory.getProperties()).thenReturn(new Hashtable<>(Map.of(ConfigurationService.KURA_SERVICE_PID,EXTRA,ConfigurationAdmin.SERVICE_FACTORYPID,"owned.factory")));doAnswer(i->{factoryDeletes.incrementAndGet();return null;}).when(factory).delete();configurations.add(factory);
            when(admin.listConfigurations("("+ConfigurationService.KURA_SERVICE_PID+"=*)")).thenReturn(configurations.toArray(Configuration[]::new));setConfigurationAdmin(admin);
            var external=new ExternalConfigurations(EXTERNAL);var handler=mock(ExternalConfigurationHandler.class);when(handler.getPid()).thenReturn(EXTERNAL);doAnswer(i->{externalApplies.incrementAndGet();if(ownerFailure!=null)throw ownerFailure;return null;}).when(handler).applyConfiguration(anyMap(),any());external.bind(handler);ProviderPlanReadBudgetTest.field("externalConfigurations").set(this,external);
            snapshots.add(new ComponentConfigurationImpl(EXTERNAL,null,new HashMap<>(Map.of("value","confirmed"))));
        }
        @Override String getSnapshotsDirectory(){return directory.toString();}
        @Override XmlComponentConfigurations loadEncryptedSnapshotFileContent(long id){assertEquals(1,id);var xml=new XmlComponentConfigurations();xml.setConfigurations(snapshots);return xml;}
        @SuppressWarnings("unchecked") Set<String> uncertain()throws Exception{return(Set<String>)ProviderPlanReadBudgetTest.field("revisionUncertain").get(this);}
        @SuppressWarnings("unchecked") Map<String,Long> admissions()throws Exception{return(Map<String,Long>)ProviderPlanReadBudgetTest.field("revisionAdmissions").get(this);}
        @SuppressWarnings("unchecked") Map<String,Map<String,Object>> pending()throws Exception{return(Map<String,Map<String,Object>>)ProviderPlanReadBudgetTest.field("revisionPending").get(this);}
    }
    @Test void sharedPreflightExpiryPreventsExternalApplyFactoryDeletionAndCmUpdates() throws Exception {
        try(var core=new Fixture(directory)) {
            core.slow.set(true);assertThrows(KuraException.class,()->core.rollback(1));
            assertEquals(0,core.externalApplies.get());assertEquals(0,core.factoryDeletes.get());assertEquals(0,core.cmWrites.get());assertTrue(core.admissions().isEmpty());assertTrue(core.uncertain().isEmpty());
            assertEquals("fixture snapshot bytes",Files.readString(directory.resolve("snapshot_1.xml")));
        }
    }
    @Test void allMetadataReadsFinishBeforeTheFirstExternalApply() throws Exception {
        try(var core=new Fixture(directory)) {
            core.forbidReadsAfterDispatch=true;assertDoesNotThrow(()->core.rollback(1));
            assertEquals(2,core.metadataReads.get());assertEquals(1,core.externalApplies.get());assertEquals(1,core.factoryDeletes.get());assertEquals(2,core.cmWrites.get());
        }
    }
    @Test void partialRollbackMutationRetainsUncertaintyForEveryAdmittedTarget() throws Exception {
        try(var core=new Fixture(directory)) {
            core.failCmWrite=true;assertThrows(KuraPartialSuccessException.class,()->core.rollback(1));
            assertEquals(1,core.externalApplies.get());assertEquals(1,core.factoryDeletes.get());assertEquals(2,core.cmWrites.get());
            assertTrue(core.uncertain().containsAll(Set.of(FIRST,SECOND,EXTRA)));
            for(String pid:List.of(FIRST,SECOND))assertEquals(ConfigurationRevisionService.Reason.CONFLICT,assertThrows(ConfigurationRevisionService.Rejected.class,()->core.readRevision(pid)).getReason());
        }
    }
    @Test void successfulRollbackOnlyClearsPendingAndUncertaintyWithinItsPreparedScope() throws Exception {
        try(var core=new Fixture(directory)) {
            core.uncertain().addAll(Set.of(FIRST,"untouched.uncertain"));core.pending().put(FIRST,Map.of("value","pending"));core.pending().put("untouched.uncertain",Map.of("value","keep"));
            core.rollback(1);assertFalse(core.uncertain().contains(FIRST));assertTrue(core.uncertain().contains("untouched.uncertain"));assertFalse(core.pending().containsKey(FIRST));assertTrue(core.pending().containsKey("untouched.uncertain"));
            assertEquals("restored",core.readRevision(FIRST).configuration().getConfigurationProperties().get("value"));
        }
    }
    @Test void evenASameValueRollbackInvalidatesPreviouslyIssuedTokens() throws Exception {
        try(var core=new Fixture(directory)) {
            for(var config:core.snapshots)if(!EXTERNAL.equals(config.getPid()))config.getConfigurationProperties().put("value","current");
            String before=core.readRevision(FIRST).revision();core.rollback(1);assertEquals(0,core.cmWrites.get());
            assertNotEquals(before,core.readRevision(FIRST).revision());assertEquals(1L,core.admissions().get(FIRST));
        }
    }
    @Test void aRejectedAfterOwnerApplyEnteredCannotMasqueradeAsAPreflightRejection() throws Exception {
        try(var core=new Fixture(directory)) {
            var original=new ConfigurationRevisionService.Rejected(ConfigurationRevisionService.Reason.INVALID_ARGUMENT);core.ownerFailure=original;
            KuraException failure=assertThrows(KuraException.class,()->core.rollback(1));
            assertFalse(failure instanceof ConfigurationRevisionService.Rejected);assertSame(original,failure.getCause());
            assertEquals(1,core.externalApplies.get());assertEquals(0,core.cmWrites.get());assertEquals(0,core.factoryDeletes.get());
            assertTrue(core.uncertain().containsAll(Set.of(FIRST,SECOND,EXTRA)));
        }
    }

    @Test @SuppressWarnings("unchecked")
    void aSourceWithdrawnAfterPreparationCannotAdmitTheRollback() throws Exception {
        try(var core=new Fixture(directory)) {
            var metadata=new ProviderDefinitionTest();var source=new ProviderDefinition.Source(metadata.provider(
                    metadata.attribute("value",org.osgi.service.metatype.AttributeDefinition.STRING,0,"current")));
            var definition=spy(new ProviderDefinition(source,FIRST));
            doAnswer(i->{Object generation=i.callRealMethod();source.invalidate();return generation;}).when(definition).generation();
            ((Map<String,org.eclipse.kura.core.configuration.metatype.Tocd>)ProviderPlanReadBudgetTest.field("ocds").get(core)).put(FIRST,definition);
            assertThrows(ConfigurationRevisionService.Rejected.class,()->core.rollback(1));
            assertEquals(0,core.externalApplies.get());assertEquals(0,core.cmWrites.get());assertEquals(0,core.factoryDeletes.get());assertTrue(core.admissions().isEmpty());assertTrue(core.uncertain().isEmpty());
        }
    }
    @Test @SuppressWarnings("unchecked")
    void replacementFactoryUsesItsNewDefinitionAndDefaultsDuringPreparation() throws Exception {
        try(var core=new Fixture(directory)) {
            var definitions=(Map<String,org.eclipse.kura.core.configuration.metatype.Tocd>)ProviderPlanReadBudgetTest.field("ocds").get(core);
            for(String factory:List.of("owned.factory","replacement.factory")) {
                var definition=new org.eclipse.kura.core.configuration.metatype.Tocd();definition.setId(factory);
                var attribute=new org.eclipse.kura.core.configuration.metatype.Tad();attribute.setId("flavor");attribute.setType(org.eclipse.kura.core.configuration.metatype.Tscalar.STRING);attribute.setDefault(factory.equals("owned.factory")?"old":"new");definition.addAD(attribute);definitions.put(factory,definition);
            }
            ((Map<String,String>)ProviderPlanReadBudgetTest.field("factoryPidByPid").get(core)).put(EXTRA,"owned.factory");
            core.snapshots.add(new ComponentConfigurationImpl(EXTRA,null,new HashMap<>(Map.of(ConfigurationAdmin.SERVICE_FACTORYPID,"replacement.factory",ConfigurationService.KURA_SERVICE_PID,EXTRA,"value","restored"))));
            var replacement=mock(Configuration.class);when(replacement.getPid()).thenReturn("replacement.factory~new");when(core.admin.createFactoryConfiguration("replacement.factory",null)).thenReturn(replacement);
            core.rollback(1);assertEquals(1,core.factoryDeletes.get());
            verify(replacement).update(argThat(values->"new".equals(values.get("flavor"))));
        }
    }

}
