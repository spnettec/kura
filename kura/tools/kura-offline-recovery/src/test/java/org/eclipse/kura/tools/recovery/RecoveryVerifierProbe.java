/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.eclipse.kura.configuration.*;
import org.eclipse.kura.core.configuration.*;
import org.osgi.framework.*;
import org.osgi.framework.startlevel.FrameworkStartLevel;
import org.osgi.service.cm.*;

/** A fresh JVM preserves the production admission's intentional lack of an in-process reset. */
public final class RecoveryVerifierProbe {
    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        Path root=Path.of(args[0]),snapshot=root.resolve("snapshot_0.xml");Files.writeString(snapshot,"pinned artifact");
        String sha=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(snapshot)));
        String id="rec-11111111-1111-1111-1111-111111111111";
        String request=root.resolve("request").toString();System.setProperty(ControlledRecovery.REQUEST_PROPERTY,request);
        boolean normalLoad = args.length == 1;
        BundleContext context=mock(BundleContext.class);Bundle framework=mock(Bundle.class);
        FrameworkStartLevel level=mock(FrameworkStartLevel.class);when(level.getStartLevel()).thenReturn(5);
        when(context.getBundle(0)).thenReturn(framework);when(framework.adapt(FrameworkStartLevel.class)).thenReturn(level);
        ConfigurationAdmin cm=mock(ConfigurationAdmin.class);Configuration value=mock(Configuration.class);
        when(value.getPid()).thenReturn("single");when(value.getProperties()).thenReturn(new Hashtable<>(Map.of("kura.service.pid","single","count",9)));
        when(cm.listConfigurations(null)).thenReturn(new Configuration[]{value});
        var cmRef=(ServiceReference<ConfigurationAdmin>)mock(ServiceReference.class);
        when(context.getServiceReference(ConfigurationAdmin.class)).thenReturn(cmRef);when(context.getService(cmRef)).thenReturn(cm);
        ConfigurationService configuration=mock(ConfigurationService.class);
        when(configuration.getConfigurableComponentPids()).thenReturn(Set.of("single"));
        var configRef=(ServiceReference<ConfigurationService>)mock(ServiceReference.class);
        when(context.getServiceReference(ConfigurationService.class)).thenReturn(configRef);when(context.getService(configRef)).thenReturn(configuration);
        var checkRef=(ServiceReference<RecoveryHealthCheck>)mock(ServiceReference.class);
        when(checkRef.getProperty(RecoveryHealthCheck.ID_PROPERTY)).thenReturn("business.check");
        RecoveryHealthCheck check=mock(RecoveryHealthCheck.class);when(context.getService(checkRef)).thenReturn(check);
        when(context.getServiceReferences(RecoveryHealthCheck.class,null)).thenReturn(List.of(checkRef));
        when(check.verify(any())).thenReturn(true);
        var challenge=new RecoveryVerificationService.Challenge(id,sha,"b".repeat(64),List.of("single"),List.of("business.check"),List.of());
        var expected=List.<ComponentConfiguration>of(new ComponentConfigurationImpl("single",null,Map.of("kura.service.pid","single","count",9)));
        if (normalLoad) {
            ControlledRecovery.admitNormalLoad(request,id,snapshot,sha);
        } else {
            ControlledRecovery.admit(request,id,snapshot,sha,expected);
        }
        try(var verifier=new RecoveryVerifier(context,expected,normalLoad)) {
            var report=verifier.verify(challenge);assertTrue(report.cmMatched());assertTrue(report.configurationServiceAvailable());
            assertEquals(normalLoad,report.normalLoad());
            assertTrue(report.components().getFirst().registered());assertTrue(report.checks().getFirst().passed());
            assertEquals(ProcessHandle.current().pid(),report.processId());assertEquals(5,report.frameworkStartLevel());
            assertTrue(report.ordinaryWritesBlocked());assertEquals(1,report.managedConfigurationCount());
            verify(value,never()).update(any());verify(value,never()).updateIfDifferent(any());verify(value,never()).delete();
            when(value.getProperties()).thenReturn(new Hashtable<>(Map.of("kura.service.pid","single","count",2)));
            assertFalse(verifier.verify(challenge).cmMatched());
            when(value.getProperties()).thenReturn(new Hashtable<>(Map.of("kura.service.pid","single","count",9)));
            when(configuration.getConfigurableComponentPids()).thenReturn(Set.of());assertFalse(verifier.verify(challenge).components().getFirst().registered());
            when(configuration.getConfigurableComponentPids()).thenReturn(Set.of("single"));
            Configuration self=mock(Configuration.class);when(self.getPid()).thenReturn("self");
            when(self.getProperties()).thenReturn(new Hashtable<>(Map.of("kura.service.pid","self","state","live")));
            var selfView=new ComponentConfigurationImpl("self",null,Map.of("kura.service.pid","self","state","live"));
            when(configuration.getComponentConfiguration("self")).thenReturn(selfView);
            var revision=mock(ConfigurationRevisionService.class);var revisionRef=(ServiceReference<ConfigurationRevisionService>)mock(ServiceReference.class);
            when(context.getServiceReference(ConfigurationRevisionService.class)).thenReturn(revisionRef);when(context.getService(revisionRef)).thenReturn(revision);
            when(revision.applicability("self")).thenReturn(new ConfigurationRevisionService.Applicability(ConfigurationRevisionService.ComponentKind.SELF_CONFIGURING,true));
            when(cm.listConfigurations(null)).thenReturn(new Configuration[]{value,self});
            assertFalse(verifier.verify(challenge).cmMatched());
            var withSelf=new RecoveryVerificationService.Challenge(id,sha,"b".repeat(64),List.of("single"),List.of("business.check"),List.of("self"));
            var selfReport=verifier.verify(withSelf);assertTrue(selfReport.cmMatched());assertEquals(1,selfReport.sourceConfigurationCount());
            assertEquals(2,selfReport.managedConfigurationCount());assertEquals(List.of("self"),selfReport.materializedSelfPids());
            when(revision.applicability("self")).thenReturn(new ConfigurationRevisionService.Applicability(ConfigurationRevisionService.ComponentKind.CONFIGURABLE,false));
            assertFalse(verifier.verify(withSelf).cmMatched());
            when(revision.applicability("self")).thenReturn(new ConfigurationRevisionService.Applicability(ConfigurationRevisionService.ComponentKind.SELF_CONFIGURING,true));
            when(self.getProperties()).thenReturn(new Hashtable<>(Map.of("kura.service.pid","self","state","foreign")));
            assertFalse(verifier.verify(withSelf).cmMatched());
            when(self.getProperties()).thenReturn(new Hashtable<>(Map.of("kura.service.pid","self","state","live")));
            when(self.getFactoryPid()).thenReturn("factory");assertFalse(verifier.verify(withSelf).cmMatched());when(self.getFactoryPid()).thenReturn(null);
            when(value.getProperties()).thenReturn(new Hashtable<>(Map.of("kura.service.pid","single","count",2)));
            assertFalse(verifier.verify(withSelf).cmMatched());
            when(value.getProperties()).thenReturn(new Hashtable<>(Map.of("kura.service.pid","single","count",9)));
            when(cm.listConfigurations(null)).thenReturn(new Configuration[]{value});
            when(context.getServiceReferences(RecoveryHealthCheck.class,null)).thenReturn(List.of(checkRef,checkRef));
            assertFalse(verifier.verify(challenge).checks().getFirst().passed());
            when(context.getServiceReferences(RecoveryHealthCheck.class,null)).thenReturn(List.of());
            assertFalse(verifier.verify(challenge).checks().getFirst().passed());
            when(context.getServiceReferences(RecoveryHealthCheck.class,null)).thenReturn(List.of(checkRef));
            doAnswer(call->{when(value.getProperties()).thenReturn(new Hashtable<>(Map.of("kura.service.pid","single","count",2)));return true;}).when(check).verify(any());
            assertFalse(verifier.verify(challenge).cmMatched());
            when(value.getProperties()).thenReturn(new Hashtable<>(Map.of("kura.service.pid","single","count",9)));
            when(check.verify(any())).thenThrow(new IllegalStateException("private-secret-canary"));
            assertFalse(verifier.verify(challenge).checks().getFirst().passed());
            assertThrows(Exception.class,()->verifier.verify(new RecoveryVerificationService.Challenge(id,sha,"b".repeat(64),List.of("foreign"),List.of("business.check"),List.of())));
            assertThrows(Exception.class,()->verifier.verify(new RecoveryVerificationService.Challenge(id,"a".repeat(64),"b".repeat(64),List.of("single"),List.of("business.check"),List.of())));
            AtomicBoolean release=new AtomicBoolean();CountDownLatch started=new CountDownLatch(1);
            doAnswer(call->{started.countDown();while(!release.get()){try{Thread.sleep(10);}catch(InterruptedException ignored){}}return true;}).when(check).verify(any());
            long begin=System.nanoTime();assertFalse(verifier.verify(challenge).checks().getFirst().passed());
            assertTrue(TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-begin)<1800);assertTrue(started.await(1,TimeUnit.SECONDS));
            assertFalse(verifier.verify(challenge).checks().getFirst().passed());release.set(true);
            assertThrows(org.eclipse.kura.KuraException.class,ControlledRecovery::requireOrdinaryWrite);
            Files.writeString(snapshot,"changed");assertThrows(Exception.class,()->verifier.verify(challenge));
        }
    }
}
