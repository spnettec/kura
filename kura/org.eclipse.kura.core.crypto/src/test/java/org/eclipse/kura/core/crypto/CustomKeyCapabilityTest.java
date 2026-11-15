package org.eclipse.kura.core.crypto;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.Arrays;
import org.eclipse.kura.crypto.CryptoService;
import org.junit.jupiter.api.Test;

class CustomKeyCapabilityTest {
    @Test void uninitializedAndExplicitLegacyRecoveryContextsDoNotAttestACustomKey() {
        assertFalse(new CryptoServiceImpl().hasCustomEncryptionKey());
        assertFalse(CryptoServiceImpl.forSnapshotRecovery(null,true).hasCustomEncryptionKey());
        assertFalse(mock(CryptoService.class,CALLS_REAL_METHODS).hasCustomEncryptionKey());
    }
    @Test void configuredContextAttestsWithoutExposingTheKeyAndAuthFailureRemainsAnError() throws Exception {
        byte[] key=new byte[32];Arrays.fill(key,(byte)0x67);
        var service=CryptoServiceImpl.forSnapshotRecovery(key,false);assertTrue(service.hasCustomEncryptionKey());
        char[] plaintext="logical content which starts encrypted:".toCharArray();
        char[] cipher=service.encryptAes(plaintext);assertArrayEquals(plaintext,service.decryptAes(cipher));
        cipher[cipher.length/2]=cipher[cipher.length/2]=='A'?'B':'A';
        assertThrows(org.eclipse.kura.KuraException.class,()->service.decryptAes(cipher));
    }
}
