package org.eclipse.kura.core.configuration;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.*;
import java.util.concurrent.*;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ConfigurationRevisionService.Reason;
import org.eclipse.kura.configuration.ConfigurationRevisionService.Rejected;
import org.junit.jupiter.api.Test;

class ConfigurationEditorAdmissionTest {
    static class Fixture extends ConfigurationServiceImpl {
        final Map<String,Map<String,Object>> values = new HashMap<>(Map.of(
                "edit.first",new HashMap<>(Map.of("name","first")),
                "edit.second",new HashMap<>(Map.of("name","second"))));
        int writes; boolean failAfterFirst; boolean delay; List<ComponentConfiguration> delayed;
        @Override public synchronized ComponentConfiguration getComponentConfiguration(String pid) {
            return values.containsKey(pid) ? new ComponentConfigurationImpl(pid,
                    mock(org.eclipse.kura.core.configuration.metatype.Tocd.class), values.get(pid)) : null;
        }
        @Override protected boolean revisionTargetTracked(String pid) { return values.containsKey(pid); }
        @Override public synchronized void updateConfigurations(List<ComponentConfiguration> configs, boolean snapshot)
                throws KuraException {
            assertTrue(snapshot);
            if (delay) { delayed=configs; writes++; return; }
            for (var config:configs) {
                values.get(config.getPid()).putAll(config.getConfigurationProperties());writes++;
                if(failAfterFirst)throw new KuraException(KuraErrorCode.CONFIGURATION_UPDATE);
            }
        }
    }
    static ComponentConfiguration edit(String pid,Map<String,Object> values) {
        return new ComponentConfigurationImpl(pid,null,values);
    }
    static Map<String,String> baselines(Fixture service)throws Exception {
        var result=new HashMap<String,String>();
        for(String pid:List.of("edit.first","edit.second"))result.put(pid,service.readRevision(pid).revision());
        return result;
    }
    @Test void oneStaleMemberRejectsTheWholeBatchBeforeAnyWrite()throws Exception {
        var service=new Fixture();var baseline=baselines(service);service.values.get("edit.second").put("name","remote");
        var failure=assertThrows(Rejected.class,()->service.updateConfigurationsIfUnchanged(
                List.of(edit("edit.first",Map.of("name","stale-first")),edit("edit.second",Map.of("name","stale-second"))),baseline));
        assertEquals(Reason.CONFLICT,failure.getReason());assertEquals(0,service.writes);
        assertEquals("first",service.values.get("edit.first").get("name"));
        assertEquals("remote",service.values.get("edit.second").get("name"));
    }
    @Test void localEditorKeepsLegacyPropertyCoverageBeyondRemotePatchLimits()throws Exception {
        var service=new Fixture();var baseline=baselines(service);var many=new HashMap<String,Object>();
        for(int i=0;i<90;i++)many.put("custom."+i,"value"+i);
        service.updateConfigurationsIfUnchanged(List.of(edit("edit.first",many),
                edit("edit.second",Map.of("name","edited"))),baseline);
        assertEquals(2,service.writes);assertEquals("value89",service.values.get("edit.first").get("custom.89"));
        assertNotEquals(baseline.get("edit.first"),service.readRevision("edit.first").revision());
        assertEquals("edited",service.readRevision("edit.second").configuration().getConfigurationProperties().get("name"));
    }
    @Test void aPartialBatchFailureWithholdsEveryParticipatingRevision()throws Exception {
        var service=new Fixture();var baseline=baselines(service);service.failAfterFirst=true;
        var failure=assertThrows(KuraException.class,()->service.updateConfigurationsIfUnchanged(
                List.of(edit("edit.first",Map.of("name","written")),edit("edit.second",Map.of("name","not-written"))),baseline));
        assertFalse(failure instanceof Rejected);assertEquals(1,service.writes);
        for(String pid:baseline.keySet())assertEquals(Reason.CONFLICT,
                assertThrows(Rejected.class,()->service.readRevision(pid)).getReason());
    }
    @Test void pendingCallbacksCannotMintFreshEditableOldViews()throws Exception {
        var service=new Fixture();var baseline=baselines(service);service.delay=true;
        service.updateConfigurationsIfUnchanged(List.of(edit("edit.first",Map.of("name","submitted")),
                edit("edit.second",Map.of("name","submitted"))),baseline);
        assertThrows(Rejected.class,()->service.readRevision("edit.first"));
        for(var config:service.delayed)service.values.get(config.getPid()).putAll(config.getConfigurationProperties());
        assertNotEquals(baseline.get("edit.first"),service.readRevision("edit.first").revision());
    }
    @Test void twoEditorsCannotBothSubmitTheSameBaseline()throws Exception {
        var service=new Fixture();String token=service.readRevision("edit.first").revision();var start=new CountDownLatch(1);
        try(var pool=Executors.newFixedThreadPool(2)) {
            Callable<Boolean> write=()->{start.await();try{service.updateConfigurationsIfUnchanged(
                    List.of(edit("edit.first",Map.of("name",Thread.currentThread().getName()))),
                    Map.of("edit.first",token));return true;}catch(Rejected e){assertEquals(Reason.CONFLICT,e.getReason());return false;}};
            var first=pool.submit(write);var second=pool.submit(write);start.countDown();
            assertNotEquals(first.get(5,TimeUnit.SECONDS),second.get(5,TimeUnit.SECONDS));
        }
        assertEquals(1,service.writes);
    }
    @Test void aLostReplyCannotReplayEvenAnIdenticalValueSubmission() throws Exception {
        var service = new Fixture(); String token = service.readRevision("edit.first").revision();
        var update = List.of(edit("edit.first", Map.of("name", "first")));
        var baseline = Map.of("edit.first", token);
        service.updateConfigurationsIfUnchanged(update, baseline);
        assertNotEquals(token, service.readRevision("edit.first").revision());
        assertEquals(Reason.CONFLICT, assertThrows(Rejected.class,
                () -> service.updateConfigurationsIfUnchanged(update, baseline)).getReason());
        assertEquals(1, service.writes);
    }
}
