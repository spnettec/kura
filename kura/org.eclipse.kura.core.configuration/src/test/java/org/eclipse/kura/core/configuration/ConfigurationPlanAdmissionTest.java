/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.util.*;
import java.util.concurrent.*;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.configuration.*;
import org.eclipse.kura.configuration.ConfigurationRevisionService.*;
import org.junit.jupiter.api.Test;
import org.osgi.service.cm.Configuration;
import org.osgi.service.cm.ConfigurationAdmin;

class ConfigurationPlanAdmissionTest {
    static final String FIRST = "plan.first", SECOND = "plan.second", NEW = "plan.new", FACTORY = "plan.factory";
    static class Fixture extends ConfigurationServiceImpl {
        final Map<String,Map<String,Object>> values = new HashMap<>();
        final List<String> dispatched = new ArrayList<>();
        final ConfigurationAdmin admin = mock(ConfigurationAdmin.class);
        boolean failAfterCreation, failSnapshot, delayed; int snapshots, explicitSnapshotCalls;
        final Map<String,Map<String,Object>> callbacks = new HashMap<>();
        Fixture() throws Exception {
            values.put(FIRST, new HashMap<>(Map.of("name", "first", "service.factoryPid", FACTORY)));
            values.put(SECOND, new HashMap<>(Map.of("name", "second", "service.factoryPid", FACTORY)));
            setConfigurationAdmin(admin);
            var field=ConfigurationServiceImpl.class.getDeclaredField("factoryPidByPid");field.setAccessible(true);
            @SuppressWarnings("unchecked") var factories=(Map<String,String>)field.get(this);
            factories.put(FIRST,FACTORY);factories.put(SECOND,FACTORY);
        }
        @Override public synchronized ComponentConfiguration getComponentConfiguration(String pid) {
            return values.containsKey(pid) ? new ComponentConfigurationImpl(pid,
                    mock(org.eclipse.kura.core.configuration.metatype.Tocd.class), values.get(pid)) : null;
        }
        @Override protected boolean revisionTargetTracked(String pid) { return values.containsKey(pid); }
        @Override public Set<String> getFactoryComponentPids() { return Set.of(FACTORY); }
        @Override public synchronized void deleteFactoryConfiguration(String pid, boolean snapshot) {
            assertFalse(snapshot); dispatched.add("delete:"+pid);values.remove(pid);
        }
        @Override public synchronized void createFactoryConfiguration(String factory, String pid,
                Map<String,Object> properties, boolean snapshot) throws KuraException {
            assertFalse(snapshot);assertEquals(FACTORY,factory);dispatched.add("create:"+pid);
            values.put(pid,new HashMap<>(properties));
            if(failAfterCreation)throw new Rejected(Reason.INVALID_ARGUMENT);
        }
        @Override public synchronized void updateConfigurations(List<ComponentConfiguration> configs, boolean snapshot) {
            assertTrue(snapshot);
            for(var config:configs) {
                dispatched.add("update:"+config.getPid());
                if(delayed) callbacks.put(config.getPid(), new HashMap<>(config.getConfigurationProperties()));
                else values.get(config.getPid()).putAll(config.getConfigurationProperties());
            }
            snapshots++;
            if(failSnapshot)throw new IllegalStateException("snapshot failed after dispatch");
        }
        @Override public synchronized long snapshot() {
            explicitSnapshotCalls++;snapshots++;
            if(failSnapshot)throw new IllegalStateException("snapshot failed after dispatch");
            return snapshots;
        }
        Map<String,String> baseline() throws KuraException {
            return Map.of(FIRST,readRevision(FIRST).revision(),SECOND,readRevision(SECOND).revision());
        }
    }
    static ComponentConfiguration update(String pid,String value) {
        return new ComponentConfigurationImpl(pid,null,Map.of("name",value));
    }
    static Creation creation(String pid) { return new Creation(FACTORY,pid,Map.of("name","created")); }

    @Test void staleGuardPreventsDeletionAndCreationBeforeAnyDispatch() throws Exception {
        var service=new Fixture();var before=service.baseline();service.values.get(SECOND).put("name","remote");
        var e=assertThrows(Rejected.class,()->service.applyConfigurationPlanIfUnchanged(
                List.of(),List.of(creation(NEW)),Set.of(FIRST),before));
        assertEquals(Reason.CONFLICT,e.getReason());assertTrue(service.dispatched.isEmpty());assertEquals(0,service.snapshots);
    }
    @Test void deletionCreationAndUpdatesUseOneAdmissionAndOneFinalSnapshot() throws Exception {
        var service=new Fixture();var before=service.baseline();
        service.applyConfigurationPlanIfUnchanged(List.of(update(SECOND,"edited")),List.of(creation(NEW)),Set.of(FIRST),before);
        assertEquals(List.of("delete:"+FIRST,"create:"+NEW,"update:"+SECOND),service.dispatched);
        assertFalse(service.values.containsKey(FIRST));assertEquals("created",service.values.get(NEW).get("name"));
        assertEquals("edited",service.values.get(SECOND).get("name"));assertEquals(1,service.snapshots);
        assertNotEquals(before.get(SECOND),service.readRevision(SECOND).revision());
    }
    @Test void aDormantConfigurationAdminTargetCannotBeMistakenForANewPid() throws Exception {
        var service=new Fixture();var occupied=mock(Configuration.class);when(occupied.getPid()).thenReturn("cm.dormant");
        var properties=new Hashtable<String,Object>();properties.put(ConfigurationService.KURA_SERVICE_PID,NEW);
        when(occupied.getProperties()).thenReturn(properties);when(service.admin.listConfigurations(null)).thenReturn(new Configuration[]{occupied});
        assertEquals(Reason.CONFLICT,assertThrows(Rejected.class,()->service.applyConfigurationPlanIfUnchanged(
                List.of(),List.of(creation(NEW)),Set.of(FIRST),service.baseline())).getReason());
        assertTrue(service.dispatched.isEmpty());verify(service.admin,never()).getConfiguration(anyString(),anyString());
    }
    @Test void aSamePidFactoryReplacementNeedsTheOldRevisionAndDeletesBeforeCreating() throws Exception {
        var service=new Fixture();var before=service.baseline();
        service.applyConfigurationPlanIfUnchanged(List.of(),List.of(creation(FIRST)),Set.of(FIRST),before);
        assertEquals(List.of("delete:"+FIRST,"create:"+FIRST),service.dispatched);
        assertEquals("created",service.values.get(FIRST).get("name"));assertEquals(1,service.snapshots);
        assertNotEquals(before.get(FIRST),service.readRevision(FIRST).revision());
    }
    @Test void missingAndDuplicatePlanTargetsRejectWithoutSideEffects() throws Exception {
        for(int example=0;example<5;example++) {
            var service=new Fixture();var before=service.baseline();final int n=example;
            var e=assertThrows(Rejected.class,()-> {
                switch(n) {
                case 0:service.applyConfigurationPlanIfUnchanged(List.of(update(FIRST,"x")),List.of(),Set.of(),Map.of(SECOND,before.get(SECOND)));break;
                case 1:service.applyConfigurationPlanIfUnchanged(List.of(),List.of(creation(NEW),creation(NEW)),Set.of(),before);break;
                case 2:service.applyConfigurationPlanIfUnchanged(List.of(update(FIRST,"x")),List.of(),Set.of(FIRST),before);break;
                case 3:service.applyConfigurationPlanIfUnchanged(List.of(),List.of(creation(FIRST)),Set.of(),before);break;
                default:service.applyConfigurationPlanIfUnchanged(List.of(),List.of(new Creation("missing.factory",NEW,Map.of())),Set.of(),before);
                }
            });
            assertTrue(Set.of(Reason.INVALID_ARGUMENT,Reason.CONFLICT,Reason.UNSUPPORTED).contains(e.getReason()));
            assertTrue(service.dispatched.isEmpty());assertEquals(before,service.baseline());
        }
    }
    @Test void dispatchFailureIsUnknownForAllGuardsAndNewTargetsWithoutReplay() throws Exception {
        var service=new Fixture();var before=service.baseline();service.failAfterCreation=true;
        var e=assertThrows(KuraException.class,()->service.applyConfigurationPlanIfUnchanged(
                List.of(update(SECOND,"never")),List.of(creation(NEW)),Set.of(FIRST),before));
        assertFalse(e instanceof Rejected);assertEquals(List.of("delete:"+FIRST,"create:"+NEW),service.dispatched);
        for(String pid:List.of(FIRST,SECOND,NEW))assertEquals(Reason.CONFLICT,
                assertThrows(Rejected.class,()->service.readRevision(pid)).getReason());
        assertEquals(0,service.snapshots);
        assertThrows(Rejected.class,()->service.applyConfigurationPlanIfUnchanged(
                List.of(update(SECOND,"never")),List.of(creation(NEW)),Set.of(FIRST),before));
        assertEquals(2,service.dispatched.size());
    }
    @Test void delayedUpdatesWithholdFreshViewsAndAnIdenticalPlanCannotReplay() throws Exception {
        var service=new Fixture();var before=service.baseline();service.delayed=true;
        service.applyConfigurationPlanIfUnchanged(List.of(update(SECOND,"submitted")),List.of(),Set.of(),before);
        assertThrows(Rejected.class,()->service.readRevision(SECOND));
        service.values.get(SECOND).putAll(service.callbacks.get(SECOND));
        assertNotEquals(before.get(SECOND),service.readRevision(SECOND).revision());
        assertEquals(Reason.CONFLICT,assertThrows(Rejected.class,()->service.applyConfigurationPlanIfUnchanged(
                List.of(update(SECOND,"submitted")),List.of(),Set.of(),before)).getReason());
        assertEquals(1,service.dispatched.size());
    }
    @Test void creationOnlyAndDeletionOnlyPlansRetainTheSameFinalSnapshotPolicy() throws Exception {
        var created=new Fixture();created.applyConfigurationPlanIfUnchanged(List.of(),List.of(creation(NEW)),Set.of(),Map.of());
        assertEquals(List.of("create:"+NEW),created.dispatched);assertEquals(1,created.snapshots);
        var deleted=new Fixture();var before=deleted.baseline();
        deleted.applyConfigurationPlanIfUnchanged(List.of(),List.of(),Set.of(FIRST),Map.of(FIRST,before.get(FIRST)));
        assertEquals(List.of("delete:"+FIRST),deleted.dispatched);assertEquals(1,deleted.snapshots);
    }
    @Test void deletingTheLastConfigurationsExplicitlyPersistsAnEmptySnapshot() throws Exception {
        var service=new Fixture();var before=service.baseline();
        service.applyConfigurationPlanIfUnchanged(List.of(),List.of(),Set.of(FIRST,SECOND),before);
        assertTrue(service.values.isEmpty());assertEquals(1,service.snapshots);
        // Legacy updateConfigurations(empty,true) skips saveSnapshot when all current
        // configurations are gone. The plan must invoke snapshot() explicitly.
        assertEquals(1,service.explicitSnapshotCalls);
    }
    @Test void snapshotFailureWithholdsUnchangedReadGuardsAsWellAsWrittenTargets() throws Exception {
        var service=new Fixture();var before=service.baseline();service.failSnapshot=true;
        var error=assertThrows(KuraException.class,()->service.applyConfigurationPlanIfUnchanged(
                List.of(update(SECOND,"submitted")),List.of(),Set.of(),before));
        assertFalse(error instanceof Rejected);assertEquals("submitted",service.values.get(SECOND).get("name"));
        assertEquals(1,service.snapshots);
        for(String pid:before.keySet())assertEquals(Reason.CONFLICT,assertThrows(Rejected.class,()->service.readRevision(pid)).getReason());
        assertEquals(1,service.dispatched.size());
    }
    @Test void batchViewsAreDetachedAndNeverReturnAPartialMissingView() throws Exception {
        var service=new Fixture();service.values.get(FIRST).put("list",new ArrayList<>(List.of("value")));
        var views=service.readRevisionViews(Set.of(FIRST,SECOND));
        @SuppressWarnings("unchecked") var list=(List<String>)views.get(FIRST).configuration().getConfigurationProperties().get("list");
        list.clear();assertEquals(List.of("value"),service.values.get(FIRST).get("list"));
        assertThrows(UnsupportedOperationException.class,()->views.clear());
        assertEquals(Reason.NOT_FOUND,assertThrows(Rejected.class,()->service.readRevisionViews(Set.of(FIRST,"missing"))).getReason());
    }
    @Test void batchViewsAcceptPublicOcdImplementationsWithoutCastingToCoreMetadata() throws Exception {
        var metadata=mock(org.eclipse.kura.configuration.metatype.OCD.class);
        var service=new Fixture() {
            @Override public synchronized ComponentConfiguration getComponentConfiguration(String pid) {
                var properties=values.get(pid);
                if(properties==null)return null;
                return new ComponentConfiguration() {
                    public String getPid(){return pid;}
                    public org.eclipse.kura.configuration.metatype.OCD getDefinition(){return metadata;}
                    public org.eclipse.kura.configuration.metatype.OCD getLocalizedDefinition(String locale){return metadata;}
                    public Map<String,Object> getConfigurationProperties(){return properties;}
                };
            }
        };
        var view=service.readRevisionViews(Set.of(FIRST)).get(FIRST);
        assertSame(metadata,view.configuration().getDefinition());
        assertSame(metadata,view.configuration().getLocalizedDefinition("zh"));
        view.configuration().getConfigurationProperties().put("name","detached");
        assertEquals("first",service.values.get(FIRST).get("name"));
    }
    @Test void replacementValidationUsesTheNewProviderBeforeDeletingTheOldComponent() throws Exception {
        var service=new Fixture();var helper=new ProviderDefinitionTest();
        var text=helper.attribute("name",org.osgi.service.metatype.AttributeDefinition.STRING,0,"allowed");
        when(text.validate("created")).thenReturn("private validation detail");
        var definition=new ProviderDefinition(new ProviderDefinition.Source(helper.provider(text)),FACTORY);
        var field=ConfigurationServiceImpl.class.getDeclaredField("ocds");field.setAccessible(true);
        @SuppressWarnings("unchecked") var definitions=(Map<String,org.eclipse.kura.core.configuration.metatype.Tocd>)field.get(service);
        definitions.put(FACTORY,definition);
        var before=service.baseline();
        var rejected=assertThrows(Rejected.class,()->service.applyConfigurationPlanIfUnchanged(
                List.of(),List.of(creation(FIRST)),Set.of(FIRST),before));
        assertEquals(Reason.INVALID_ARGUMENT,rejected.getReason());assertTrue(service.dispatched.isEmpty());
        assertEquals(before,service.baseline());assertFalse(rejected.getMessage().contains("private validation detail"));
        service.applyConfigurationPlanIfUnchanged(List.of(),List.of(new Creation(FACTORY,FIRST,Map.of("name","allowed"))),Set.of(FIRST),before);
        assertEquals(List.of("delete:"+FIRST,"create:"+FIRST),service.dispatched);
    }
    @Test void twoCompetingPlansCannotBothPassTheSameGuard() throws Exception {
        var service=new Fixture();var before=service.baseline();var start=new CountDownLatch(1);
        try(var pool=Executors.newFixedThreadPool(2)) {
            Callable<Boolean> action=()-> {start.await();try {
                service.applyConfigurationPlanIfUnchanged(List.of(update(SECOND,"second")),List.of(),Set.of(),before);return true;
            }catch(Rejected e){assertEquals(Reason.CONFLICT,e.getReason());return false;}};
            var a=pool.submit(action);var b=pool.submit(action);start.countDown();
            assertNotEquals(a.get(5,TimeUnit.SECONDS),b.get(5,TimeUnit.SECONDS));
        }
        assertEquals(1,service.dispatched.size());
    }
}
