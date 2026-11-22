/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.configuration.XmlComponentConfigurations;
import org.eclipse.kura.core.crypto.CryptoServiceImpl;
import org.eclipse.kura.internal.xml.marshaller.unmarshaller.XmlJavaComponentConfigurationsMapper;

/** Test-only entrypoint for a fresh systemd fixture; never packaged in the product. */
public final class ManagedCredentialProbe {
    public static void main(String[] args) {
        String phase="arguments";
        try {
            if(args.length==2 && args[0].equals("seed")) { seed(Path.of(args[1])); return; }
            if(args.length!=3 || !List.of("read","reject").contains(args[0])) { throw new IllegalArgumentException(); }
            phase="manifest";
            var manifest=RecoveryBootstrap.manifest(Path.of(args[1]));
            CryptoServiceImpl crypto;
            phase="credentials";
            try { crypto=RecoveryBootstrap.recoveryCrypto(manifest); }
            catch(Exception refusal) {
                if(!args[0].equals("reject")) { throw refusal; }
                System.out.println("MANAGED_CREDENTIAL_REJECTED");return;
            }
            if(args[0].equals("reject")) { throw new IllegalStateException(); }
            if(Files.exists(Path.of("/fixtures/managed-credentials/active"))) { throw new IllegalStateException(); }
            phase="artifact";
            byte[] artifact=Files.readAllBytes(Path.of(manifest.get("snapshot.path")));
            byte[] xml=artifact;
            try {
                if(manifest.get("snapshot.mode").equals("aes-gcm")) {
                    try(var input=crypto.aesDecryptingStream(new ByteArrayInputStream(artifact))) { xml=input.readNBytes((32<<20)+1); }
                }
                var decoded=SnapshotTool.decode(xml,crypto,"authenticated");
                if(decoded.report().authenticated!=Integer.parseInt(args[2])) { throw new IllegalStateException(); }
                System.out.println("MANAGED_CREDENTIAL_READER_OK");
            } finally { Arrays.fill(artifact,(byte)0);Arrays.fill(xml,(byte)0); }
        } catch(Exception failure) {
            System.err.println("MANAGED_CREDENTIAL_PROBE_FAILED phase="+phase+" type="+failure.getClass().getSimpleName());
            Arrays.stream(failure.getStackTrace()).limit(4).forEach(frame->System.err.println(
                    frame.getClassName()+"."+frame.getMethodName()+":"+frame.getLineNumber()));
            System.exit(2);
        }
    }

    private static void seed(Path root) throws Exception {
        byte[] old=Files.readAllBytes(root.resolve("old"));
        byte[] active=Files.readAllBytes(root.resolve("active"));
        byte[] ring=Files.readAllBytes(root.resolve("ring"));
        try {
            var legacy=CryptoServiceImpl.forSnapshotRecovery(old,false);
            var single=CryptoServiceImpl.forSnapshotRecovery(active,false);
            var generations=CryptoServiceImpl.forKeyRingRecovery(ring,active);
            byte[] mixed=xml(generations,Map.of("old",new Password(legacy.encryptAes("old-fixture-value".toCharArray())),
                    "current",new Password(generations.encryptAes("new-fixture-value".toCharArray()))));
            byte[] current=xml(single,Map.of("current",new Password(single.encryptAes("single-fixture-value".toCharArray()))));
            Files.write(root.resolve("mixed.xml"),mixed);Files.write(root.resolve("single.xml"),current);
            encrypted(root.resolve("mixed-old.aes"),mixed,legacy);
            encrypted(root.resolve("mixed-current.aes"),mixed,generations);
            encrypted(root.resolve("single.aes"),current,single);
            Arrays.fill(mixed,(byte)0);Arrays.fill(current,(byte)0);
        } finally { Arrays.fill(old,(byte)0);Arrays.fill(active,(byte)0);Arrays.fill(ring,(byte)0); }
    }

    private static byte[] xml(CryptoServiceImpl crypto,Map<String,Object> values) throws Exception {
        var source=new XmlComponentConfigurations();
        source.setConfigurations(List.of(new ComponentConfigurationImpl("test.managed.credentials",null,values)));
        var output=new ByteArrayOutputStream();new XmlJavaComponentConfigurationsMapper(crypto).marshal(output,source);
        return output.toByteArray();
    }

    private static void encrypted(Path path,byte[] xml,CryptoServiceImpl crypto) throws Exception {
        try(var output=crypto.aesEncryptingStream(Files.newOutputStream(path))) { output.write(xml); }
    }
}
