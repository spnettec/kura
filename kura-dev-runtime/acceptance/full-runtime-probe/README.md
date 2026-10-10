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

## Complete upstream configuration scenarios

`configuration-scenarios.py` reads the exact 47-case `ConfigurationServiceRuntimeIT`
selection and invokes the unchanged `ConfigurationServiceScenarios` assertions
inside a fresh complete application per case. It uses the real host
`SystemServiceImpl`, configuration service, OCD and SCR fixtures. The 46 upstream
cases use encrypted snapshots; the fork CDATA case uses plaintext. These are
executable assertions rather than another JUnit engine report, so their count is
recorded separately from workspace test invocations.

Build the helper, then supply a previously assembled, stopped macOS runtime,
an isolated acceptance template profile, current test fixture JARs and Java 21:

```sh
python3 kura-dev-runtime/acceptance/full-runtime-probe/configuration-scenarios.py \
  --runtime /absolute/dedicated-runtime \
  --template-profile /absolute/isolated-template-profile \
  --fixtures /absolute/kura-osgi-tests/target/config-it-bundles \
  --repository /absolute/kura \
  --archive /absolute/new-acceptance-archive \
  --java /absolute/jdk21/bin/java
```

The archive must be new and outside `~/.kura-dev`. The runtime template must use
ports 18480/18443/18444, matching the runner's availability/release assertions.
The runner copies the isolated template into a new home and Equinox configuration
area for every case, including relocation of absolute snapshot/bootstrap keystore
paths into that owned copy. `prepare()` cleans only that copied snapshot directory; the
probe verifies the ownership marker and actual host paths before invoking it.
The existing template and runtime tree are not cleaned or rewritten. Each owned
JVM is terminated after its result and awaited before the next case. A failed
assertion, timeout or forced shutdown stops the batch; nothing retries it.
`--scenario <name>` selects one explicit scenario for diagnosis in a new archive.

Development encryption may use the default test key when the isolated template
has no user master key; this suite validates the snapshot encryption/rollback
branch, not a production key provisioning process. Real filesystem TLS/WSS
keystore acceptance has separate evidence.
