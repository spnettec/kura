/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import org.eclipse.kura.core.configuration.ControlledRecovery;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.osgi.framework.BundleContext;

class RecoveryBootstrapTest {
    @TempDir Path directory;
    String valid() {
        return "schema=1\nrestore.id=rec-11111111-1111-1111-1111-111111111111\nsnapshot.path=/fixed/snapshot_2.xml\n"
                +"snapshot.sha256="+"0".repeat(64)+"\nsnapshot.mode=plain\npassword.policy=legacy\nreceipt.path=/fixed/result\ncrypto.default=true\n";
    }
    Path file(String content) throws Exception {
        Path path=directory.resolve("manifest-"+java.util.UUID.randomUUID());Files.writeString(path,content);
        Files.setPosixFilePermissions(path,PosixFilePermissions.fromString("rw-------"));return path;
    }
    @Test void defaultBundleDoesNothingAndNeverIntroducesAgentDependency() throws Exception {
        assertNull(System.getProperty(ControlledRecovery.REQUEST_PROPERTY));
        BundleContext context=mock(BundleContext.class);new RecoveryBootstrap().start(context);verifyNoInteractions(context);
    }
    @Test void malformedRecoveryHoldsBusinessBundlesAndStopsFrameworkInsteadOfFallingThrough() throws Exception {
        String prior=System.getProperty(ControlledRecovery.REQUEST_PROPERTY);
        System.setProperty(ControlledRecovery.REQUEST_PROPERTY,directory.resolve("missing-request").toString());
        try {
            BundleContext context=mock(BundleContext.class);
            org.osgi.framework.Bundle framework=mock(org.osgi.framework.Bundle.class), gate=mock(org.osgi.framework.Bundle.class);
            when(context.getBundle(0)).thenReturn(framework);when(context.getBundle()).thenReturn(gate);
            when(gate.getBundleId()).thenReturn(9L);
            var frameworkLevel=mock(org.osgi.framework.startlevel.FrameworkStartLevel.class);
            when(framework.adapt(org.osgi.framework.startlevel.FrameworkStartLevel.class)).thenReturn(frameworkLevel);
            when(frameworkLevel.getStartLevel()).thenReturn(1);when(context.getProperty("osgi.startLevel")).thenReturn("5");
            var scr=mock(org.osgi.framework.Bundle.class);when(scr.getBundleId()).thenReturn(1L);when(scr.getSymbolicName()).thenReturn("org.apache.felix.scr");
            var cm=mock(org.osgi.framework.Bundle.class);when(cm.getBundleId()).thenReturn(2L);when(cm.getSymbolicName()).thenReturn("org.eclipse.equinox.cm");
            var business=mock(org.osgi.framework.Bundle.class);when(business.getBundleId()).thenReturn(3L);when(business.getSymbolicName()).thenReturn("fixture.business");
            var scrLevel=mock(org.osgi.framework.startlevel.BundleStartLevel.class);when(scrLevel.getStartLevel()).thenReturn(1);when(scr.adapt(org.osgi.framework.startlevel.BundleStartLevel.class)).thenReturn(scrLevel);
            var cmLevel=mock(org.osgi.framework.startlevel.BundleStartLevel.class);when(cmLevel.getStartLevel()).thenReturn(5);when(cm.adapt(org.osgi.framework.startlevel.BundleStartLevel.class)).thenReturn(cmLevel);
            var businessLevel=mock(org.osgi.framework.startlevel.BundleStartLevel.class);when(businessLevel.getStartLevel()).thenReturn(5);when(business.adapt(org.osgi.framework.startlevel.BundleStartLevel.class)).thenReturn(businessLevel);
            when(context.getBundles()).thenReturn(new org.osgi.framework.Bundle[]{framework,gate,scr,cm,business});
            assertThrows(org.osgi.framework.BundleException.class,()->new RecoveryBootstrap().start(context));
            verify(businessLevel).setStartLevel(50);verify(scrLevel).setStartLevel(50);verify(businessLevel,never()).setStartLevel(5);
            verify(framework).stop();verify(context,never()).getServiceReference(org.osgi.service.cm.ConfigurationAdmin.class);
        } finally {if(prior==null){System.clearProperty(ControlledRecovery.REQUEST_PROPERTY);}else{System.setProperty(ControlledRecovery.REQUEST_PROPERTY,prior);}}
    }

    @Test void invalidTargetFencesLowLevelBusinessEvenWhenFrameworkCannotStopDuringInitialStart() throws Exception {
        String prior=System.getProperty(ControlledRecovery.REQUEST_PROPERTY);
        System.setProperty(ControlledRecovery.REQUEST_PROPERTY,directory.resolve("missing-request").toString());
        try {
            for(String target:new String[]{null,"4","unconfigured"}) {
                BundleContext context=mock(BundleContext.class);
                var framework=mock(org.osgi.framework.Bundle.class);var gate=mock(org.osgi.framework.Bundle.class);
                var business=mock(org.osgi.framework.Bundle.class);var scr=mock(org.osgi.framework.Bundle.class);
                when(gate.getBundleId()).thenReturn(9L);when(business.getBundleId()).thenReturn(2L);when(scr.getBundleId()).thenReturn(3L);
                when(business.getSymbolicName()).thenReturn("fixture.low.level.business");when(scr.getSymbolicName()).thenReturn("org.apache.felix.scr");
                when(business.getState()).thenReturn(org.osgi.framework.Bundle.ACTIVE);
                var businessLevel=mock(org.osgi.framework.startlevel.BundleStartLevel.class);
                var scrLevel=mock(org.osgi.framework.startlevel.BundleStartLevel.class);
                when(businessLevel.getStartLevel()).thenReturn(3);when(scrLevel.getStartLevel()).thenReturn(1);
                when(business.adapt(org.osgi.framework.startlevel.BundleStartLevel.class)).thenReturn(businessLevel);
                when(scr.adapt(org.osgi.framework.startlevel.BundleStartLevel.class)).thenReturn(scrLevel);
                when(context.getBundle(0)).thenReturn(framework);when(context.getBundle()).thenReturn(gate);
                when(context.getBundles()).thenReturn(new org.osgi.framework.Bundle[]{framework,gate,business,scr});
                when(context.getProperty("osgi.startLevel")).thenReturn(target);
                doThrow(new org.osgi.framework.BundleException("initial start still in progress")).when(framework).stop();
                assertThrows(org.osgi.framework.BundleException.class,()->new RecoveryBootstrap().start(context));
                verify(business).stop(org.osgi.framework.Bundle.STOP_TRANSIENT);
                verify(businessLevel).setStartLevel(50);verify(scrLevel).setStartLevel(50);
                verify(businessLevel,never()).setStartLevel(3);verify(scr,never()).start();
                verify(context,never()).getServiceReference(org.osgi.service.cm.ConfigurationAdmin.class);
            }
        } finally {if(prior==null){System.clearProperty(ControlledRecovery.REQUEST_PROPERTY);}else{System.setProperty(ControlledRecovery.REQUEST_PROPERTY,prior);}}
    }

    @Test void declaredFrameworkTargetSupportsTheCompleteLevelSixProfileWithoutAnImplicitDefault() {
        assertEquals(5,RecoveryBootstrap.startupTarget("5"));assertEquals(6,RecoveryBootstrap.startupTarget("6"));
        assertEquals(9,RecoveryBootstrap.startupTarget("9"));
        for(String value:new String[]{null,"","4","10","06","6 trailing"}) {
            assertThrows(Exception.class,()->RecoveryBootstrap.startupTarget(value));
        }
    }
    @Test void manifestRejectsDuplicateUnknownMissingAmbiguousAndUnprotectedInputs() throws Exception {
        assertEquals("1",RecoveryBootstrap.manifest(file(valid())).get("schema"));
        for(String content:java.util.List.of(valid()+"schema=1\n",valid()+"unknown=value\n",valid().replace("schema=1\n",""),
                valid()+"crypto.key.file=/key\n",valid().replace("crypto.default=true","crypto.default=false"),
                valid().replace("snapshot.mode=plain","snapshot.mode=auto"),valid().replace("restore.id=rec-","restore.id=oops-"))) {
            assertThrows(Exception.class,()->RecoveryBootstrap.manifest(file(content)));
        }
        Path permissive=file(valid());Files.setPosixFilePermissions(permissive,PosixFilePermissions.fromString("rw-r--r--"));
        assertThrows(Exception.class,()->RecoveryBootstrap.manifest(permissive));
        Path link=directory.resolve("link");Files.createSymbolicLink(link,file(valid()));
        assertThrows(Exception.class,()->RecoveryBootstrap.manifest(link));
    }
    String hash(byte[] bytes) throws Exception {return java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(bytes));}
    java.util.Map<String,String> compensationSource(org.eclipse.kura.core.crypto.CryptoServiceImpl crypto) throws Exception {
        return compensationSource(crypto,false);
    }
    java.util.Map<String,String> compensationSource(org.eclipse.kura.core.crypto.CryptoServiceImpl crypto, boolean empty) throws Exception {
        var old=new org.eclipse.kura.core.configuration.XmlComponentConfigurations();
        old.setConfigurations(empty ? java.util.List.of() : java.util.List.of(new org.eclipse.kura.core.configuration.ComponentConfigurationImpl("single",null,java.util.Map.of("kura.service.pid","single","count",9))));
        var next=new org.eclipse.kura.core.configuration.XmlComponentConfigurations();
        next.setConfigurations(java.util.List.of(new org.eclipse.kura.core.configuration.ComponentConfigurationImpl("single",null,java.util.Map.of("kura.service.pid","single","count",2,"password",new String(crypto.encryptAes("secret".toCharArray()))))));
        java.util.List<byte[]> data=new java.util.ArrayList<>();
        for(var value:java.util.List.of(old,next)) {
            var xml=new java.io.ByteArrayOutputStream();new org.eclipse.kura.internal.xml.marshaller.unmarshaller.XmlJavaComponentConfigurationsMapper(crypto).marshal(xml,value);
            var encrypted=new java.io.ByteArrayOutputStream();try(var out=crypto.aesEncryptingStream(encrypted)){xml.writeTo(out);}data.add(encrypted.toByteArray());
        }
        String id="rec-22222222-2222-2222-2222-222222222222";
        Path receipt=file("schema=1\nstatus=CM_APPLIED\nrestore.id="+id+"\nsnapshot.sha256="+"f".repeat(64)+"\nbackup.sha256="+hash(data.get(0))+"\n");
        Path backup=Path.of(receipt+".cm-backup.aes"),intent=Path.of(receipt+".cm-intended.aes"),plan=Path.of(receipt+".cm-plan.properties");
        Files.write(backup,data.get(0));Files.write(intent,data.get(1));Files.writeString(plan,"schema=1\nrestore.id="+id+"\nsnapshot.sha256="+"f".repeat(64)+"\nbackup.sha256="+hash(data.get(0))+"\nintended.sha256="+hash(data.get(1))+"\n");
        String request=valid().replace("snapshot.mode=plain","snapshot.mode=aes-gcm").replace("snapshot.sha256="+"0".repeat(64),"snapshot.sha256="+hash(data.get(0)))
                +"compensation.source.receipt="+receipt+"\ncompensation.source.receipt.sha256="+hash(Files.readAllBytes(receipt))+"\ncompensation.source.plan.sha256="+hash(Files.readAllBytes(plan))+"\n";
        return RecoveryBootstrap.manifest(file(request));
    }
    @Test void compensationUsesExactAuthenticatedCmIntentInsteadOfReencryptingPasswords() throws Exception {
        var crypto=org.eclipse.kura.core.crypto.CryptoServiceImpl.forSnapshotRecovery(null,true);
        var manifest=compensationSource(crypto);var values=RecoveryBootstrap.compensationIntent(manifest,crypto);
        assertEquals(2,values.getFirst().getConfigurationProperties().get("count"));
        Object encrypted=values.getFirst().getConfigurationProperties().get("password");assertInstanceOf(String.class,encrypted);
        assertArrayEquals("secret".toCharArray(),crypto.decryptAes(((String)encrypted).toCharArray()));
        assertNull(RecoveryBootstrap.compensationIntent(java.util.Map.of(),crypto));
    }
    @Test void authenticatedEmptyOriginalBackupRemainsRejectedAsAnOrdinaryUpload() throws Exception {
        var crypto=org.eclipse.kura.core.crypto.CryptoServiceImpl.forSnapshotRecovery(null,true);
        var manifest=compensationSource(crypto,true);
        assertFalse(RecoveryBootstrap.compensationIntent(manifest,crypto).isEmpty());
        byte[] xml;
        try(var input=crypto.aesDecryptingStream(Files.newInputStream(Path.of(manifest.get("compensation.source.receipt")+".cm-backup.aes")))) {
            xml=input.readAllBytes();
        }
        try {
            assertThrows(Exception.class,()->SnapshotTool.decode(xml,crypto,"authenticated"));
            assertThrows(Exception.class,()->SnapshotTool.decode(xml,crypto,"legacy"));
            var retained=SnapshotTool.decodeRetainedCmBackup(xml,crypto,"authenticated");
            assertTrue(retained.configurations().isEmpty());
            assertTrue(org.eclipse.kura.core.configuration.ConfigurationRestore.expected(retained.configurations()).isEmpty());
            var admin=mock(org.osgi.service.cm.ConfigurationAdmin.class);
            assertThrows(Exception.class,()->org.eclipse.kura.core.configuration.ConfigurationRestore.apply(admin,retained.configurations(),ignored->fail("ordinary empty target reached backup")));
            verifyNoInteractions(admin);
        } finally {java.util.Arrays.fill(xml,(byte)0);}
    }
    @Test void compensationRejectsDriftWrongKeyWrongTargetAndIncompleteGrant() throws Exception {
        var crypto=org.eclipse.kura.core.crypto.CryptoServiceImpl.forSnapshotRecovery(null,true);
        for(String suffix:java.util.List.of("", ".cm-plan.properties", ".cm-intended.aes", ".cm-backup.aes")) {
            var manifest=compensationSource(crypto);Path path=Path.of(manifest.get("compensation.source.receipt")+suffix);Files.writeString(path,"drift");
            assertThrows(Exception.class,()->RecoveryBootstrap.compensationIntent(manifest,crypto));
        }
        var manifest=compensationSource(crypto);
        var other=org.eclipse.kura.core.crypto.CryptoServiceImpl.forSnapshotRecovery("0123456789abcdef".getBytes(java.nio.charset.StandardCharsets.UTF_8),false);
        assertThrows(Exception.class,()->RecoveryBootstrap.compensationIntent(manifest,other));
        var changed=new java.util.HashMap<>(manifest);changed.put("snapshot.sha256","a".repeat(64));
        assertThrows(Exception.class,()->RecoveryBootstrap.compensationIntent(changed,crypto));
        assertThrows(Exception.class,()->RecoveryBootstrap.manifest(file(valid()+"compensation.source.receipt=/partial\n")));
    }

    java.util.Map<String,String> normalSource(org.eclipse.kura.core.crypto.CryptoServiceImpl crypto) throws Exception {
        var prior=compensationSource(crypto);
        byte[] cm=Files.readAllBytes(Path.of(prior.get("compensation.source.receipt")+".cm-intended.aes"));
        Path source=file("schema=1\nstatus=CM_APPLIED\nrestore.id=rec-33333333-3333-3333-3333-333333333333\n"
                +"applied.sha256="+hash(cm)+"\nfullRecoveryVerified=false\nbusinessHealth=UNVERIFIED\n");
        Files.write(Path.of(source+".cm-applied.aes"),cm);
        return RecoveryBootstrap.manifest(file(valid()+"verification.mode=normal-read-only\nverification.source.receipt="+source
                +"\nverification.source.receipt.sha256="+hash(Files.readAllBytes(source))
                +"\nverification.source.applied.sha256="+hash(cm)+"\n"));
    }
    @Test void normalSourceAuthenticatesExactCmWithoutApplyingOrReencryptingIt() throws Exception {
        var crypto=org.eclipse.kura.core.crypto.CryptoServiceImpl.forSnapshotRecovery(null,true);
        var manifest=normalSource(crypto);var values=RecoveryBootstrap.normalLoadSource(manifest,crypto,false);
        assertEquals(2,values.getFirst().getConfigurationProperties().get("count"));
        assertInstanceOf(String.class,values.getFirst().getConfigurationProperties().get("password"));
        var admin=mock(org.osgi.service.cm.ConfigurationAdmin.class);
        assertThrows(Exception.class,()->org.eclipse.kura.core.configuration.ConfigurationRestore.verify(admin,values));
        verify(admin).listConfigurations(null);verifyNoMoreInteractions(admin);
        for(String suffix:java.util.List.of("", ".cm-applied.aes")) {
            var changed=normalSource(crypto);Files.writeString(Path.of(changed.get("verification.source.receipt")+suffix),"drift");
            assertThrows(Exception.class,()->RecoveryBootstrap.normalLoadSource(changed,crypto,false));
        }
        var other=org.eclipse.kura.core.crypto.CryptoServiceImpl.forSnapshotRecovery("0123456789abcdef".getBytes(),false);
        assertThrows(Exception.class,()->RecoveryBootstrap.normalLoadSource(manifest,other,false));
    }
    @Test void fixedGuardedLoadRequiresOriginalRestoreAndSnapshot() throws Exception {
        var crypto=org.eclipse.kura.core.crypto.CryptoServiceImpl.forSnapshotRecovery(null,true);
        var manifest=normalSource(crypto);
        var source=Path.of(manifest.get("verification.source.receipt"));
        Files.writeString(source,"snapshot.sha256="+manifest.get("snapshot.sha256")+"\n",
                java.nio.file.StandardOpenOption.APPEND);
        var fixed=new java.util.HashMap<>(manifest);
        fixed.put("restore.id","rec-33333333-3333-3333-3333-333333333333");
        fixed.put("verification.source.receipt.sha256",hash(Files.readAllBytes(source)));
        assertFalse(RecoveryBootstrap.normalLoadSource(fixed,crypto,true).isEmpty());
        assertThrows(Exception.class,()->RecoveryBootstrap.normalLoadSource(fixed,crypto,false));
        var changed=new java.util.HashMap<>(fixed);
        changed.put("snapshot.sha256","f".repeat(64));
        assertThrows(Exception.class,()->RecoveryBootstrap.normalLoadSource(changed,crypto,true));
        changed.put("snapshot.sha256",fixed.get("snapshot.sha256"));
        changed.put("restore.id",manifest.get("restore.id"));
        assertThrows(Exception.class,()->RecoveryBootstrap.normalLoadSource(changed,crypto,true));
    }
    @Test void normalManifestCannotMixCompensationOrAdmitPartialUnknownSource() throws Exception {
        var crypto=org.eclipse.kura.core.crypto.CryptoServiceImpl.forSnapshotRecovery(null,true);
        var manifest=normalSource(crypto);
        for(String key:java.util.List.of("verification.mode","verification.source.receipt","verification.source.receipt.sha256","verification.source.applied.sha256")) {
            var changed=new java.util.TreeMap<>(manifest);changed.remove(key);
            StringBuilder request=new StringBuilder();changed.forEach((k,v)->request.append(k).append('=').append(v).append('\n'));
            assertThrows(Exception.class,()->RecoveryBootstrap.manifest(file(request.toString())));
        }
        StringBuilder request=new StringBuilder();manifest.forEach((k,v)->request.append(k).append('=').append(v).append('\n'));
        assertThrows(Exception.class,()->RecoveryBootstrap.manifest(file(request+"compensation.source.receipt=/fixed/source\n")));
        assertThrows(Exception.class,()->RecoveryBootstrap.manifest(file(request.toString().replace("normal-read-only","normal"))));
    }

}
