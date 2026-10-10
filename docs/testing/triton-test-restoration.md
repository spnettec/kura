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

## Separate production repair: resource-option value equality

Three new regression invocations showed that reconstructing options from the same
properties with a CPU, memory or GPU setting produced unequal options. Each getter
wraps its value in a new Optional, but equals compared those wrappers by reference.
TritonServerServiceAbs.updated uses this result to decide whether to restart the
managed instance, so this defect can cause an unnecessary restart.

The repair compares these three Optional values with Objects.equals; existing
property-map comparison and other local configuration behavior are unchanged.
Regressions cover equal values in both directions, equal hash codes and changed
values remaining unequal. All three failed on the original implementation and pass
after the repair. The full restored module now passes 83 tests, zero failures,
errors or skips. The production change and its regressions are committed separately
from the upstream restoration. Inventory source counts remain unchanged.

## Service and gRPC continuation

The remaining nine sources (seven suites and two helpers) add 30 passing scenarios:
Bundle lifecycle 4, engine 1, inference 1, model 7, native configuration 5, remote
configuration 3 and container configuration/metrics 9. All 15 inventory sources
are now reviewed. Including the separate three equality regressions, the complete
module passes 113 tests with zero failures/errors/skips.

GrpcCleanupRule was replaced with Jupiter teardown that deactivates the service,
shuts down and awaits every owned channel/server, and closes its scoped factory
mock even after an assertion fails. Production ManagedChannelBuilder.forAddress
is routed to actual in-process gRPC channels; real generated stubs, server handlers
and serialization still execute. No production TCP endpoint is contacted. Cases
that explicitly invoke inference APIs on an invalid/unactivated native configuration
retain an injected in-process stub; they are component tests, not activation proof.

The HTTP metrics tests bind a real localhost server on an OS-assigned port before
building options and close it immediately in teardown. Disabled metrics, HTTP 500,
GPU metrics and model statistics are checked; JSON values compare structurally.
Native startup uses bounded command verification instead of a fixed wait.

Additional upstream fixture corrections:

- The container-not-running helper stubs listContainerDescriptors; previously it
  accidentally erased the available-image fixture and prevented real manager startup.
- The invalid-model-repository native case now supplies a valid backend path,
  ensuring it reaches the repository validation instead of repeating the backend case.
- Inference input shape/data and output descriptors agree. Raw responses use the
  current decoder's little-endian numbers and length-prefixed BYTES. Assertions
  inspect the transmitted input and all eight returned values/types and shapes;
  the old nonempty-list check concealed corrupt numeric values and empty BYTES.

Only grpc-inprocess 1.71.0 and Guava failureaccess 1.0.3 were added to test scope in
this continuation. Real Triton/GPU inference, container runtime, Equinox/DS and IDEA
acceptance remain open. No production or handwritten metadata change in this batch.

## Separate production repair: close replaced gRPC channels

Two regressions using actual in-process ManagedChannels reproduced retained
connections after changing to another valid configuration or to an invalid one.
A third control confirms unchanged configuration retains its live channel.

The update path now closes and awaits the old channel after stopping the managed
instance, before creating a replacement or leaving the service unconfigured.
Deactivation shares the existing shutdown/await implementation. The unchanged
configuration guard, manager lifecycle and transport settings remain intact.
The two failures were observed before the fix; all three lifecycle cases and all
116 module tests pass after it, with zero failures/errors/skips. This production
repair is a separate commit; source inventory counts do not change.

## 2026-10-11 Triton 数组配置及真实 SCR 后续

相同端口数组经复制后误判为配置变更的问题已单独复现并修复。完整模块
119/119、IDEA 3/3 通过；实际 Mac Remote/Native/Container 工厂 SCR 配置生命周期
及 remote channel 更新/关闭通过，未启动 Triton/GPU/native 进程/容器。
见 [验收记录](triton-copied-configuration-scr-validation-20261011.md)。
旧完整 CI 保留固定提交范围，未覆盖此后续私有生产修复；结果不相加。
