/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.crypto;

import static org.junit.jupiter.api.Assertions.*;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.FilterOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;
import java.util.Properties;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

import org.eclipse.kura.KuraException;
import org.eclipse.kura.system.SystemService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.Mockito;

class EncryptionKeyRingTest {
    @TempDir Path directory;
    private static final byte[] OLD = "rv;ipse329183!@#".getBytes(StandardCharsets.UTF_8);
    private static final byte[] FIRST = key(0x35);
    private static final byte[] SECOND = key(0x68);
    private static final String VALUE = "旧值 / retained password & snapshot <xml/>";

    private static byte[] key(int value) {
        byte[] bytes = new byte[32]; Arrays.fill(bytes, (byte)value); return bytes;
    }
    private static byte[] ring(int active, byte[]... keys) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        out.writeBytes("YOFC-KURA-KEYRING-v1\n".getBytes(StandardCharsets.US_ASCII));
        out.write(keys.length); out.write(active); out.write(0);
        for (byte[] key : keys) { out.write(key.length); out.writeBytes(key); }
        return out.toByteArray();
    }
    private static CryptoServiceImpl legacy() { return CryptoServiceImpl.forSnapshotRecovery(OLD,false); }
    private static CryptoServiceImpl first() { return CryptoServiceImpl.forKeyRingRecovery(ring(1,OLD,FIRST)); }
    private static CryptoServiceImpl second() { return CryptoServiceImpl.forKeyRingRecovery(ring(2,OLD,FIRST,SECOND)); }
    private static byte[] streamEncrypt(CryptoServiceImpl service,String value,boolean returningStream) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        if (returningStream) {
            try (OutputStream encrypted = service.aesEncryptingStream(out)) { encrypted.write(value.getBytes(StandardCharsets.UTF_8)); }
        } else { service.encryptAes(new ByteArrayInputStream(value.getBytes(StandardCharsets.UTF_8)),out); }
        return out.toByteArray();
    }
    private static void allReaders(CryptoServiceImpl service,byte[] encrypted,String expected) throws Exception {
        assertArrayEquals(expected.toCharArray(),service.decryptAes(new String(encrypted,StandardCharsets.US_ASCII).toCharArray()));
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        service.decryptAes(new ByteArrayInputStream(encrypted),out);
        assertEquals(expected,out.toString(StandardCharsets.UTF_8));
        try (InputStream decrypted = service.aesDecryptingStream(new ByteArrayInputStream(encrypted))) {
            assertEquals(expected,new String(decrypted.readAllBytes(),StandardCharsets.UTF_8));
        }
    }
    private static void allReject(CryptoServiceImpl service,String encrypted) {
        byte[] bytes = encrypted.getBytes(StandardCharsets.US_ASCII);
        assertThrows(KuraException.class,()->service.decryptAes(encrypted.toCharArray()));
        assertThrows(KuraException.class,()->service.decryptAes(new ByteArrayInputStream(bytes),new ByteArrayOutputStream()));
        assertThrows(Exception.class,()->{
            try (InputStream in=service.aesDecryptingStream(new ByteArrayInputStream(bytes))) { in.readAllBytes(); }
        });
    }

    @Test void legacyValuesAndBothStreamWritersRemainReadableAcrossTwoRotations() throws Exception {
        for (CryptoServiceImpl writer : new CryptoServiceImpl[]{legacy(),first(),second()}) {
            for (byte[] encrypted : new byte[][]{new String(writer.encryptAes(VALUE.toCharArray())).getBytes(StandardCharsets.US_ASCII),
                    streamEncrypt(writer,VALUE,true),streamEncrypt(writer,VALUE,false)}) {
                allReaders(second(),encrypted,VALUE);
            }
        }
    }

    @Test void newCiphertextUsesOnlyTheActiveGenerationAndAuthenticatesItsHeader() throws Exception {
        String encrypted = new String(second().encryptAes(VALUE.toCharArray()));
        assertTrue(encrypted.startsWith("KURA2."+EncryptionKeyRing.id(SECOND)+"."));
        CryptoServiceImpl onlyNew=CryptoServiceImpl.forSnapshotRecovery(SECOND,false);
        allReaders(onlyNew,encrypted.getBytes(StandardCharsets.US_ASCII),VALUE);
        // Removing metadata must not turn a v2 payload into an accepted v1 value.
        allReject(onlyNew,encrypted.substring("KURA2.".length()+64+1));
        allReject(second(),encrypted.replace(EncryptionKeyRing.id(SECOND),EncryptionKeyRing.id(FIRST)));
        allReject(second(),encrypted.replace(EncryptionKeyRing.id(SECOND),"0".repeat(64)));
        allReject(second(),encrypted.replace("KURA2.","KURA3."));
    }

    @Test void untaggedValuesUseExactlyTheDesignatedLegacyKeyWithoutTrialOrDefaultFallback() throws Exception {
        byte[] wrongLegacy="other-legacy-key".getBytes(StandardCharsets.US_ASCII);
        CryptoServiceImpl selected=CryptoServiceImpl.forKeyRingRecovery(ring(1,wrongLegacy,FIRST,OLD));
        allReject(selected,new String(legacy().encryptAes(VALUE.toCharArray())));
        allReject(first(),new String(CryptoServiceImpl.forSnapshotRecovery(FIRST,false).encryptAes(VALUE.toCharArray())));
    }

    @Test void emptyPlaintextIsAuthenticatedInAllValueAndStreamFormats() throws Exception {
        for (CryptoServiceImpl writer:new CryptoServiceImpl[]{legacy(),second()}) {
            for (byte[] encrypted:new byte[][]{new String(writer.encryptAes(new char[0])).getBytes(StandardCharsets.US_ASCII),
                    streamEncrypt(writer,"",true),streamEncrypt(writer,"",false)}) { allReaders(second(),encrypted,""); }
        }
    }

    @Test void malformedAndTruncatedMaterialNeverBecomesAPlaintextFallback() {
        for (String bad:new String[]{"x","x-y-z","-","====-AA==","A".repeat(100000),
                "KURA2."+"0".repeat(64)+".AAAAAAAAAAAAAAAA-AA==","AAAAAAAAAAAAAAAA-"}) { allReject(second(),bad); }
    }

    @Test void mutatedCiphertextAndAuthenticationTagAreRejectedByEveryReader() throws Exception {
        String encrypted=new String(first().encryptAes(VALUE.toCharArray()));
        int offset=encrypted.indexOf('-')+1;
        char change=encrypted.charAt(offset)=='A'?'B':'A';
        allReject(first(),encrypted.substring(0,offset)+change+encrypted.substring(offset+1));
        allReject(first(),encrypted.substring(0,encrypted.length()-4));
    }

    @Test void trailingEncodedBytesAfterPaddingAreRejectedByEveryReader() throws Exception {
        for(CryptoServiceImpl writer:new CryptoServiceImpl[]{legacy(),first()}){
            String padded=new String(writer.encryptAes(new char[0]));
            assertTrue(padded.endsWith("=="));
            allReject(second(),padded+"AAAA");
            allReject(second(),padded+"\n");
        }
    }

    @Test void malformedDuplicateOversizedAndWeakActiveRingsAreRejected() {
        assertThrows(IllegalArgumentException.class,()->CryptoServiceImpl.forKeyRingRecovery(new byte[0]));
        assertThrows(IllegalArgumentException.class,()->CryptoServiceImpl.forKeyRingRecovery(new byte[513]));
        assertThrows(IllegalArgumentException.class,()->CryptoServiceImpl.forKeyRingRecovery(ring(1,OLD,OLD)));
        assertThrows(IllegalArgumentException.class,()->CryptoServiceImpl.forKeyRingRecovery(ring(0,OLD,FIRST)));
        assertThrows(IllegalArgumentException.class,()->CryptoServiceImpl.forKeyRingRecovery(ring(1,OLD,new byte[24])));
        byte[] valid=ring(1,OLD,FIRST);
        assertThrows(IllegalArgumentException.class,()->CryptoServiceImpl.forKeyRingRecovery(Arrays.copyOf(valid,valid.length-1)));
        assertThrows(IllegalArgumentException.class,()->CryptoServiceImpl.forKeyRingRecovery(Arrays.copyOf(valid,valid.length+1)));
        valid[0]^=1;
        assertThrows(IllegalArgumentException.class,()->CryptoServiceImpl.forKeyRingRecovery(valid));
    }

    @Test void parsedMaterialIsIndependentOfTheMutableInputBuffer() throws Exception {
        byte[] input=ring(1,OLD,FIRST);
        CryptoServiceImpl selected=CryptoServiceImpl.forKeyRingRecovery(input);
        Arrays.fill(input,(byte)0);
        allReaders(selected,new String(first().encryptAes(VALUE.toCharArray())).getBytes(StandardCharsets.US_ASCII),VALUE);
    }

    @Test void installedRingMustMatchTheSeparateActiveCredentialAndCannotFallBack() throws Exception {
        Files.write(this.directory.resolve(EncryptionKeyRing.CREDENTIAL),ring(1,OLD,FIRST));
        SystemdCredentialLoader loader=new SystemdCredentialLoader(this.directory.toFile());
        CryptoServiceImpl selected=legacy();
        assertThrows(IllegalStateException.class,()->selected.loadKeyRing(loader));
        Files.write(this.directory.resolve("kura_encryption_key"),SECOND);
        assertThrows(IllegalStateException.class,()->selected.loadKeyRing(loader));
        Files.write(this.directory.resolve("kura_encryption_key"),FIRST);
        assertTrue(selected.loadKeyRing(loader));
        allReaders(selected,new String(legacy().encryptAes(VALUE.toCharArray())).getBytes(StandardCharsets.US_ASCII),VALUE);
        assertTrue(new String(selected.encryptAes(VALUE.toCharArray())).startsWith("KURA2."));
    }

    @Test void boundedCredentialsRejectLinksDirectoriesAndOversizedBytes() throws Exception {
        SystemdCredentialLoader loader=new SystemdCredentialLoader(this.directory.toFile());
        assertTrue(loader.loadCredential(EncryptionKeyRing.CREDENTIAL,512).isEmpty());
        Files.write(this.directory.resolve("target"),ring(1,OLD,FIRST));
        Path link=this.directory.resolve(EncryptionKeyRing.CREDENTIAL);
        Files.createSymbolicLink(link,Path.of("target"));
        assertThrows(IOException.class,()->loader.loadCredential(EncryptionKeyRing.CREDENTIAL,512));
        Files.delete(link); Files.createDirectory(link);
        assertThrows(IOException.class,()->loader.loadCredential(EncryptionKeyRing.CREDENTIAL,512));
        Files.delete(link); Files.write(link,new byte[513]);
        assertThrows(IOException.class,()->loader.loadCredential(EncryptionKeyRing.CREDENTIAL,512));
        assertThrows(IOException.class,()->loader.loadCredential("../target",512));
    }

    @Test void finalizationFailureIsReportedInsteadOfReturningATruncatedSuccessfulEncryption() {
        OutputStream failure=new FilterOutputStream(new ByteArrayOutputStream()) {
            @Override public void close() throws IOException { throw new IOException("synthetic-finalization-failure"); }
        };
        assertThrows(KuraException.class,()->legacy().encryptAes(new ByteArrayInputStream(new byte[]{1}),failure));
    }

    private static Cipher cipher(int mode) throws Exception {
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(mode,new SecretKeySpec(SECOND,"AES"),new GCMParameterSpec(128,new byte[12]));
        return cipher;
    }

    @Test void largeAuthenticatedReadsSpillOnlyCiphertextWithPrivateModesAndRemoveItOnClose() throws Exception {
        byte[] clear=new byte[200000];new java.security.SecureRandom().nextBytes(clear);
        byte[] encrypted=cipher(Cipher.ENCRYPT_MODE).doFinal(clear);
        try(InputStream in=new AuthenticatedDecryptingStream(new ByteArrayInputStream(encrypted),
                cipher(Cipher.DECRYPT_MODE),cipher(Cipher.DECRYPT_MODE),this.directory)){
            assertEquals(Byte.toUnsignedInt(clear[0]),in.read());
            Path spool;
            try(var paths=Files.list(this.directory)){spool=paths.findFirst().orElseThrow();}
            assertEquals(PosixFilePermissions.fromString("rwx------"),Files.getPosixFilePermissions(spool));
            assertEquals(PosixFilePermissions.fromString("rw-------"),Files.getPosixFilePermissions(spool.resolve("value")));
            assertArrayEquals(encrypted,Files.readAllBytes(spool.resolve("value")));
            assertArrayEquals(Arrays.copyOfRange(clear,1,clear.length),in.readAllBytes());
        }
        try(var paths=Files.list(this.directory)){assertEquals(0,paths.count());}
    }

    @Test void badTagReleasesNoPlaintextAndRemovesTheLargeCiphertextSpool() throws Exception {
        byte[] encrypted=cipher(Cipher.ENCRYPT_MODE).doFinal(new byte[200000]);
        encrypted[encrypted.length-1]^=1;
        byte[] output=new byte[128];Arrays.fill(output,(byte)0x4d);
        try(InputStream in=new AuthenticatedDecryptingStream(new ByteArrayInputStream(encrypted),
                cipher(Cipher.DECRYPT_MODE),cipher(Cipher.DECRYPT_MODE),this.directory)){
            assertThrows(IOException.class,()->in.read(output));
            assertThrows(IOException.class,()->in.read(output));
        }
        for(byte value:output){assertEquals((byte)0x4d,value);}
        try(var paths=Files.list(this.directory)){assertEquals(0,paths.count());}
    }

    @Test void interruptedCiphertextReadIsNotRepeatedAndLeavesNoSpool() throws Exception {
        int[] reads={0};
        InputStream broken=new InputStream(){
            @Override public int read(){throw new AssertionError("bulk reads required");}
            @Override public int read(byte[] bytes,int offset,int length)throws IOException{
                if(++reads[0]>10){throw new IOException("synthetic input failure");}
                Arrays.fill(bytes,offset,offset+length,(byte)1);return length;
            }
        };
        try(InputStream in=new AuthenticatedDecryptingStream(broken,
                cipher(Cipher.DECRYPT_MODE),cipher(Cipher.DECRYPT_MODE),this.directory)){
            assertThrows(IOException.class,()->in.read());int afterFailure=reads[0];
            assertThrows(IOException.class,()->in.read());assertEquals(afterFailure,reads[0]);
        }
        try(var paths=Files.list(this.directory)){assertEquals(0,paths.count());}
    }

    @Test void storeSaveCanReadOldPasswordsAndWriteNewGenerationWithoutRewritingRetainedValue() throws Exception {
        CryptoServiceImpl selected=new CryptoServiceImpl();
        SystemService system=Mockito.mock(SystemService.class);
        Mockito.when(system.getKuraDataDirectory()).thenReturn(this.directory.toString());
        selected.setSystemService(system); selected.activate();
        Path store=this.directory.resolve("store.save");
        Properties original=new Properties();
        String oldCipher=new String(legacy().encryptAes(VALUE.toCharArray()));original.setProperty("old",oldCipher);
        try (OutputStream out=Files.newOutputStream(store)) { original.store(out,"synthetic retained fixture"); }
        Files.setPosixFilePermissions(store,PosixFilePermissions.fromString("rw-------"));
        byte[] before=Files.readAllBytes(store);
        Files.write(this.directory.resolve(EncryptionKeyRing.CREDENTIAL),ring(1,OLD,FIRST));
        Files.write(this.directory.resolve("kura_encryption_key"),FIRST);
        assertTrue(selected.loadKeyRing(new SystemdCredentialLoader(this.directory.toFile())));
        assertArrayEquals(VALUE.toCharArray(),selected.getKeyStorePassword("old"));
        assertArrayEquals(before,Files.readAllBytes(store));
        selected.setKeyStorePassword("new",VALUE.toCharArray());
        Properties after=new Properties();try (InputStream in=Files.newInputStream(store)) { after.load(in); }
        assertEquals(oldCipher,after.getProperty("old"));assertTrue(after.getProperty("new").startsWith("KURA2."));
        assertArrayEquals(VALUE.toCharArray(),selected.getKeyStorePassword("new"));
    }
}
