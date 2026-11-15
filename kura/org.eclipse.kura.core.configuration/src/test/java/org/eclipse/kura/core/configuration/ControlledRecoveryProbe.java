/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.Password;

/** Runs in a fresh JVM: the production gate deliberately has no in-process reset/ack bypass. */
public final class ControlledRecoveryProbe {
    @FunctionalInterface interface Checked { void run() throws Exception; }
    static void blocked(Checked call) throws Exception {
        try {call.run();throw new AssertionError("write admitted");}
        catch(KuraException expected) {if(!expected.getMessage().contains("Controlled recovery")){throw expected;}}
    }
    public static void main(String[] args) throws Exception {
        Path root=Path.of(args[0]);Path snapshot=root.resolve("snapshot_2.xml");Files.writeString(snapshot,"admitted artifact");
        Path old=root.resolve("snapshot_1.xml");Files.writeString(old,"retained malformed old artifact");
        String request=root.resolve("request").toString();System.setProperty(ControlledRecovery.REQUEST_PROPERTY,request);
        blocked(()->ControlledRecovery.configurations());
        ConfigurationServiceImpl service=new ConfigurationServiceImpl();
        blocked(()->service.updateConfiguration("p",Map.of()));blocked(()->service.updateConfigurations(List.of(),false));
        blocked(()->service.updateRevision("p","0".repeat(64),Map.of()));
        blocked(()->service.createFactoryConfiguration("f","p",Map.of(),false));blocked(()->service.deleteFactoryConfiguration("p",false));
        blocked(()->service.snapshot());blocked(()->service.rollback());blocked(()->service.rollback(1));
        String sha=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(snapshot)));
        if(args.length>1 && args[1].equals("empty")) {
            String id="rec-11111111-1111-1111-1111-111111111111";
            blocked(()->ControlledRecovery.admit(request,id,snapshot,sha,List.of()));
            blocked(()->ControlledRecovery.admitCompensation(request,id,snapshot,"0".repeat(64),List.of()));
            ControlledRecovery.admitCompensation(request,id,snapshot,sha,List.of());
            if(!ControlledRecovery.configurations().orElseThrow().isEmpty()){throw new AssertionError();}
            var load=ConfigurationServiceImpl.class.getDeclaredMethod("loadLatestSnapshotConfigurations");load.setAccessible(true);
            if(!((List<?>)load.invoke(service)).isEmpty()){throw new AssertionError("empty inverse fell back");}
            blocked(()->ControlledRecovery.requireOrdinaryWrite());blocked(service::snapshot);
            blocked(()->ControlledRecovery.admitCompensation(request,id,snapshot,sha,List.of()));
            Files.writeString(root.resolve("snapshot_3.xml"),"unadmitted higher artifact");blocked(()->ControlledRecovery.configurations());
            if(!Files.readString(old).equals("retained malformed old artifact")){throw new AssertionError();}
            System.clearProperty(ControlledRecovery.REQUEST_PROPERTY);blocked(()->ControlledRecovery.configurations());
            blocked(()->ControlledRecovery.requireOrdinaryWrite());return;
        }
        String[] labels={"a","b"};Map<String,Object> values=new HashMap<>();values.put("labels",labels);values.put("password",new Password("canary"));
        Vector<Password> passwords=new Vector<>(List.of(new Password("vector-canary")));
        values.put("passwords",passwords);
        if (args.length>1 && args[1].equals("normal")) {
            ControlledRecovery.admitNormalLoad(request,"rec-11111111-1111-1111-1111-111111111111",snapshot,sha);
            if(ControlledRecovery.configurations().isPresent()){throw new AssertionError("normal path replaced");}
            var evidence=ControlledRecovery.evidence().orElseThrow();
            if(!evidence.normalLoad() || !evidence.snapshotSha256().equals(sha)
                    || !evidence.recoveryId().equals("rec-11111111-1111-1111-1111-111111111111")){throw new AssertionError();}
            blocked(()->ControlledRecovery.requireOrdinaryWrite());
            ControlledRecovery.verifySnapshotDirectory(root);
            blocked(()->ControlledRecovery.verifySnapshotDirectory(root.resolve("different-profile")));
            var system=org.mockito.Mockito.mock(org.eclipse.kura.system.SystemService.class);
            org.mockito.Mockito.when(system.getKuraSnapshotsDirectory()).thenReturn(root.toString());
            var props=new Properties();props.setProperty("kura.snapshots.encrypt","false");
            org.mockito.Mockito.when(system.getProperties()).thenReturn(props);service.setSystemService(system);
            // A missing decoder fails the actual ordinary-read branch without modifying either file.
            var load=ConfigurationServiceImpl.class.getDeclaredMethod("loadLatestSnapshotConfigurations");load.setAccessible(true);
            try {load.invoke(service);throw new AssertionError("malformed artifact admitted");}
            catch(java.lang.reflect.InvocationTargetException e){if(!(e.getCause() instanceof KuraException)){throw e;}}
            if(!Files.exists(snapshot)||Files.exists(Path.of(snapshot+".bad"))){throw new AssertionError("evidence moved");}
            Path empty=root.resolve("snapshot_0.xml");Files.createFile(empty);
            try {service.getSnapshots();throw new AssertionError("empty file silently deleted");}
            catch(IllegalStateException expected) {if(!Files.exists(empty)){throw new AssertionError();}}
            Files.writeString(root.resolve("snapshot_3.xml"),"higher");blocked(()->ControlledRecovery.configurations());
            System.clearProperty(ControlledRecovery.REQUEST_PROPERTY);blocked(()->ControlledRecovery.configurations());
            blocked(()->ControlledRecovery.requireOrdinaryWrite());return;
        }
        ControlledRecovery.admit(request,"rec-11111111-1111-1111-1111-111111111111",snapshot,sha,List.of(new ComponentConfigurationImpl("p",null,values)));
        labels[0]="external mutation";
        passwords.getFirst().getPassword()[0]='X';passwords.clear();
        var first=ControlledRecovery.configurations().orElseThrow();if(!((String[])first.getFirst().getConfigurationProperties().get("labels"))[0].equals("a")){throw new AssertionError();}
        var readPasswords=(Vector<?>)first.getFirst().getConfigurationProperties().get("passwords");
        if(readPasswords.size()!=1 || !readPasswords.getFirst().toString().equals("vector-canary")){throw new AssertionError("admission aliases collection");}
        ((Password)readPasswords.getFirst()).getPassword()[0]='X';readPasswords.clear();
        var reread=(Vector<?>)ControlledRecovery.configurations().orElseThrow().getFirst().getConfigurationProperties().get("passwords");
        if(reread.size()!=1 || !reread.getFirst().toString().equals("vector-canary")){throw new AssertionError("read aliases collection");}
        ((String[])first.getFirst().getConfigurationProperties().get("labels"))[0]="returned mutation";
        if(!((String[])ControlledRecovery.configurations().orElseThrow().getFirst().getConfigurationProperties().get("labels"))[0].equals("a")){throw new AssertionError();}
        blocked(()->ControlledRecovery.requireOrdinaryWrite());
        Files.writeString(root.resolve("snapshot_3.xml"),"unadmitted higher artifact");blocked(()->ControlledRecovery.configurations());
        if(!Files.readString(old).equals("retained malformed old artifact")){throw new AssertionError();}
        System.clearProperty(ControlledRecovery.REQUEST_PROPERTY);blocked(()->ControlledRecovery.configurations());blocked(()->ControlledRecovery.requireOrdinaryWrite());
    }
}
