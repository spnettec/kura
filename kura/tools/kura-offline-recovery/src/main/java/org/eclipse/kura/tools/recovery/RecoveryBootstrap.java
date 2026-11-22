/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.nio.file.attribute.PosixFileAttributes;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.configuration.ConfigurationRestore;
import org.eclipse.kura.core.configuration.ControlledRecovery;
import org.eclipse.kura.core.configuration.XmlComponentConfigurations;
import org.eclipse.kura.core.configuration.util.ComponentUtil;
import org.eclipse.kura.core.crypto.CryptoServiceImpl;
import org.eclipse.kura.internal.xml.marshaller.unmarshaller.XmlJavaComponentConfigurationsMapper;
import org.osgi.framework.Bundle;
import org.osgi.framework.BundleActivator;
import org.osgi.framework.BundleContext;
import org.osgi.framework.BundleException;
import org.osgi.framework.startlevel.BundleStartLevel;
import org.osgi.framework.startlevel.FrameworkStartLevel;
import org.osgi.service.cm.ConfigurationAdmin;

/** Optional in-framework gate. Standalone validate never starts this or any OSGi framework. */
public final class RecoveryBootstrap implements BundleActivator {
    private static final Path CORE_PROJECTIONS = Path.of("/var/lib/kura-recovery-launch");
    private static final Path CORE_SNAPSHOTS = Path.of("/opt/eclipse/kura/user/snapshots");
    private RecoveryVerifier verifier;
    private org.osgi.framework.ServiceRegistration<org.eclipse.kura.configuration.RecoveryVerificationService> verificationRegistration;
    private org.osgi.framework.ServiceRegistration<org.eclipse.kura.configuration.RecoveryCompletionService> completionRegistration;
    @Override public void start(BundleContext context) throws Exception {
        String request = System.getProperty(ControlledRecovery.REQUEST_PROPERTY);
        if (request == null) { return; }
        Path receipt = null;
        Map<String,String> manifest = null;
        try {
            Set<String> infrastructure=Set.of("org.eclipse.equinox.cm", "org.apache.aries.spifly.dynamic.bundle",
                    "org.apache.logging.log4j.core", "org.apache.logging.log4j.slf4j2.impl",
                    "org.apache.logging.log4j.api", "slf4j.api");
            Map<Bundle,Integer> held = new java.util.LinkedHashMap<>();
            for (Bundle candidate : context.getBundles()) {
                if (candidate.getBundleId()!=0 && candidate!=context.getBundle()
                        && !infrastructure.contains(String.valueOf(candidate.getSymbolicName()))) {
                    BundleStartLevel start=candidate.adapt(BundleStartLevel.class);
                    if (start!=null) {
                        held.put(candidate,start.getStartLevel());
                        if (candidate.getState()==Bundle.ACTIVE || candidate.getState()==Bundle.STARTING) {
                            candidate.stop(Bundle.STOP_TRANSIENT);
                        }
                        start.setStartLevel(50);
                    }
                }
            }
            // Fence first: stopping a framework while its initial start is still
            // in progress does not prevent the launcher from advancing it later.
            var level = context.getBundle(0).adapt(FrameworkStartLevel.class);
            int frameworkTarget=startupTarget(context.getProperty("osgi.startLevel"));
            require(level.getStartLevel() <= 1);
            Bundle scr = bundle(context,"org.apache.felix.scr");
            scr.start(); // Persist intended autostart, held above the launcher's target level.
            for (Bundle candidate : context.getBundles()) {
                if (candidate.getBundleId()!=0 && candidate!=context.getBundle() && candidate.getState()==Bundle.ACTIVE) {
                    require(infrastructure.contains(candidate.getSymbolicName()));
                }
            }
            // External authority must be injected from current Rust revision, not an old Kura snapshot.
            // Until that adapter is wired, reject the profile rather than replaying or silently skipping it.
            require(System.getProperty("kura.configuration.external.pids", "").isBlank());
            Path requestPath = Path.of(request);
            manifest = manifest(requestPath);
            boolean fixedGuarded = requestPath.startsWith(CORE_PROJECTIONS) && manifest.containsKey("verification.mode");
            require(!fixedGuarded || "false".equals(context.getProperty("osgi.clean")));
            receipt = Path.of(manifest.get("receipt.path"));
            privateParent(receipt);
            require(!Files.exists(receipt,LinkOption.NOFOLLOW_LINKS)); // Never replay a retained decision.
            StringBuilder ledger=new StringBuilder("schema=1\n");
            for(var entry:held.entrySet()) { ledger.append(entry.getKey().getBundleId()).append('=').append(entry.getValue()).append('\n'); }
            publish(receipt.resolveSibling(receipt.getFileName()+".bundle-levels"),ledger.toString().getBytes(StandardCharsets.UTF_8));
            // Start only logging/SPI infrastructure before touching classes with static loggers.
            // It is independent of SCR/business and prevents a permanently cached NOP provider.
            for(String name:List.of("org.apache.aries.spifly.dynamic.bundle","org.apache.logging.log4j.core",
                    "org.apache.logging.log4j.slf4j2.impl","org.apache.logging.log4j.api","slf4j.api")) {
                Bundle logging=bundle(context,name);logging.adapt(BundleStartLevel.class).setStartLevel(1);
                if(logging.getState()!=Bundle.ACTIVE){logging.start(Bundle.START_TRANSIENT);}
            }

            Path snapshot=Path.of(manifest.get("snapshot.path"));
            privateParent(snapshot);
            // A published import may have been converted into the directory's own format;
            // the boot then reads that artifact while receipts keep the source lineage digest.
            String publishedSha=manifest.getOrDefault("snapshot.published.sha256",manifest.get("snapshot.sha256"));
            String publishedMode=manifest.getOrDefault("snapshot.published.mode",manifest.get("snapshot.mode"));
            ControlledRecovery.verifyArtifact(snapshot,publishedSha);
            byte[] artifact=read(snapshot,32<<20);
            require(hash(artifact).equals(publishedSha));
            CryptoServiceImpl crypto=recoveryCrypto(manifest);
            byte[] xml=artifact;
            if(publishedMode.equals("aes-gcm")) {
                try(InputStream input=crypto.aesDecryptingStream(new ByteArrayInputStream(artifact))){
                    xml=input.readNBytes((32<<20)+1);require(xml.length<=32<<20);
                }
            }
            List<ComponentConfiguration> target;
            List<ComponentConfiguration> previousIntent;
            try {
                previousIntent=compensationIntent(manifest,crypto);
                // Empty targets are exclusively the authenticated original CM backup of an inverse.
                var decoded=previousIntent==null ? (manifest.get("snapshot.mode").equals("aes-gcm")
                        ? SnapshotTool.decodeAuthenticatedArtifact(xml,crypto,manifest.get("password.policy"))
                        : SnapshotTool.decode(xml,crypto,manifest.get("password.policy")))
                        : SnapshotTool.decodeRetainedCmBackup(xml,crypto,manifest.get("password.policy"));
                target=new ArrayList<>();
                for(var configuration:decoded.configurations()) {
                    target.add(new ComponentConfigurationImpl(configuration.getPid(),null,targetProperties(configuration,crypto)));
                }
            } finally { Arrays.fill(xml,(byte)0);Arrays.fill(artifact,(byte)0); }
            Bundle cm=bundle(context,"org.eclipse.equinox.cm");
            cm.adapt(BundleStartLevel.class).setStartLevel(1);
            if(cm.getState()!=Bundle.ACTIVE){cm.start(Bundle.START_TRANSIENT);}
            var reference=context.getServiceReference(ConfigurationAdmin.class);
            require(reference!=null);
            ConfigurationAdmin admin=context.getService(reference);require(admin!=null);
            if (manifest.containsKey("verification.mode")) {
                try {
                    var verificationExpected=normalLoadSource(manifest,crypto,fixedGuarded);
                    ConfigurationRestore.verify(admin,verificationExpected);
                    Path observed=receipt.resolveSibling(receipt.getFileName()+".cm-observed.aes");
                    backup(observed,ConfigurationRestore.capture(admin),crypto);
                    ControlledRecovery.admitNormalLoad(request,manifest.get("restore.id"),snapshot,manifest.get("snapshot.sha256"));
                    publish(receipt,("schema=1\nstatus=NORMAL_BOOT_ADMITTED\nrestore.id="+manifest.get("restore.id")
                            +"\nsnapshot.sha256="+manifest.get("snapshot.sha256")
                            +"\nsource.receipt.sha256="+manifest.get("verification.source.receipt.sha256")
                            +"\nsource.applied.sha256="+manifest.get("verification.source.applied.sha256")
                            +"\nobserved.sha256="+hash(read(observed,32<<20))
                            +"\nfullRecoveryVerified=false\nnormalBootVerified=false\nbusinessHealth=UNVERIFIED\n")
                            .getBytes(StandardCharsets.UTF_8));
                    this.verifier=new RecoveryVerifier(context,verificationExpected);
                    this.verificationRegistration=context.registerService(
                            org.eclipse.kura.configuration.RecoveryVerificationService.class,this.verifier,null);
                    String completionPolicy=System.getProperty("kura.management.recovery.completion.enabled","false");
                    require(completionPolicy.equals("true") || completionPolicy.equals("false"));
                    if(completionPolicy.equals("true")) {
                        this.completionRegistration=context.registerService(
                                org.eclipse.kura.configuration.RecoveryCompletionService.class,
                                new RecoveryWriteRelease(this.verifier,receipt,frameworkTarget,fixedGuarded),null);
                    }
                } finally { context.ungetService(reference); }
            } else {
                Path backup=receipt.resolveSibling(receipt.getFileName()+".cm-backup.aes");
                ConfigurationRestore.Applied result;
                List<ComponentConfiguration> appliedConfigurations;
                Path applied=receipt.resolveSibling(receipt.getFileName()+".cm-applied.aes");
                Path intended=receipt.resolveSibling(receipt.getFileName()+".cm-intended.aes");
                Path plan=receipt.resolveSibling(receipt.getFileName()+".cm-plan.properties");
                backup(intended,ConfigurationRestore.expected(target),crypto);
                final Map<String,String> admittedManifest=manifest;
                try {
                    ConfigurationRestore.Backup checkpoint=old->{
                        backup(backup,old,crypto);
                        // A durable pre-mutation anchor also survives partial CM failure or process death.
                        publish(plan,("schema=1\nrestore.id="+admittedManifest.get("restore.id")
                                +"\nsnapshot.sha256="+admittedManifest.get("snapshot.sha256")
                                +"\nbackup.sha256="+hash(read(backup,64<<20))
                                +"\nintended.sha256="+hash(read(intended,64<<20))+"\n").getBytes(StandardCharsets.UTF_8));
                    };
                    result=previousIntent==null ? ConfigurationRestore.apply(admin,target,checkpoint)
                            : ConfigurationRestore.compensate(admin,target,previousIntent,checkpoint);
                    // Persist the exact CM representation, including randomized password ciphertext.
                    // Re-decoding/re-encrypting the source snapshot cannot reconstruct these bytes.
                    appliedConfigurations = ConfigurationRestore.capture(admin);
                    backup(applied,appliedConfigurations,crypto);
                } finally { context.ungetService(reference); }
                if(previousIntent==null) {
                    ControlledRecovery.admit(request,manifest.get("restore.id"),snapshot,manifest.get("snapshot.sha256"),target);
                } else {
                    ControlledRecovery.admitCompensation(request,manifest.get("restore.id"),snapshot,manifest.get("snapshot.sha256"),target);
                }
                String report="schema=1\nstatus=CM_APPLIED\nrestore.id="+manifest.get("restore.id")
                        +"\nsnapshot.sha256="+manifest.get("snapshot.sha256")
                        +"\nfullRecoveryVerified=false\nbusinessHealth=UNVERIFIED\nbackup.sha256="+hash(read(backup,64<<20))
                        +"\napplied.sha256="+hash(read(applied,64<<20))+"\n";
                report+=actions("replaced",result.replaced())+actions("created",result.created())+actions("deleted",result.deleted());
                publish(receipt,report.getBytes(StandardCharsets.UTF_8));
                if (previousIntent == null && Path.of(request).startsWith(CORE_PROJECTIONS)) {
                    this.verifier = new RecoveryVerifier(context, appliedConfigurations, false);
                    this.verificationRegistration = context.registerService(
                            org.eclipse.kura.configuration.RecoveryVerificationService.class, this.verifier, null);
                }
            }
            // Only the CM application decision is durable. Agent still must verify bridge/business and finalize.
            // The launcher owns the framework transition to the explicitly declared target.
            for(var entry:held.entrySet()) {
                if(!infrastructure.contains(entry.getKey().getSymbolicName())) {
                    entry.getKey().adapt(BundleStartLevel.class).setStartLevel(entry.getKey()==scr ? frameworkTarget : entry.getValue());
                }
            }
        } catch(Exception | LinkageError failure) {
            if(receipt!=null && manifest!=null && !Files.exists(receipt,LinkOption.NOFOLLOW_LINKS)) {
                try { publish(receipt,("schema=1\nstatus=RECOVERY_REQUIRED\nrestore.id="+manifest.get("restore.id")
                        +"\nfullRecoveryVerified=false\nbusinessHealth=BLOCKED\n").getBytes(StandardCharsets.UTF_8)); }
                catch(Exception ignored) { /* Preserve original request and state. No fallback or cleanup. */ }
            }
            // A startup error must not let the standard launcher activate any unheld business bundle.
            try { context.getBundle(0).stop(); } catch(Exception ignored) { }
            // Do not attach parser/crypto exception messages to framework logs.
            throw new BundleException("Controlled recovery failed; business start level remains blocked");
        }
    }

    static int startupTarget(String value) {
        require(value!=null && value.matches("[5-9]"));
        return Integer.parseInt(value);
    }
    @Override public void stop(BundleContext context) {
        if(this.completionRegistration!=null){this.completionRegistration.unregister();}
        if(this.verificationRegistration!=null){this.verificationRegistration.unregister();}
        if(this.verifier!=null){this.verifier.close();}
        // No implicit acknowledgement or state clearing.
    }

    private static String actions(String kind,List<String> pids) {
        StringBuilder result=new StringBuilder(kind+".count="+pids.size()+"\n");
        for(int i=0;i<pids.size();i++){
            result.append(kind).append('.').append(i).append('=').append(java.util.Base64.getEncoder()
                    .encodeToString(pids.get(i).getBytes(StandardCharsets.UTF_8))).append('\n');
        }
        return result.toString();
    }
    private static void backup(Path path,List<ComponentConfiguration> old,CryptoServiceImpl crypto) throws Exception {
        XmlComponentConfigurations values=new XmlComponentConfigurations();values.setConfigurations(old);
        BoundedOutput xml=new BoundedOutput(),encrypted=new BoundedOutput();
        try {
            new XmlJavaComponentConfigurationsMapper(crypto).marshal(xml,values);
            try(var output=crypto.aesEncryptingStream(encrypted)){xml.writeTo(output);}
            // Also bounded by the offline reader's artifact limit, so every backup is consumable.
            // This is our encrypted API-level backup, never CM's private database layout.
            publish(path,encrypted.toByteArray());
        } finally {xml.wipe();encrypted.wipe();}
    }
    private static final class BoundedOutput extends ByteArrayOutputStream {
        @Override public synchronized void write(int value) {
            require(size()<(32<<20));super.write(value);
        }
        @Override public synchronized void write(byte[] value,int offset,int length) {
            require(length<=(32<<20)-size());super.write(value,offset,length);
        }
        void wipe(){Arrays.fill(this.buf,(byte)0);reset();}
    }
    private static Bundle bundle(BundleContext context,String name) {
        List<Bundle> found=Arrays.stream(context.getBundles()).filter(b->name.equals(b.getSymbolicName())).toList();
        require(found.size()==1);return found.getFirst();
    }
    static List<ComponentConfiguration> compensationIntent(Map<String,String> manifest,CryptoServiceImpl crypto)
            throws Exception {
        String source=manifest.get("compensation.source.receipt");
        if(source==null){return null;}
        require("aes-gcm".equals(manifest.get("snapshot.mode")));
        Path receipt=Path.of(source);privateParent(receipt);
        byte[] receiptBytes=read(receipt,1<<20);
        require(hash(receiptBytes).equals(manifest.get("compensation.source.receipt.sha256")));
        Map<String,String> decision=properties(receiptBytes);
        require("1".equals(decision.get("schema")) && Set.of("CM_APPLIED","RECOVERY_REQUIRED").contains(decision.get("status")));
        Path plan=receipt.resolveSibling(receipt.getFileName()+".cm-plan.properties");
        byte[] planBytes=read(plan,4096);
        require(hash(planBytes).equals(manifest.get("compensation.source.plan.sha256")));
        Map<String,String> anchor=properties(planBytes);
        require(anchor.keySet().equals(Set.of("schema","restore.id","snapshot.sha256","backup.sha256","intended.sha256"))
                && "1".equals(anchor.get("schema")) && anchor.get("restore.id").matches("rec-[0-9a-f-]{36}")
                && anchor.get("restore.id").equals(decision.get("restore.id"))
                && !anchor.get("restore.id").equals(manifest.get("restore.id"))
                && anchor.get("snapshot.sha256").matches("[0-9a-f]{64}")
                && anchor.get("backup.sha256").equals(manifest.get("snapshot.sha256"))
                && anchor.get("intended.sha256").matches("[0-9a-f]{64}"));
        if("CM_APPLIED".equals(decision.get("status"))) {
            require(anchor.get("snapshot.sha256").equals(decision.get("snapshot.sha256"))
                    && anchor.get("backup.sha256").equals(decision.get("backup.sha256")));
        }
        Path backup=receipt.resolveSibling(receipt.getFileName()+".cm-backup.aes");
        require(hash(read(backup,32<<20)).equals(anchor.get("backup.sha256")));
        byte[] intended=read(receipt.resolveSibling(receipt.getFileName()+".cm-intended.aes"),32<<20);
        require(hash(intended).equals(anchor.get("intended.sha256")));
        byte[] xml;
        try(InputStream input=crypto.aesDecryptingStream(new ByteArrayInputStream(intended))){
            xml=input.readNBytes((32<<20)+1);require(xml.length<=32<<20);
        } finally {Arrays.fill(intended,(byte)0);}
        try { return SnapshotTool.decode(xml,crypto,"authenticated").configurations(); }
        finally {Arrays.fill(xml,(byte)0);}
    }
    /** Authenticate the exact restored CM before SCR or any business bundle can run. */
    static List<ComponentConfiguration> normalLoadSource(Map<String,String> manifest,CryptoServiceImpl crypto,
            boolean fixedGuarded)
            throws Exception {
        require("normal-read-only".equals(manifest.get("verification.mode")));
        Path source=Path.of(manifest.get("verification.source.receipt"));privateParent(source);
        byte[] receipt=read(source,1<<20);
        require(hash(receipt).equals(manifest.get("verification.source.receipt.sha256")));
        Map<String,String> decision=properties(receipt);
        require("1".equals(decision.get("schema")) && "CM_APPLIED".equals(decision.get("status"))
                && "false".equals(decision.get("fullRecoveryVerified"))
                && "UNVERIFIED".equals(decision.get("businessHealth"))
                && decision.get("restore.id").matches("rec-[0-9a-f-]{36}")
                && manifest.get("verification.source.applied.sha256").equals(decision.get("applied.sha256")));
        if (fixedGuarded) {
            require(manifest.get("restore.id").equals(decision.get("restore.id"))
                    && manifest.get("snapshot.sha256").equals(decision.get("snapshot.sha256")));
        } else {
            require(!manifest.get("restore.id").equals(decision.get("restore.id")));
        }
        byte[] encrypted=read(source.resolveSibling(source.getFileName()+".cm-applied.aes"),32<<20);
        require(hash(encrypted).equals(manifest.get("verification.source.applied.sha256")));
        byte[] xml;
        try(InputStream input=crypto.aesDecryptingStream(new ByteArrayInputStream(encrypted))){
            xml=input.readNBytes((32<<20)+1);require(xml.length<=32<<20);
        } finally { Arrays.fill(encrypted,(byte)0); }
        try { return SnapshotTool.decode(xml,crypto,"authenticated").configurations(); }
        finally { Arrays.fill(xml,(byte)0); }
    }
    static Map<String,String> properties(byte[] bytes) {
        Map<String,String> result=new HashMap<>();
        for(String line:new String(bytes,StandardCharsets.UTF_8).split("\\n")) {
            if(line.isEmpty()){continue;}
            int equals=line.indexOf('=');require(equals>0);
            String key=line.substring(0,equals),value=line.substring(equals+1);
            require(!value.isEmpty() && value.chars().noneMatch(Character::isISOControl)
                    && result.putIfAbsent(key,value)==null);
        }
        return result;
    }
    static Map<String,String> manifest(Path path) throws Exception {
        boolean projection = path.startsWith(CORE_PROJECTIONS);
        boolean guarded = projection && path.getNameCount() == CORE_PROJECTIONS.getNameCount() + 3
                && path.getParent().getFileName().toString().equals("guarded");
        if (projection) {
            require(path.equals(path.normalize()) && (guarded || path.getNameCount() == CORE_PROJECTIONS.getNameCount() + 2)
                    && path.getFileName().toString().equals("request.properties"));
            projected(CORE_PROJECTIONS, true);
            if (guarded) { projected(path.getParent().getParent(), true); }
            projected(path.getParent(), true);
            projected(path, false);
        } else {
            require(Files.getPosixFilePermissions(path,LinkOption.NOFOLLOW_LINKS)
                    .stream().noneMatch(p->p.name().startsWith("GROUP")||p.name().startsWith("OTHERS")));
        }
        byte[] bytes=read(path,16*1024);
        privateParent(path);
        Map<String,String> result=new HashMap<>();
        for(String line:new String(bytes,StandardCharsets.UTF_8).split("\\n")) {
            if(line.isEmpty()){continue;}
            int equals=line.indexOf('=');require(equals>0);
            String key=line.substring(0,equals),value=line.substring(equals+1);
            require(!value.isEmpty() && value.chars().noneMatch(Character::isISOControl)
                    && result.putIfAbsent(key,value)==null);
        }
        Set<String> required=Set.of("schema","restore.id","snapshot.path","snapshot.sha256","snapshot.mode","password.policy","receipt.path");
        Set<String> allowed=new HashSet<>(required);allowed.addAll(Set.of("crypto.key.file","crypto.default",
                "crypto.keyring.file","crypto.keyring.sha256","crypto.systemd.credentials",
                "crypto.key.sha256","crypto.ring.sha256"));
        Set<String> compensation=Set.of("compensation.source.receipt","compensation.source.receipt.sha256","compensation.source.plan.sha256");
        allowed.addAll(compensation);
        Set<String> normal=Set.of("verification.mode","verification.source.receipt",
                "verification.source.receipt.sha256","verification.source.applied.sha256");
        allowed.addAll(normal);
        Set<String> published=Set.of("snapshot.published.sha256","snapshot.published.mode");
        allowed.addAll(published);
        require(result.keySet().containsAll(required)&&allowed.containsAll(result.keySet())&&result.get("schema").equals("1")
                &&result.get("restore.id").matches("rec-[0-9a-f-]{36}")&&result.get("snapshot.sha256").matches("[0-9a-f]{64}")
                &&Set.of("plain","aes-gcm").contains(result.get("snapshot.mode"))
                &&Set.of("authenticated","legacy","logical-v1").contains(result.get("password.policy"))
                &&(result.containsKey("crypto.key.file") ? 1 : 0)+(result.containsKey("crypto.default") ? 1 : 0)
                        +(result.containsKey("crypto.keyring.file") ? 1 : 0)
                        +(result.containsKey("crypto.systemd.credentials") ? 1 : 0)==1
                &&result.containsKey("crypto.keyring.file")==result.containsKey("crypto.keyring.sha256"));
        boolean managed=result.containsKey("crypto.systemd.credentials");
        require(managed==result.containsKey("crypto.key.sha256") && managed==result.containsKey("crypto.ring.sha256"));
        if(managed) {
            require("true".equals(result.get("crypto.systemd.credentials"))
                    &&result.get("crypto.key.sha256").matches("[0-9a-f]{64}")
                    &&(result.get("crypto.ring.sha256").equals("none")
                        ||result.get("crypto.ring.sha256").matches("[0-9a-f]{64}")));
        }
        if(result.containsKey("crypto.keyring.file")) {
            require(Path.of(result.get("crypto.keyring.file")).isAbsolute()
                    &&result.get("crypto.keyring.sha256").matches("[0-9a-f]{64}"));
        }
        if(result.containsKey("crypto.default")){require(result.get("crypto.default").equals("true"));}
        if(compensation.stream().anyMatch(result::containsKey)) {
            require(result.keySet().containsAll(compensation)
                    && result.get("compensation.source.receipt.sha256").matches("[0-9a-f]{64}")
                    && result.get("compensation.source.plan.sha256").matches("[0-9a-f]{64}"));
        }
        if(normal.stream().anyMatch(result::containsKey)) {
            require(result.keySet().containsAll(normal) && compensation.stream().noneMatch(result::containsKey)
                    && "normal-read-only".equals(result.get("verification.mode"))
                    && Path.of(result.get("verification.source.receipt")).isAbsolute()
                    && !result.get("verification.source.receipt").equals(result.get("receipt.path"))
                    && result.get("verification.source.receipt.sha256").matches("[0-9a-f]{64}")
                    && result.get("verification.source.applied.sha256").matches("[0-9a-f]{64}"));
        }
        if(published.stream().anyMatch(result::containsKey)) {
            require(normal.stream().allMatch(result::containsKey)
                    && result.keySet().containsAll(published)
                    && result.get("snapshot.published.sha256").matches("[0-9a-f]{64}")
                    && Set.of("plain","aes-gcm").contains(result.get("snapshot.published.mode")));
        }
        if (projection) {
            Path directory = path.getParent();
            Path original = guarded ? directory.getParent() : directory;
            require(managed && result.get("restore.id").equals(original.getFileName().toString())
                    && compensation.stream().noneMatch(result::containsKey));
            if (guarded) {
                Path snapshot = Path.of(result.get("snapshot.path"));
                require(result.keySet().containsAll(normal) && snapshot.equals(snapshot.normalize())
                        && CORE_SNAPSHOTS.equals(snapshot.getParent())
                        && snapshot.getFileName().toString().matches("snapshot_(0|[1-9][0-9]{0,18})\\.xml")
                        && result.get("receipt.path").equals(directory.resolve("result/normal.properties").toString())
                        && result.get("verification.source.receipt").equals(original.resolve("result/applied.properties").toString()));
            } else {
                Path snapshot = directory.resolve("snapshot_0.xml");
                require(result.get("snapshot.path").equals(snapshot.toString())
                        && result.get("receipt.path").equals(directory.resolve("result/applied.properties").toString())
                        && normal.stream().noneMatch(result::containsKey));
                projected(snapshot, false);
            }
        }
        return result;
    }

    static void projected(Path path, boolean directory) throws Exception {
        var attributes = Files.readAttributes(path, PosixFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
        require((directory ? attributes.isDirectory() : attributes.isRegularFile())
                && Files.getAttribute(path, "unix:uid", LinkOption.NOFOLLOW_LINKS).equals(0)
                && attributes.group().getName().equals("kurad")
                && attributes.permissions().equals(PosixFilePermissions.fromString(directory ? "rwxr-x---" : "r--r-----")));
        if (!directory) {
            require(Files.getAttribute(path, "unix:nlink", LinkOption.NOFOLLOW_LINKS).equals(1));
        }
    }
    static CryptoServiceImpl recoveryCrypto(Map<String,String> manifest) throws Exception {
        if("true".equals(manifest.get("crypto.systemd.credentials"))) {
            String directory=System.getenv("CREDENTIALS_DIRECTORY");
            require(directory!=null && !directory.isBlank());
            return RecoveryCrypto.loadManaged(Path.of(directory),manifest.get("crypto.key.sha256"),manifest.get("crypto.ring.sha256"));
        }
        return RecoveryCrypto.load(
                manifest.containsKey("crypto.key.file") ? Path.of(manifest.get("crypto.key.file")) : null,
                manifest.containsKey("crypto.keyring.file") ? Path.of(manifest.get("crypto.keyring.file")) : null,
                manifest.get("crypto.keyring.sha256"), "true".equals(manifest.get("crypto.default")));
    }
    static Map<String,Object> targetProperties(ComponentConfiguration configuration,CryptoServiceImpl crypto) throws Exception {
        Map<String,Object> properties=new HashMap<>(configuration.getConfigurationProperties());
        if(configuration instanceof ComponentConfigurationImpl impl && impl.hasLogicalPasswords()) {
            for(var entry:properties.entrySet()) {
                entry.setValue(encryptLogicalPassword(entry.getValue(),crypto));
            }
        } else {
            ComponentUtil.encryptConfigurationProperties(properties,crypto);
        }
        // The legacy helper drops failed password fields: never accept that lossy result here.
        require(properties.keySet().equals(configuration.getConfigurationProperties().keySet()));
        return properties;
    }
    private static Object encryptLogicalPassword(Object value,CryptoServiceImpl crypto) throws Exception {
        if(value instanceof Password password) {
            require(password.getPassword()!=null);
            char[] plain=password.getPassword().clone();
            try {
                char[] encrypted=crypto.encryptAes(plain);
                require(encrypted!=null && encrypted.length>0);
                return new Password(encrypted);
            } finally { Arrays.fill(plain,'\0'); }
        }
        if(value instanceof Password[] passwords) {
            Password[] result=new Password[passwords.length];
            for(int n=0;n<passwords.length;n++) {
                require(passwords[n]!=null);
                result[n]=(Password)encryptLogicalPassword(passwords[n],crypto);
            }
            return result;
        }
        if(value instanceof java.util.Collection<?> values && values.stream().anyMatch(Password.class::isInstance)) {
            require(values instanceof List<?>);
            java.util.Collection<Object> result=value instanceof java.util.Vector<?> ? new java.util.Vector<>() : new ArrayList<>();
            for(Object item:values) {
                require(item instanceof Password);
                result.add(encryptLogicalPassword(item,crypto));
            }
            return result;
        }
        return value;
    }
    static byte[] read(Path path,int limit) throws Exception {
        require(path.isAbsolute()&&Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS));
        try(InputStream input=Files.newInputStream(path,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS)) {
            byte[] result=input.readNBytes(limit+1);require(result.length>0&&result.length<=limit);return result;
        }
    }
    private static void privateParent(Path path) throws Exception {
        require(path.isAbsolute()&&Files.isDirectory(path.getParent(),LinkOption.NOFOLLOW_LINKS));
        Set<PosixFilePermission> permissions=Files.getPosixFilePermissions(path.getParent(),LinkOption.NOFOLLOW_LINKS);
        require(!permissions.contains(PosixFilePermission.GROUP_WRITE)&&!permissions.contains(PosixFilePermission.OTHERS_WRITE));
    }
    static void publish(Path path,byte[] bytes) throws Exception {
        privateParent(path);require(bytes.length<=64<<20);
        try(FileChannel output=FileChannel.open(path,Set.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
            ByteBuffer buffer=ByteBuffer.wrap(bytes);while(buffer.hasRemaining()){output.write(buffer);}output.force(true);
        }
        try(FileChannel directory=FileChannel.open(path.getParent(),StandardOpenOption.READ)){directory.force(true);}
    }
    private static String hash(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }
    private static void require(boolean condition) {
        if(!condition){throw new IllegalStateException("Invalid controlled recovery contract");}
    }
}
