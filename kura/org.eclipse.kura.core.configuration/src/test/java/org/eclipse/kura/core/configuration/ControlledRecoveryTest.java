/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;
import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.Path;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
class ControlledRecoveryTest {
    @TempDir Path directory;
    @Test void emptyCompensationIsPinnedDoesNotFallbackAndNeverReleasesOrdinaryWrites() throws Exception {
        Process process=new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin","java").toString(),
                "-cp",System.getProperty("java.class.path"),ControlledRecoveryProbe.class.getName(),directory.toString(),"empty").redirectErrorStream(true).start();
        assertTrue(process.waitFor(15,TimeUnit.SECONDS));String output=new String(process.getInputStream().readAllBytes());assertEquals(0,process.exitValue(),output);
    }
    @Test void guardedNormalLoadRetainsOrdinaryPathAndNeverPermitsFallbackOrWrite() throws Exception {
        Process process=new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin","java").toString(),
                "-cp",System.getProperty("java.class.path"),ControlledRecoveryProbe.class.getName(),directory.toString(),"normal").redirectErrorStream(true).start();
        assertTrue(process.waitFor(15,TimeUnit.SECONDS));String output=new String(process.getInputStream().readAllBytes());assertEquals(0,process.exitValue(),output);
    }
    @Test void recoveryAdmissionPinsSourceBlocksOrdinaryWritesAndCannotFallbackOrResetInProcess() throws Exception {
        Process process=new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin","java").toString(),
                "-cp",System.getProperty("java.class.path"),ControlledRecoveryProbe.class.getName(),directory.toString()).redirectErrorStream(true).start();
        assertTrue(process.waitFor(15,TimeUnit.SECONDS));String output=new String(process.getInputStream().readAllBytes());assertEquals(0,process.exitValue(),output);
    }
}
