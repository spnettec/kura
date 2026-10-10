# System service upstream test restoration

Audited both `org.eclipse.kura.core.system.test` sources at upstream
`e500a68d7b3f4a970aca3e13c038947269278827` against the current implementation.

- `SystemServiceTest`: five scenarios cover explicit and directory-based property
  files, custom/default precedence, system overrides and successful/failed package
  parsing for dpkg, rpm and apk. Real files live under JUnit temporary directories.
- `SystemServiceRuntimeTest`: 26 scenarios cover OS/JVM and device properties,
  current network defaults and MAC parsing with deterministic command output.
  Known fixture properties have exact value assertions; JDK vendor version is
  compared with the actual JDK 21 property rather than assuming it is absent.
- A shared fixture restores the original system properties in `finally`, locks
  global properties and controls scheduling/command execution. Activation and
  deactivation run, with cancellation and scheduler shutdown verified.

Maven 3.10.0 / Temurin 21 / JUnit Jupiter full-module result: **31 tests, zero
failures, errors or skips**. Only test sources and test dependencies changed;
handwritten OSGi metadata and production behavior are unchanged.

## Explicitly unfinished boundaries

`testActivateRelativeConfigFilePathsUpdate` and `testActivateWithUpdatedDefaults`
write to the hardcoded `/opt/eclipse/kura` hierarchy. They remain recorded in
`deferredMethods` for an isolated filesystem/runtime fixture. A construction mock
for `java.io.File` affected the test JVM's class loader, so that approach was
removed instead of retaining an unstable or host-mutating test.

The runtime source's `testServiceExists` remains deferred to actual Kura SCR
assembly. `testDummy` and `testGetProductVersion` only assert `true` upstream and
are explicitly excluded. This suite does not validate real package commands,
network access, hardware MAC discovery, service registration or IDEA execution.
Source audit completion does not imply these acceptance checks are complete.

## Core platform continuation

The older core `NetUtilTest` primary MAC scenario now runs twice, for `eth0` and
`en0`, with controlled Java network-interface enumeration and exact output checks.
Full core module: 111 passing tests. No NetworkManager/D-Bus implementation changes.

The older `SystemAdminServiceTest` positive uptime case runs against the actual
macOS parser with controlled `sysctl` output. Full system module: 32 passing tests.
Its real SCR service-existence case remains deferred. Source inspection identifies
an apparent seconds/milliseconds mismatch in this parser; that will be confirmed
and repaired separately rather than folded into this restoration commit.

## Separate macOS uptime repair

A bounded uptime assertion reproduced the defect: a boot time 30 seconds earlier
returned roughly 1.79 trillion milliseconds rather than 30,000. The `sysctl` `sec`
field is now converted to milliseconds before subtraction, matching the existing
Linux/Windows API units. Actual read-only macOS `sysctl` output confirmed the format.
The fix leaves other platform branches, API and metadata unchanged.

The new regression fails before the one-line fix and passes afterward. All **33
system tests and isolated bundle installation** pass on Maven 3.10/JDK 21. Cloud
birth/disconnect/device-profile and management UI callers consume the same string;
no caller API adaptation is required. Networking has no matching call in its index.
The suspected defect above is resolved; inventory remains 62 unreviewed.


## Remaining methods restored (2026-10-10)

Both `testServiceExists` methods now run in `SystemServicesRuntimeIT` with actual
Equinox and SCR. The controller has no Kura business classes. It verifies missing
mandatory executor references before registration, actual core.system service
providers/API wiring afterward, and removal after stopping the bundle. The real
SystemService reads temporary default/custom property files and creates only test
directories. A proxy implements the actual bundle-loaded PrivilegedExecutorService
interface and rejects command execution. No host package, ping, reboot or sync
commands are run. Both scenarios pass; the complete Equinox suite is **64 passed**.

The two hardcoded `/opt/eclipse/kura` migration cases now run through:

```sh
MAVEN_HOME=/path/to/apache-maven-3.10.0 \
MAVEN_REPO=/absolute/path/to/prepared-m2 \
  tools/testing/verify-system-paths.sh
```

The script uses an offline Temurin 21 Docker container with no network, a read-only
checkout/cache, and tmpfs for `/opt/eclipse/kura`, `/tmp`, Maven locks and module
build output. Only a fresh report directory is writable on the host. Maven 3.10.0
and Java 21 were confirmed inside the container. Both original path assertions
and the working-directory update pass; all **35 system tests pass with no skips**.
Reports are copied while the container is running, before its tmpfs is torn down.
Each run produces `target/isolated-system-reports-XXXXXXXX/`.

The methods require `KURA_SYSTEM_PATH_FIXTURE=1`, then verify `/.dockerenv` and the
actual tmpfs file-store type before writing. Ordinary host execution does not set
this variable and skips those two methods. The former File-construction-mock
approach was not reused. Production code and handwritten metadata are unchanged.
Actual hardware/network commands, deployed Kura assembly and GUI execution of
these new system tests remain separate acceptance work.
