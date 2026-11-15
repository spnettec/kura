/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;
import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.Path;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
class RecoveryVerifierTest {
    @TempDir Path directory;
    @Test void liveEvidenceRejectsDriftMissingAmbiguousAndHungChecksWithoutMutationOrRelease() throws Exception {
        Process process=new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin","java").toString(),
                "-cp",System.getProperty("java.class.path"),RecoveryVerifierProbe.class.getName(),directory.toString()).redirectErrorStream(true).start();
        assertTrue(process.waitFor(15,TimeUnit.SECONDS));String output=new String(process.getInputStream().readAllBytes());assertEquals(0,process.exitValue(),output);
    }
}
