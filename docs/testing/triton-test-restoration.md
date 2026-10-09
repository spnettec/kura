# Triton upstream test restoration

2026-10-09; upstream snapshot `kura-triton@13d23a95`. This first batch restores six
source entries on Jupiter against the current production API; nine sources remain
unreviewed. No production or handwritten OSGi metadata changes in this batch.

| Suite | Passing cases |
| --- | ---: |
| GpuMetricsParser | 4 |
| TritonServerServiceOptions | 29 |
| TritonServerNativeManager | 7 |
| TritonServerRemoteManager | 4 |
| TritonServerContainerManager | 17 |
| TritonServerEncryptionUtils | 19 |
| Total | 80 |

Manager tests execute the actual production managers, with mocked command executor
and container orchestration services. Native positive startup waits for the
command invocation instead of a 10 ms sleep and stops each manager in teardown.
Container startup waits for a barrier on its actual single-thread scheduler, so
negative assertions also follow the initial monitor cycle. Every owned scheduler
is stopped or shut down and awaited. Remote stop/kill tests first start the manager
to verify an actual state transition. No Triton binary, container or GPU is started.

The encryption suite uses one Jupiter TempDir per case instead of cleaning a
shared `/tmp/decr_folder`. The separate temporary folder created by production is
also removed after its test. All four small upstream encrypted/ZIP fixtures are
loaded from the classpath for Maven and IDEA, independent of the working directory.
Expected errors retain their exception for useful failure diagnostics. GPU JSON
assertions compare objects instead of relying on HashMap field order.

Test-only dependencies add Jupiter, Mockito, kura-test-support, Log4j API and
Bouncy Castle bcutil 1.86 (matching the existing bcpg/bcprov). Production dependency
versions and scopes remain unchanged.

Validation: Maven 3.10.0, Temurin JDK 21, isolated migration-m2 cache:

```sh
mvn -f bundles/org.eclipse.kura.ai.triton.server/pom.xml \
  -Dmaven.repo.local=/Users/heyoulin/iot-kura-develop/migration-m2 test
```

80 invocations, zero failures/errors/skips. Service integration, real Triton/gRPC,
OSGi/DS and IDEA acceptance remain open.
