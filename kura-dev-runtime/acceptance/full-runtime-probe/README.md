# Complete runtime acceptance fixture

Test-only OSGi bundle outside the default reactor. It exercises host
SystemService/configuration, singleton/self/factory SCR fixtures, snapshot CDATA,
EventAdmin and a production Timer → Logger route in a **dedicated empty macOS
profile**. It writes `full-runtime-probe-result.json` under `kura.home` and fails
bundle activation on any assertion or cleanup failure. It is not a JUnit suite.

## Reproduction

1. Build the current core and sibling artifacts using Maven 3.10/JDK 21. Assemble
   `kura-dev-runtime` in a dedicated checkout with `KURA_DEV_HOME` pointing to a
   new acceptance directory **outside `target/runtime` and `~/.kura-dev`**.
   Keep that environment for both assembly and launch. Select unused HTTP/HTTPS
   ports with `KURA_HTTP_PORT`, `KURA_HTTPS_PORT` and `KURA_CLIENT_AUTH_PORT`.
2. Build this helper with the same Maven cache:

   ```sh
   mvn -f kura-dev-runtime/acceptance/full-runtime-probe/pom.xml package \
     -Dmaven.repo.local=/absolute/cache
   ```

3. Launch the complete runtime with `runtime.py run --profile macos`. Verify no
   bundle is `INSTALLED`, and the initial wire graph is empty. Install/start
   `kura-configuration-test-fixtures` and its JUnit API dependencies from the
   current `kura-osgi-tests/target/config-it-bundles` fixture set. Then install
   and start this helper JAR through Gogo.
4. Inspect the result JSON and `FULL_RUNTIME_PROBE_PASS` output. Stop the
   application before any target clean/reassembly and verify its ports released.

The helper creates unique owned PIDs and restores the empty graph. It requires
production `SystemServiceImpl`, production configuration service and actual
WireAdmin. It does not reset profiles or deploy package/hardware fixtures.
Do not run it against a user's active application or a nonempty wire graph.

[2026-10-10 evidence](../../../docs/testing/mac-full-runtime-business-validation-20261010.md)
records a passing complete Mac application probe and its preserved failed log
matcher trial. Existing IDEA acceptance is recorded separately.
