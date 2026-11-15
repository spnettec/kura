/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Dictionary;
import java.util.HashMap;
import java.util.Hashtable;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import org.eclipse.kura.configuration.ComponentConfiguration;
import org.junit.jupiter.api.Test;
import org.osgi.service.cm.Configuration;
import org.osgi.service.cm.ConfigurationAdmin;

class ConfigurationRestoreTest {
    final List<Configuration> records = new ArrayList<>();
    final ConfigurationAdmin admin = mock(ConfigurationAdmin.class);
    final AtomicInteger generated = new AtomicInteger();
    ConfigurationRestoreTest() throws Exception {
        when(admin.listConfigurations(any())).thenAnswer(invocation -> records.toArray(Configuration[]::new));
        when(admin.createFactoryConfiguration(anyString(), anyString())).thenAnswer(invocation ->
            record("generated-"+generated.incrementAndGet(),invocation.getArgument(0),Map.of()));
        when(admin.getConfiguration(anyString(),anyString())).thenAnswer(invocation ->
            record(invocation.getArgument(0),null,Map.of()));
    }
    Configuration record(String servicePid, String factory, Map<String,Object> values) throws Exception {
        Configuration result=mock(Configuration.class);records.add(result);
        Map<String,Object> state=new HashMap<>(values);state.put("service.pid",servicePid);
        if(factory!=null){state.put("service.factoryPid",factory);}
        when(result.getPid()).thenReturn(servicePid);when(result.getFactoryPid()).thenReturn(factory);
        when(result.getProperties()).thenAnswer(invocation->new Hashtable<>(state));
        when(result.updateIfDifferent(any())).thenAnswer(invocation->{
            state.clear();Dictionary<String,Object> properties=invocation.getArgument(0);
            for(var keys=properties.keys();keys.hasMoreElements();){String key=keys.nextElement();state.put(key,properties.get(key));}
            state.put("service.pid",servicePid);if(factory!=null){state.put("service.factoryPid",factory);}return true;
        });
        doAnswer(invocation->{records.remove(result);return null;}).when(result).delete();return result;
    }
    ComponentConfiguration configuration(String pid, String factory, Map<String,Object> values) {
        Map<String,Object> result=new HashMap<>(values);result.put("kura.service.pid",pid);
        if(factory!=null){result.put("service.factoryPid",factory);}
        return new ComponentConfigurationImpl(pid,null,result);
    }
    @Test void replacesWholePropertiesRemovesAbsentFactoriesPreservesForeignRecordsAndStableFactory() throws Exception {
        Configuration singleton=record("single",null,Map.of("kura.service.pid","single","stale",true));
        Configuration factory=record("old-generated","factory",Map.of("kura.service.pid","retained","stale",true));
        Configuration absent=record("absent-generated","factory",Map.of("kura.service.pid","absent"));
        Configuration foreign=record("foreign-generated","foreign",Map.of("foreign","untouched"));
        List<ComponentConfiguration> target=List.of(configuration("single",null,Map.of("count",2)),
                configuration("retained","factory",Map.of("labels",new String[]{"a","b"})),
                configuration("new","factory",Map.of("enabled",true)));
        List<ComponentConfiguration> backup=new ArrayList<>();
        var result=ConfigurationRestore.apply(admin,target,old->{assertEquals(3,old.size());backup.addAll(old);
            verify(singleton,never()).updateIfDifferent(any());verify(absent,never()).delete();});
        assertEquals(List.of("absent"),result.deleted());assertEquals(List.of("new"),result.created());
        assertNull(singleton.getProperties().get("stale"));assertNull(factory.getProperties().get("stale"));
        assertEquals("old-generated",factory.getPid());verify(foreign,never()).delete();verify(foreign,never()).updateIfDifferent(any());
        assertEquals(3,backup.size());ConfigurationRestore.verify(admin,target);
    }
    @Test void deletesMissingSingletonAndChangesFactoryTypeOnlyAfterBackup() throws Exception {
        Configuration old=record("old-service","old.factory",Map.of("kura.service.pid","same"));
        Configuration removed=record("removed",null,Map.of("kura.service.pid","removed"));
        var result=ConfigurationRestore.apply(admin,List.of(configuration("same","new.factory",Map.of())),
                backup->{verify(old,never()).delete();assertEquals(2,backup.size());});
        assertTrue(result.deleted().containsAll(List.of("same","removed")));assertEquals(List.of("same"),result.created());verify(removed).delete();
    }
    @Test void failedBackupMakesNoConfigurationChanges() throws Exception {
        Configuration old=record("old","factory",Map.of("kura.service.pid","old"));
        assertThrows(IOException.class,()->ConfigurationRestore.apply(admin,List.of(configuration("new",null,Map.of())),
                backup->{throw new IOException("disk unavailable");}));
        verify(old,never()).delete();verify(admin,never()).getConfiguration(anyString(),anyString());
    }
    @Test void duplicateIdentityAndUnmanagedCollisionRejectBeforeBackup() throws Exception {
        record("a","factory",Map.of("kura.service.pid","duplicate"));record("b","factory",Map.of("kura.service.pid","duplicate"));
        assertThrows(IllegalStateException.class,()->ConfigurationRestore.apply(admin,List.of(configuration("new",null,Map.of())),
                ignored->fail("no backup after invalid preflight")));
        records.clear();record("foreign",null,Map.of("owner","external"));
        assertThrows(IllegalStateException.class,()->ConfigurationRestore.apply(admin,List.of(configuration("foreign",null,Map.of())),
                ignored->fail("foreign collision")));
    }
    @Test void invalidTargetsAndUnrepresentableOldValuesRejectBeforeMutation() throws Exception {
        for(List<ComponentConfiguration> target:List.<List<ComponentConfiguration>>of(List.<ComponentConfiguration>of(),
                List.of(configuration("same",null,Map.of()),configuration("same",null,Map.of())),
                List.of(new ComponentConfigurationImpl("a",null,Map.of("kura.service.pid","b"))),
                List.of(configuration("a",null,Map.of("x",new Object()))),
                List.of(configuration("a",null,Map.of("x",1,"X",2))))) {
            assertThrows(IllegalStateException.class,()->ConfigurationRestore.apply(admin,target,ignored->fail("invalid target")));
        }
        record("old",null,Map.of("kura.service.pid","old","unsupported",new int[][]{{1,2}}));
        assertThrows(IllegalStateException.class,()->ConfigurationRestore.apply(admin,List.of(configuration("a",null,Map.of())),
                ignored->fail("lossy backup forbidden")));
    }
    @Test void partialFailureIsNotReportedAsAppliedAndDoesNotTouchUnmanagedRecords() throws Exception {
        Configuration old=record("old",null,Map.of("kura.service.pid","old"));
        doThrow(new IOException("CM unavailable")).when(old).delete();
        assertThrows(IOException.class,()->ConfigurationRestore.apply(admin,List.of(configuration("new",null,Map.of())),ignored->{}));
        verify(admin,never()).getConfiguration(anyString(),anyString());
    }
    @Test void compensationRestoresDeletedFactoryAndOldPropertiesAndRemovesNewIdentity() throws Exception {
        record("single",null,Map.of("kura.service.pid","single","count",9,"stale",true));
        record("gone-old","factory",Map.of("kura.service.pid","gone","count",9));
        Configuration foreign=record("foreign",null,Map.of("owner","other"));
        List<ComponentConfiguration> old=ConfigurationRestore.capture(admin);
        List<ComponentConfiguration> intended=List.of(configuration("single",null,Map.of("count",2)),configuration("new","factory",Map.of("count",2)));
        ConfigurationRestore.apply(admin,intended,ignored->{});
        var result=ConfigurationRestore.compensate(admin,old,ConfigurationRestore.expected(intended),backup->{
            assertEquals(2,backup.size());ConfigurationRestore.verify(admin,intended);
        });
        assertEquals(List.of("new"),result.deleted());assertEquals(List.of("gone"),result.created());
        ConfigurationRestore.verify(admin,old);verify(foreign,never()).delete();verify(foreign,never()).updateIfDifferent(any());
    }
    @Test void compensationAcceptsOnlyReachablePartialRecordsAndRefusesExternalDriftBeforeBackup() throws Exception {
        List<ComponentConfiguration> old=List.of(configuration("same",null,Map.of("count",9)),configuration("gone","old.factory",Map.of("count",9)));
        List<ComponentConfiguration> next=List.of(configuration("same",null,Map.of("count",2)),configuration("new","factory",Map.of("count",2)));
        Configuration changed=record("same",null,Map.of("kura.service.pid","same","count",3));
        assertThrows(IllegalStateException.class,()->ConfigurationRestore.compensate(admin,old,next,ignored->fail("drift must not mutate")));
        changed.updateIfDifferent(new Hashtable<>(Map.of("kura.service.pid","same","count",2)));
        ConfigurationRestore.compensate(admin,old,next,backup->assertEquals(1,backup.size()));
        ConfigurationRestore.verify(admin,old);
        records.clear();
        assertThrows(IllegalStateException.class,()->ConfigurationRestore.compensate(admin,old,next,ignored->fail("retained identity cannot disappear")));
        record("same",null,Map.of("kura.service.pid","same","count",9));
        record("unknown",null,Map.of("kura.service.pid","unknown","count",1));
        assertThrows(IllegalStateException.class,()->ConfigurationRestore.compensate(admin,old,next,ignored->fail("unknown identity preserved")));
    }
    @Test void compensationCanReturnToOriginallyEmptySetWithoutChangingForeignRecords() throws Exception {
        Configuration foreign=record("foreign",null,Map.of("owner","other"));
        var next=List.of(configuration("new","factory",Map.of("count",2)));
        ConfigurationRestore.apply(admin,next,old->assertTrue(old.isEmpty()));
        ConfigurationRestore.compensate(admin,List.of(),next,backup->assertEquals(1,backup.size()));
        assertTrue(ConfigurationRestore.capture(admin).isEmpty());verify(foreign,never()).delete();
        assertThrows(IllegalStateException.class,()->ConfigurationRestore.apply(admin,List.of(),ignored->{}));
    }
    @Test void compensationBackupFailurePreservesAppliedStateAndEncryptedPasswordBytes() throws Exception {
        var encrypted=new org.eclipse.kura.configuration.Password("ciphertext-IV-payload");
        var next=List.of(configuration("same",null,Map.of("password",encrypted,"passwords",new org.eclipse.kura.configuration.Password[]{encrypted})));
        var exact=ConfigurationRestore.expected(next);
        assertEquals("ciphertext-IV-payload",exact.getFirst().getConfigurationProperties().get("password"));
        assertArrayEquals(new String[]{"ciphertext-IV-payload"},(String[])exact.getFirst().getConfigurationProperties().get("passwords"));
        ConfigurationRestore.apply(admin,next,ignored->{});
        assertThrows(IOException.class,()->ConfigurationRestore.compensate(admin,List.of(),exact,ignored->{throw new IOException("disk full");}));
        ConfigurationRestore.verify(admin,next);
    }

}
