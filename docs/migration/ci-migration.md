# CI entry migration — 2026-10-10

The Jenkins pipeline now invokes the same ordinary Maven workspace entry used by
the validated local build: `RUN_TESTS=1 RUN_IT=1 BUILD_DOCKER=0 ./build-all.sh`.
It runs ordinary JUnit 5, real Equinox and HTTP/MQTT tests, then builds the existing
packages and development runtime. It does not launch the development application,
run device/D-Bus checks, or build Docker images.

The pipeline obtains Maven/JDK from the agent environment and checks Maven 3.10.x
and JDK 21 before any build. It does not assume that Eclipse's Jenkins tool names,
Kubernetes pod templates, GitLab configuration or Sonar credentials exist in this
fork. The former upstream Sonar/quality-gate stages are not carried over: a fork
Sonar service must be configured explicitly before adding such a gate. Test
failures are never ignored or automatically rerun by this entry.

## Agent/workspace contract

Use a dedicated agent/job workspace with `kura/` and the 13 sibling checkouts
required by `build-all.sh` immediately beside it. The pipeline checks out its SCM
revision into `kura/`; provision matching, pinned sibling revisions independently.
It neither guesses remote URLs/credentials nor silently switches sibling branches.
Missing siblings fail preflight before cleaning/building. The selected revision
and dirty state of each repository are included in the report summary.

Set `JAVA_HOME`, put Maven 3.10 on PATH or set `MVN` to its executable, and provide
Python 3.8 or newer and Git. Optionally set `KURA_CI_AGENT_LABEL` to an actual
configured Jenkins label; no new agent/tool installation name is presumed. Use a
separate workspace for each job because the existing build cleans module targets.
Never point the build at the user's active IDEA/runtime checkout.

PLC4X remains an explicit independently built prerequisite. Install the matching
source-built PLC4X artifacts in the selected Maven repository first. Preflight
checks the toolchain/layout only; it does not claim to verify that cache content.
Set `KURA_MAVEN_REPO=/absolute/cache` consistently for that prerequisite and this
workspace build. This entry does not expand PLC4X or YOFC tests.

```sh
bash tools/ci/verify-workspace.sh --check  # read-only toolchain/layout check
bash tools/ci/verify-workspace.sh         # full build in the dedicated checkout
```

## Test evidence

The collector only copies Surefire/Failsafe XML files newer than this build's start
and backed by the exact current Java source. It handles nested classes and retains
the latest report per repository/module/class, avoiding repeated reactor counts.
Reports from deleted sources are listed as excluded. The pipeline publishes this
filtered set, rather than globbing every old target directory in the workspace.

A failed build remains failed even if report collection succeeds. Current failed
test reports are retained, while zero current tests is an error. Prior CI reports
are removed before starting a build so an interrupted run cannot publish a prior
success. Distribution artifacts are archived only after a successful build.

The JDK 11/Maven 3.6.2 Travis definition targeted removed examples/PDE tests and
performed destructive cache resets. It and its Java 6/7/8 toolchain file had no
remaining repository consumers and are removed. Their history remains in Git.
No live CI job, account, credential or server setting was modified.

## Local verification and limits

On macOS, the actual Maven 3.10.0/JDK 21 preflight passed. Five Python regression
checks cover stale/deleted reports, nested/deduplicated classes, failed and empty
runs, required workspace/toolchain checks, preserved build failure and old-report
cleanup. Jenkinsfile parses with the locally available Groovy 4.0.31 compiler;
this is syntax validation, not Jenkins plugin/server execution.

The collector was also replayed against the newly completed actual endpoint
reports and returned **184 tests, zero failures/errors/skips**, matching their
archived evidence. This replay does not rerun those tests. The full build command
it wraps already passed in the [workspace regression](../testing/full-workspace-validation-20261010.md);
the new wrapper was not used to repeat that expensive build. No Jenkins server
run or additional Linux validation was performed. Deployment to a live CI service
remains an environment integration step, not a claimed passing result.
