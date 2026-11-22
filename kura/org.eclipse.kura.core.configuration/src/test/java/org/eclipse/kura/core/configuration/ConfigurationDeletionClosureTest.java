package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.*;
import org.eclipse.kura.configuration.*;
import org.eclipse.kura.configuration.ConfigurationRevisionService.*;
import org.junit.jupiter.api.Test;
import org.osgi.framework.*;
import org.osgi.framework.dto.ServiceReferenceDTO;
import org.osgi.service.cm.Configuration;
import org.osgi.service.component.runtime.ServiceComponentRuntime;
import org.osgi.service.component.runtime.dto.*;

class ConfigurationDeletionClosureTest {
    static final String FIRST=ConfigurationPlanAdmissionTest.FIRST, SECOND=ConfigurationPlanAdmissionTest.SECOND,
            FACTORY=ConfigurationPlanAdmissionTest.FACTORY;
    static class Fixture extends ConfigurationPlanAdmissionTest.Fixture {
        final BundleContext context=mock(BundleContext.class);
        final ServiceComponentRuntime scr=mock(ServiceComponentRuntime.class);
        Fixture()throws Exception {
            var field=ConfigurationServiceImpl.class.getDeclaredField("bundleContext");field.setAccessible(true);field.set(this,context);
            setScrService(scr);when(scr.getComponentDescriptionDTOs()).thenReturn(List.of());
        }
        void cm(String pid,Map<String,Object> properties)throws Exception {
            var c=mock(Configuration.class);when(c.getPid()).thenReturn("cm."+pid);
            var map=new Hashtable<String,Object>(properties);map.put(ConfigurationService.KURA_SERVICE_PID,pid);
            when(c.getProperties()).thenReturn(map);when(admin.listConfigurations(null)).thenReturn(new Configuration[]{c});
        }
        void targetReference()throws Exception {
            var reference=mock(ServiceReference.class);
            var properties=Map.<String,Object>of(ConfigurationService.KURA_SERVICE_PID,FIRST,
                    Constants.SERVICE_ID,123L,Constants.OBJECTCLASS,new String[]{"owned.Native"});
            when(reference.getPropertyKeys()).thenReturn(properties.keySet().toArray(new String[0]));
            when(reference.getProperty(anyString())).thenAnswer(i->properties.get(i.getArgument(0)));
            when(context.getAllServiceReferences(null,null)).thenReturn(new ServiceReference[]{reference});
        }
        void delete(Set<String> pids,DeletionGuard guard)throws Exception {
            var revisions=new HashMap<String,String>();for(String pid:pids)revisions.put(pid,readRevision(pid).revision());
            applyConfigurationPlanIfUnchanged(List.of(),List.of(),pids,revisions,guard);
        }
        void untouched(){assertTrue(dispatched.isEmpty());assertEquals(0,snapshots);}
    }
    static DeletionGuard guard(String...pids){var factories=new HashMap<String,String>();for(String pid:pids)factories.put(pid,FACTORY);return new DeletionGuard(factories,Set.of("cloud.endpoint.service.pid"));}
    @Test void exclusiveOwnedDeletionUsesOnePlanAndOneSnapshot()throws Exception {
        var f=new Fixture();f.delete(Set.of(FIRST),guard(FIRST));
        assertEquals(List.of("delete:"+FIRST),f.dispatched);assertEquals(1,f.snapshots);assertFalse(f.values.containsKey(FIRST));
        verify(f.context,never()).getService(any());
    }
    @Test void factoryIdentityAndExactDeletionMembershipAreCheckedBeforeDispatch()throws Exception {
        for(int variant=0;variant<3;variant++){
            var f=new Fixture();final int n=variant;
            var e=assertThrows(Rejected.class,()->f.delete(Set.of(FIRST),n==0?guard(SECOND):n==1?
                    new DeletionGuard(Map.of(FIRST,"other.factory"),Set.of()):guard(FIRST,SECOND)));
            assertTrue(Set.of(Reason.CONFLICT,Reason.INVALID_ARGUMENT).contains(e.getReason()));f.untouched();
        }
    }
    @Test void persistedExactPidReferenceOutsideTheStackRejectsDeletion()throws Exception {
        var f=new Fixture();f.cm("consumer",Map.of("cloud.endpoint.service.pid",FIRST));
        assertEquals(Reason.CONFLICT,assertThrows(Rejected.class,()->f.delete(Set.of(FIRST),guard(FIRST))).getReason());f.untouched();
    }
    @Test void persistedTargetFilterOutsideTheStackRejectsDeletion()throws Exception {
        var f=new Fixture();f.cm("consumer",Map.of("ArbitraryReference.target","(kura.service.pid="+FIRST+")"));
        assertEquals(Reason.CONFLICT,assertThrows(Rejected.class,()->f.delete(Set.of(FIRST),guard(FIRST))).getReason());f.untouched();
    }
    @Test void referencesWhollyInsideTheDeletionSetAreAllowed()throws Exception {
        var f=new Fixture();f.cm(SECOND,Map.of("DataService.target","(kura.service.pid="+FIRST+")"));
        f.delete(Set.of(FIRST,SECOND),guard(FIRST,SECOND));assertEquals(2,f.dispatched.size());assertEquals(1,f.snapshots);
    }
    @Test void unrelatedCanonicalFilterDoesNotBlockDeletion()throws Exception {
        var f=new Fixture();f.cm("consumer",Map.of("DataService.target","(kura.service.pid=unrelated)"));
        f.delete(Set.of(FIRST),guard(FIRST));assertEquals(List.of("delete:"+FIRST),f.dispatched);
    }
    @Test void broadFilterIsMatchedAgainstActualServicePropertiesWithoutActivatingIt()throws Exception {
        var f=new Fixture();f.targetReference();f.cm("consumer",Map.of("Native.target","(objectClass=owned.Native)"));
        assertEquals(Reason.CONFLICT,assertThrows(Rejected.class,()->f.delete(Set.of(FIRST),guard(FIRST))).getReason());f.untouched();
        verify(f.context,never()).getService(any());
    }
    @Test void unresolvedBroadOrMalformedFilterFailsClosedBeforeAnyWrite()throws Exception {
        for(Object filter:List.of("(objectClass=unknown.Native)","broken-filter",42)){
            var f=new Fixture();f.cm("consumer",Map.of("Native.target",filter));
            assertEquals(Reason.UNSUPPORTED,assertThrows(Rejected.class,()->f.delete(Set.of(FIRST),guard(FIRST))).getReason());f.untouched();
        }
    }
    @Test void scrBoundConsumerWithoutAnyCmEntryProtectsTheTargetService()throws Exception {
        var f=new Fixture();f.targetReference();var description=new ComponentDescriptionDTO();description.name="consumer";
        var component=new ComponentConfigurationDTO();component.id=77;component.description=description;
        component.properties=Map.of(ConfigurationService.KURA_SERVICE_PID,"consumer");
        var reference=new SatisfiedReferenceDTO();var target=new ServiceReferenceDTO();target.id=123;
        reference.boundServices=new ServiceReferenceDTO[]{target};component.satisfiedReferences=new SatisfiedReferenceDTO[]{reference};
        when(f.scr.getComponentDescriptionDTOs()).thenReturn(List.of(description));
        when(f.scr.getComponentConfigurationDTOs(description)).thenReturn(List.of(component));
        assertEquals(Reason.CONFLICT,assertThrows(Rejected.class,()->f.delete(Set.of(FIRST),guard(FIRST))).getReason());f.untouched();
    }
    @Test void guardContainersAreDetachedAndDoNotRevealTheirValues() {
        var factories=new HashMap<>(Map.of(FIRST,FACTORY));var names=new HashSet<>(Set.of("cloud.endpoint.service.pid"));
        var guard=new DeletionGuard(factories,names);factories.clear();names.clear();guard.factoryPids().clear();guard.pidReferenceProperties().clear();
        assertEquals(Map.of(FIRST,FACTORY),guard.factoryPids());assertEquals(Set.of("cloud.endpoint.service.pid"),guard.pidReferenceProperties());
        assertFalse(guard.toString().contains(FIRST));
    }
    @Test void missingRuntimeOrNullGuardCannotDowngradeToTheUnguardedPlan()throws Exception {
        var f=new Fixture();f.setScrService(null);
        assertEquals(Reason.UNSUPPORTED,assertThrows(Rejected.class,()->f.delete(Set.of(FIRST),guard(FIRST))).getReason());f.untouched();
        var other=new Fixture();assertEquals(Reason.INVALID_ARGUMENT,assertThrows(Rejected.class,()->other.delete(Set.of(FIRST),null)).getReason());other.untouched();
    }
    @Test void oldProvidersRejectTheStrongerOverloadWithoutCallingTheOldPlan()throws Exception {
        var service=mock(ConfigurationRevisionService.class,CALLS_REAL_METHODS);
        assertEquals(Reason.UNSUPPORTED,assertThrows(Rejected.class,()->service.applyConfigurationPlanIfUnchanged(
                List.of(),List.of(),Set.of(FIRST),Map.of(FIRST,"a".repeat(64)),guard(FIRST))).getReason());
        verify(service,never()).applyConfigurationPlanIfUnchanged(anyList(),anyList(),anySet(),anyMap());
    }
    @Test void newReferencesInsideTheSamePlanCannotBypassDeletionClosure()throws Exception {
        for(boolean create:new boolean[]{false,true}){
            var f=new Fixture();var baseline=f.baseline();
            var updates=create?List.<ComponentConfiguration>of():List.<ComponentConfiguration>of(
                    new ComponentConfigurationImpl(SECOND,null,Map.of("DataService.target","(kura.service.pid="+FIRST+")")));
            var creations=create?List.of(new Creation(FACTORY,"plan.new",Map.of("cloud.endpoint.service.pid",FIRST))):List.<Creation>of();
            assertEquals(Reason.CONFLICT,assertThrows(Rejected.class,()->f.applyConfigurationPlanIfUnchanged(
                    updates,creations,Set.of(FIRST),baseline,guard(FIRST))).getReason());f.untouched();
        }
    }
    @Test void activePublishedReferencesOutsideCmAreAlsoChecked()throws Exception {
        var f=new Fixture();f.values.get(SECOND).put("cloud.endpoint.service.pid",FIRST);
        var field=ConfigurationServiceImpl.class.getDeclaredField("allActivatedPids");field.setAccessible(true);
        @SuppressWarnings("unchecked") var active=(Set<String>)field.get(f);active.add(SECOND);
        assertEquals(Reason.CONFLICT,assertThrows(Rejected.class,()->f.delete(Set.of(FIRST),guard(FIRST))).getReason());f.untouched();
    }
    @Test void onlyThisConfigurationServicesOwnTrackingReferencesAreExempt()throws Exception {
        for(long id:new long[]{77L,78L}){
            var f=new Fixture();f.targetReference();var description=new ComponentDescriptionDTO();description.name="observer";
            var component=new ComponentConfigurationDTO();component.id=id;component.properties=Map.of();
            var reference=new SatisfiedReferenceDTO();reference.name="ConfigurableComponent";
            var bound=new ServiceReferenceDTO();bound.id=123;reference.boundServices=new ServiceReferenceDTO[]{bound};
            component.satisfiedReferences=new SatisfiedReferenceDTO[]{reference};
            when(f.scr.getComponentDescriptionDTOs()).thenReturn(List.of(description));
            when(f.scr.getComponentConfigurationDTOs(description)).thenReturn(List.of(component));
            var ctx=mock(org.osgi.service.component.ComponentContext.class);
            var properties=new Hashtable<String,Object>();properties.put("component.id",77L);when(ctx.getProperties()).thenReturn(properties);
            var field=ConfigurationServiceImpl.class.getDeclaredField("ctx");field.setAccessible(true);field.set(f,ctx);
            if(id==77L){f.delete(Set.of(FIRST),guard(FIRST));assertEquals(1,f.dispatched.size());}
            else{assertEquals(Reason.CONFLICT,assertThrows(Rejected.class,()->f.delete(Set.of(FIRST),guard(FIRST))).getReason());f.untouched();}
        }
    }

    static void observer(Fixture f, boolean declared, String cardinality, String policy,
            String runtimeTarget, boolean unbind) throws Exception {
        f.targetReference();var description=new ComponentDescriptionDTO();description.name="native.registry.observer";
        description.properties=declared?Map.of(ConfigurationRevisionService.DELETION_OBSERVER_REFERENCES,"RequestHandlerRegistry"):Map.of();
        var declaration=new ReferenceDTO();declaration.name="RequestHandlerRegistry";
        declaration.interfaceName="org.eclipse.kura.cloudconnection.request.RequestHandlerRegistry";
        declaration.cardinality=cardinality;declaration.policy=policy;
        declaration.unbind=unbind?"unsetRequestHandlerRegistry":null;description.references=new ReferenceDTO[]{declaration};
        var component=new ComponentConfigurationDTO();component.id=77;component.description=description;
        component.properties=Map.of(ConfigurationService.KURA_SERVICE_PID,"observer",
                ConfigurationRevisionService.DELETION_OBSERVER_REFERENCES,"RequestHandlerRegistry"); // CM-only forgery must not count.
        var reference=new SatisfiedReferenceDTO();reference.name="RequestHandlerRegistry";reference.target=runtimeTarget;
        var target=new ServiceReferenceDTO();target.id=123;reference.boundServices=new ServiceReferenceDTO[]{target};
        component.satisfiedReferences=new SatisfiedReferenceDTO[]{reference};
        when(f.scr.getComponentDescriptionDTOs()).thenReturn(List.of(description));
        when(f.scr.getComponentConfigurationDTOs(description)).thenReturn(List.of(component));
    }
    @Test void descriptorDeclaredOptionalDynamicObserverCanUnbindWithoutBlockingDeletion()throws Exception {
        var f=new Fixture();observer(f,true,"0..n","dynamic",null,true);f.delete(Set.of(FIRST),guard(FIRST));
        assertEquals(List.of("delete:"+FIRST),f.dispatched);assertEquals(1,f.snapshots);
        verify(f.context,never()).getService(any());
    }
    @Test void componentOrCmPropertyCannotForgeAnObserverDeclaration()throws Exception {
        var f=new Fixture();observer(f,false,"0..n","dynamic",null,true);
        assertEquals(Reason.CONFLICT,assertThrows(Rejected.class,()->f.delete(Set.of(FIRST),guard(FIRST))).getReason());f.untouched();
    }
    @Test void requiredStaticSingleOrUnbindlessReferencesRemainProtected()throws Exception {
        for(String[] shape:new String[][]{{"1..n","dynamic","true"},{"0..n","static","true"},
                {"0..1","dynamic","true"},{"0..n","dynamic","false"}}){
            var f=new Fixture();observer(f,true,shape[0],shape[1],null,Boolean.parseBoolean(shape[2]));
            assertEquals(Reason.CONFLICT,assertThrows(Rejected.class,()->f.delete(Set.of(FIRST),guard(FIRST))).getReason());f.untouched();
        }
    }
    @Test void declaredObserverNeverExemptsExplicitTargetOrPersistedBusinessDependency()throws Exception {
        for(boolean cm:new boolean[]{false,true}){
            var f=new Fixture();observer(f,true,"0..n","dynamic",cm?null:"(kura.service.pid="+FIRST+")",true);
            if(cm)f.cm("observer",Map.of("cloud.endpoint.service.pid",FIRST));
            assertEquals(Reason.CONFLICT,assertThrows(Rejected.class,()->f.delete(Set.of(FIRST),guard(FIRST))).getReason());f.untouched();
        }
    }

}
