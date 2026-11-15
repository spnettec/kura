/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;
import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
class RecoveryWriteReleaseTest {
    @TempDir Path directory;
    @Test void durableReleaseAndItsFailureBoundariesUseFreshJvms() throws Exception {
        for (String mode : new String[]{"success","publish-failure","business-failure","wrong-bounds","expired","journal-handoff","journal-publish-failure"}) {
            Path root=Files.createDirectory(this.directory.resolve(mode));
            var process=new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin","java").toString(),
                    "-cp",System.getProperty("java.class.path"),RecoveryWriteReleaseProbe.class.getName(),root.toString(),mode)
                    .redirectErrorStream(true).start();
            assertTrue(process.waitFor(12,TimeUnit.SECONDS));
            assertEquals(0,process.exitValue(),new String(process.getInputStream().readAllBytes()));
        }
    }
}
