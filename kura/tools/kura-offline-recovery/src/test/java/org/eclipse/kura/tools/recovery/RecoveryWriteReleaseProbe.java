/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import org.eclipse.kura.configuration.*;
import org.eclipse.kura.core.configuration.*;
import org.osgi.framework.*;
import org.osgi.framework.startlevel.FrameworkStartLevel;
import org.osgi.service.cm.*;

public final class RecoveryWriteReleaseProbe {
    @SuppressWarnings("unchecked") public static void main(String[] args) throws Exception {
        Path root=Path.of(args[0]);
        if(args[1].equals("journal-reopen")){verifyReopenedJournal(root.resolve("data"));return;}
        boolean journalMode=args[1].startsWith("journal-"),successMode=args[1].equals("success")||args[1].equals("journal-handoff");
        ConfigurationServiceImpl journalCore=null;
        if(journalMode){
            Path data=Files.createDirectory(root.resolve("data"));journalCore=new ConfigurationServiceImpl();
            var initialize=ConfigurationServiceImpl.class.getDeclaredMethod("initializeIntentJournal",Path.class);initialize.setAccessible(true);initialize.invoke(journalCore,data);
            var field=ConfigurationServiceImpl.class.getDeclaredField("intentJournal");field.setAccessible(true);Object journal=field.get(journalCore);
            var begin=journal.getClass().getDeclaredMethod("begin",String.class,Set.class);begin.setAccessible(true);
            try(var ticket=(AutoCloseable)begin.invoke(journal,"plan",Set.of("owned.created","owned.deleted"))){}
        }
        Path snapshot=root.resolve("snapshot_0.xml"),normal=root.resolve("normal.properties");
        Files.writeString(snapshot,"pinned source");String sha=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(snapshot)));
        String request=root.resolve("request.properties").toString(),id="rec-11111111-1111-1111-1111-111111111111";
        System.setProperty(ControlledRecovery.REQUEST_PROPERTY,request);ControlledRecovery.admitNormalLoad(request,id,snapshot,sha);
        BundleContext context=mock(BundleContext.class);Bundle framework=mock(Bundle.class);FrameworkStartLevel level=mock(FrameworkStartLevel.class);
        when(context.getBundle(0)).thenReturn(framework);when(framework.adapt(FrameworkStartLevel.class)).thenReturn(level);when(level.getStartLevel()).thenReturn(5);
        ConfigurationAdmin cm=mock(ConfigurationAdmin.class);Configuration value=mock(Configuration.class);when(value.getPid()).thenReturn("single");
        when(value.getProperties()).thenReturn(new Hashtable<>(Map.of("kura.service.pid","single","count",9)));when(cm.listConfigurations(null)).thenReturn(new Configuration[]{value});
        var cmRef=(ServiceReference<ConfigurationAdmin>)mock(ServiceReference.class);when(context.getServiceReference(ConfigurationAdmin.class)).thenReturn(cmRef);when(context.getService(cmRef)).thenReturn(cm);
        ConfigurationService service=mock(ConfigurationService.class);when(service.getConfigurableComponentPids()).thenReturn(Set.of("single"));
        var configRef=(ServiceReference<ConfigurationService>)mock(ServiceReference.class);when(context.getServiceReference(ConfigurationService.class)).thenReturn(configRef);when(context.getService(configRef)).thenReturn(service);
        var healthRef=(ServiceReference<RecoveryHealthCheck>)mock(ServiceReference.class);when(healthRef.getProperty(RecoveryHealthCheck.ID_PROPERTY)).thenReturn("business.check");
        RecoveryHealthCheck check=mock(RecoveryHealthCheck.class);when(context.getService(healthRef)).thenReturn(check);when(context.getServiceReferences(RecoveryHealthCheck.class,null)).thenReturn(List.of(healthRef));
        when(check.verify(any())).thenReturn(!args[1].equals("business-failure"));
        var challenge=new RecoveryVerificationService.Challenge(id,sha,"b".repeat(64),List.of("single"),List.of("business.check"),List.of());
        var bounds=new RecoveryCompletionService.Bounds(args[1].equals("wrong-bounds")?2:1,1,2,List.of());
        var completion=new RecoveryCompletionService.Request(challenge,"complete-11111111-1111-1111-1111-111111111111", "a".repeat(64),"c".repeat(64),"d".repeat(64),
                System.currentTimeMillis()+(args[1].equals("expired")?-1:10000),bounds);
        Path receipt=normal.resolveSibling(normal.getFileName()+".write-release.properties");
        if(args[1].equals("publish-failure")||args[1].equals("journal-publish-failure")){Files.createDirectory(receipt);}
        var expected=List.<ComponentConfiguration>of(new ComponentConfigurationImpl("single",null,Map.of("kura.service.pid","single","count",9)));
        try(var verifier=new RecoveryVerifier(context,expected)) {
            var release=new RecoveryWriteRelease(verifier,normal);
            assertThrows(org.eclipse.kura.KuraException.class,ControlledRecovery::requireOrdinaryWrite);
            if(!successMode) {
                assertThrows(org.eclipse.kura.KuraException.class,()->release.complete(completion));
                assertThrows(org.eclipse.kura.KuraException.class,ControlledRecovery::requireOrdinaryWrite);
                assertTrue(ControlledRecovery.completionEvidence().isEmpty());
                if(!args[1].equals("publish-failure")&&!args[1].equals("journal-publish-failure")){assertFalse(Files.exists(receipt));}
            } else {
                var result=release.complete(completion);assertTrue(result.writeReleaseCommitted());assertFalse(result.kuraRecoveryVerified());
                assertTrue(result.preReleaseHealth().ordinaryWritesBlocked());assertFalse(ControlledRecovery.requested());
                assertEquals(completion.completionId(),ControlledRecovery.completionEvidence().orElseThrow().completionId());
                assertDoesNotThrow(ControlledRecovery::requireOrdinaryWrite);assertTrue(ControlledRecovery.evidence().isEmpty());
                byte[] bytes=Files.readAllBytes(receipt);assertTrue(new String(bytes).contains("scope=administrator-selected-checks"));
                assertEquals(result.receiptSha256(),HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)));
                assertThrows(org.eclipse.kura.KuraException.class,()->release.complete(completion));assertArrayEquals(bytes,Files.readAllBytes(receipt));
                Files.writeString(snapshot,"legitimate post-release change");Files.writeString(root.resolve("snapshot_2.xml"),"new ordinary snapshot");
                assertDoesNotThrow(ControlledRecovery::requireOrdinaryWrite);assertDoesNotThrow(()->ControlledRecovery.verifySnapshotDirectory(root));
                assertTrue(ControlledRecovery.configurations().isEmpty());
            }
            verify(value,never()).update(any());verify(value,never()).delete();
            if(journalCore!=null){
                var deactivate=ConfigurationServiceImpl.class.getDeclaredMethod("deactivate");deactivate.setAccessible(true);deactivate.invoke(journalCore);
                if(successMode){
                    try(var files=Files.list(root.resolve("data/configuration-dispatch-journal-v1"))){assertEquals(1,files.filter(p->p.toString().endsWith(".release")).count());}
                    var child=new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin","java").toString(),"-cp",System.getProperty("java.class.path"),RecoveryWriteReleaseProbe.class.getName(),root.toString(),"journal-reopen").redirectErrorStream(true).start();
                    assertTrue(child.waitFor(12,java.util.concurrent.TimeUnit.SECONDS));assertEquals(0,child.exitValue(),new String(child.getInputStream().readAllBytes()));
                }
            }
        }
    }
    private static void verifyReopenedJournal(Path data)throws Exception {
        var core=new ConfigurationServiceImpl();
        var initialize=ConfigurationServiceImpl.class.getDeclaredMethod("initializeIntentJournal",Path.class);initialize.setAccessible(true);initialize.invoke(core,data);
        try {
            var field=ConfigurationServiceImpl.class.getDeclaredField("intentJournal");field.setAccessible(true);Object journal=field.get(core);
            var startup=journal.getClass().getDeclaredMethod("requireStartup");startup.setAccessible(true);startup.invoke(journal);
            var ordinary=journal.getClass().getDeclaredMethod("requireOrdinaryWrite");ordinary.setAccessible(true);ordinary.invoke(journal);
        }finally{var deactivate=ConfigurationServiceImpl.class.getDeclaredMethod("deactivate");deactivate.setAccessible(true);deactivate.invoke(core);}
    }

}
