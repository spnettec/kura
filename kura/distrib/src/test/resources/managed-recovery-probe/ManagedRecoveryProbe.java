/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tests.managedrecovery;

import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.Properties;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.core.configuration.ConfigurationRestore;
import org.eclipse.kura.core.configuration.ControlledRecovery;
import org.eclipse.kura.core.crypto.CryptoServiceImpl;
import org.eclipse.kura.crypto.CryptoService;
import org.osgi.framework.Bundle;
import org.osgi.framework.FrameworkUtil;
import org.osgi.framework.startlevel.FrameworkStartLevel;
import org.osgi.service.cm.ConfigurationAdmin;
import org.osgi.service.component.ComponentContext;

/** Test-only real DS consumer; never packaged in the product. */
public final class ManagedRecoveryProbe {
    private static final char[] VALUE="disposable-managed-original-value".toCharArray();
    private static final Path DATA=Path.of("/opt/eclipse/kura/data/managed-recovery-probe");
    private CryptoService crypto;
    private ConfigurationService configuration;
    private ConfigurationAdmin admin;
    public void setCrypto(CryptoService value){this.crypto=value;}
    public void setConfiguration(ConfigurationService value){this.configuration=value;}
    public void setAdmin(ConfigurationAdmin value){this.admin=value;}

    public static void main(String[] args) throws Exception {
        if(args.length!=2){throw new IllegalArgumentException("Only fresh-fixture seed inputs accepted");}
        byte[] key=Files.readAllBytes(Path.of(args[0]));
        try {
            char[] cipher=CryptoServiceImpl.forSnapshotRecovery(key,false).encryptAes(VALUE);
            Files.createDirectories(Path.of(args[1]).getParent());
            Files.writeString(Path.of(args[1]),new String(cipher),StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW);
        } finally {Arrays.fill(key,(byte)0);}
    }

    private static String hash(byte[] data) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(data));
    }
    private static void implementation(Properties out,String role,Object value) throws Exception {
        Class<?> type=value.getClass();Bundle bundle=FrameworkUtil.getBundle(type);
        if(bundle==null || bundle.getState()!=Bundle.ACTIVE){throw new IllegalStateException("Provider not active");}
        try(InputStream input=type.getResourceAsStream("/"+type.getName().replace('.','/')+".class")) {
            out.setProperty(role+"ClassSha256",hash(input.readAllBytes()));
        }
        out.setProperty(role+"Class",type.getName());out.setProperty(role+"State",Integer.toString(bundle.getState()));
    }

    public void activate(ComponentContext context) {
        Thread probe=new Thread(()->{
            String phase=System.getProperty("kura.tests.managed.phase","invalid");
            Properties result=new Properties();result.setProperty("phase",phase);
            try {
                var level=context.getBundleContext().getBundle(0).adapt(FrameworkStartLevel.class);
                int target=Integer.parseInt(context.getBundleContext().getProperty("osgi.startLevel"));
                long deadline=System.nanoTime()+30_000_000_000L;
                while(level.getStartLevel()!=target && System.nanoTime()<deadline){Thread.sleep(100);}
                if(level.getStartLevel()!=target){throw new IllegalStateException("Framework not at target level");}
                result.setProperty("frameworkStartLevel",Integer.toString(target));
                Thread.sleep(1500); // Let the initial DS activation wave finish; no mutation is retried.
                Files.createDirectories(DATA);
                boolean bootstrapActive=false;
                for(Bundle bundle:context.getBundleContext().getBundles()) {
                    if("org.eclipse.kura.recovery.bootstrap".equals(bundle.getSymbolicName())) {
                        if(bundle.getState()!=Bundle.ACTIVE){throw new IllegalStateException("Bootstrap inactive");}
                        Class<?> type=bundle.loadClass("org.eclipse.kura.tools.recovery.RecoveryBootstrap");
                        try(InputStream input=type.getResourceAsStream("/org/eclipse/kura/tools/recovery/RecoveryBootstrap.class")) {
                            result.setProperty("bootstrapClassSha256",hash(input.readAllBytes()));
                        }
                        bootstrapActive=true;
                    }
                }
                if(!bootstrapActive){throw new IllegalStateException("Bootstrap missing");}
                byte[] original=Files.readAllBytes(DATA.resolve("original.cipher"));
                if(!Arrays.equals(VALUE,this.crypto.decryptAes(new String(original,StandardCharsets.UTF_8).toCharArray()))) {
                    throw new IllegalStateException("Original value unavailable");
                }
                result.setProperty("originalSha256",hash(original));result.setProperty("originalDecrypted","true");
                String fresh=new String(this.crypto.encryptAes(VALUE));
                if(!Arrays.equals(VALUE,this.crypto.decryptAes(fresh.toCharArray()))){throw new IllegalStateException("Round trip failed");}
                result.setProperty("currentHasGeneration",Boolean.toString(fresh.startsWith("KURA2.")));
                result.setProperty("currentKeyId",fresh.startsWith("KURA2.")?fresh.split("\\.",3)[1]:"legacy");
                if(phase.equals("ordinary")) {
                    if(ControlledRecovery.evidence().isPresent()){throw new IllegalStateException("Unexpected recovery admission");}
                    Path once=DATA.resolve("ordinary-snapshot.once");
                    Files.writeString(once,"one snapshot invocation\n",StandardOpenOption.CREATE_NEW);
                    result.setProperty("snapshotId",Long.toString(this.configuration.snapshot()));
                    result.setProperty("writesBlocked","false");
                } else if(phase.equals("controlled")) {
                    var admission=ControlledRecovery.evidence().orElseThrow();
                    if(admission.normalLoad()){throw new IllegalStateException("Wrong recovery phase");}
                    ConfigurationRestore.verify(this.admin,ControlledRecovery.configurations().orElseThrow());
                    result.setProperty("cmMatched","true");
                    result.setProperty("restoreId",admission.recoveryId());result.setProperty("snapshotSha256",admission.snapshotSha256());
                    boolean refused=false;
                    try{this.configuration.snapshot();}catch(KuraException expected){refused=expected.getMessage().contains("Controlled recovery");}
                    if(!refused){throw new IllegalStateException("Ordinary snapshot write was not blocked");}
                    result.setProperty("writesBlocked","true");
                } else {throw new IllegalStateException("Unknown probe phase");}
                implementation(result,"crypto",this.crypto);implementation(result,"configuration",this.configuration);
                var captured=ConfigurationRestore.capture(this.admin);
                result.setProperty("cmCount",Integer.toString(captured.size()));
                result.setProperty("propertyCount",Integer.toString(captured.stream().mapToInt(c->c.getConfigurationProperties().size()).sum()));
                result.setProperty("pid",Long.toString(ProcessHandle.current().pid()));result.setProperty("ok","true");
            } catch(Exception failure) {
                result.setProperty("ok","false");result.setProperty("errorType",failure.getClass().getSimpleName());
                var frames=failure.getStackTrace();if(frames.length>0){result.setProperty("errorFrame",frames[0].getClassName()+":"+frames[0].getLineNumber());}
            }
            try {
                Files.createDirectories(DATA);Path staged=Files.createTempFile(DATA,".status-",".tmp");
                try(OutputStream output=Files.newOutputStream(staged)){result.store(output,"Synthetic real Core/CM probe; no key or plaintext values");}
                Files.move(staged,DATA.resolve(phase+".properties"),StandardCopyOption.ATOMIC_MOVE);
            }catch(Exception failure){throw new IllegalStateException("Probe receipt unavailable");}
        },"managed-recovery-probe");probe.setDaemon(true);probe.start();
    }
}
