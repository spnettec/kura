# Complete Mac runtime business acceptance — 2026-10-10

An independently assembled complete Maven development application passed the
[acceptance probe](../../kura-dev-runtime/acceptance/full-runtime-probe/README.md)
on macOS arm64 with Maven 3.10.0/JDK 21. Its data home and ports were isolated
outside all generated runtime targets and personal `~/.kura-dev`.

- **277 production bundle entries**, plus framework/launcher and test fixtures;
  Gogo found zero bundles in `INSTALLED` state before fixtures were installed.
- The actual `org.eclipse.kura.core.system.SystemServiceImpl` supplied Kura home
  and snapshot paths; the production configuration bundle supplied its service.
- Upstream singleton and self-configuring fixtures were read through the actual
  host service. A real SCR factory instance was created, updated and deleted.
  Integer/XML values and the default `Password` type survived; the actual
  plaintext snapshot contained the fork's CDATA representation.
- The complete application's EventAdmin delivered a unique event to a temporary
  handler within the bounded wait.
- Production Timer and Logger factories created one WireAdmin route. Logger
  consumed **three actual envelopes**; graph, route and component cleanup
  assertions passed.

The first route trial delivered envelopes but its test log matcher used logical
`kura.service.pid` while `WireEnvelope` retains the generated SCR `service.pid`.
The corrected test matcher uses the unique Timer thread name. The failed trial
is retained alongside the final result; production PID behavior was unchanged.

The runtime was stopped and ports 18480/18443/18444 were released. The
[JSON evidence](mac-full-runtime-business-validation-20261010.json) records the
result, source and artifact SHA-256 values, pinned dependency revisions, cleanup
and limits. Archive:
`/Users/heyoulin/iot-kura-develop/migration-baseline/mac-full-assembly-20261010`.

This representative complete-application probe supplements the separate direct
Mac IDEA Run/Debug/restart and 47-case configuration JUnit evidence. It does not
claim all 47 scenarios ran inside this complete application, historical wire
fixtures were deployed, or Debian/hardware acceptance passed. It is not added
to the workspace's 5515 JUnit invocations. The remaining inventory boundaries
are retained explicitly; no additional Linux validation was performed.
