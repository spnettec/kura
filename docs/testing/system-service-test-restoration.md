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
