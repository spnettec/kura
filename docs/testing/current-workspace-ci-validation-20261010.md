# Current workspace CI regression — 2026-10-10

The actual `tools/ci/verify-workspace.sh` completed with exit code **0** on macOS
27.0.1 arm64, Maven 3.10.0, Temurin 21.0.12.1 and JUnit 5.14.4. Its dedicated
14-repository workspace ran `RUN_TESTS=1 RUN_IT=1 BUILD_DOCKER=0 ./build-all.sh`.

**5515 test invocations, zero failures/errors, nine skips; 407 XML reports, zero
excluded reports.** Every report digest matches the archive and every associated
Java source digest matches the original audited checkout. All 14 validation
checkouts remained clean. These counts replace the current regression snapshot;
they are not added to overlapping historical runs.

| Repository | Invocations | Skipped |
| --- | ---: | ---: |
| kura | 2107 | 3 |
| kura-camel | 52 | 0 |
| kura-cloud | 415 | 0 |
| kura-container | 131 | 0 |
| kura-deployment | 171 | 0 |
| kura-management-ui | 49 | 0 |
| kura-networking | 1961 | 0 |
| kura-opcua | 9 | 0 |
| kura-position | 75 | 0 |
| kura-triton | 116 | 0 |
| kura-wires | 380 | 0 |
| yofc-iot | 49 | 6 |

`CloudFactoryRuntimeIT` passed 13/13, including the current filesystem TLS/WSS
fixtures; `ConfigurationEndpointsIT` passed 204/204. Core baseline is
`adfac0954eb06f9d9da5e4f894b4f7f99e35fc52`, cloud is
`d2da9b137fd711d2aa70befd4c9c229c72224696`. All 19 original repositories were
audited for branch, HEAD, worktree and fetch/push remotes before the run. The
post-build audit found no branch/HEAD/remote changes; the other 18 worktrees were
clean, and core only contained the new acceptance helper pending this commit.

The skips are two SystemService methods requiring `KURA_SYSTEM_PATH_FIXTURE`,
one Linux/root clock scenario, and six pre-existing YOFC external-device/service
invocations. The two SystemService methods already have separate scoped fixture
acceptance. No skipped invocation is claimed to have executed in this run.
Existing YOFC tests were not expanded; PLC4X stayed a cache prerequisite.

The source inventory remains **465 reviewed, zero unreviewed, zero
`deferredScenarios`, 39 rows / 40 strings of `deferredValidation`**. Existing WSS,
cross-JVM file-H2 durability and IDEA evidence was reconciled by source/artifact
digests before running the workspace gate. Current cloud source supersedes two
historical WSS helper hashes; the current 13-case cloud class covers that source.
No Sparkplug callback/NDEATH investigation was repeated.

Archive: `/Users/heyoulin/iot-kura-develop/migration-baseline/final-workspace-20261010`.
The [JSON evidence](current-workspace-ci-validation-20261010.json) records pinned
revisions, reports, source/report digests, skips, reconciliation and the 19-repo
audit. Build logs and the copied `test-reports/` live in that archive. The
33 existing protected personal profile files remained identical, with no new or
removed files. No running runtime tree was cleaned.

The wrapper built distribution artifacts and the development runtime. A separate
[complete Mac application business probe](mac-full-runtime-business-validation-20261010.md)
then exercised actual host services. Remote Jenkins, installed Debian, Docker,
hardware/GPU and additional Linux acceptance remain unexecuted.
