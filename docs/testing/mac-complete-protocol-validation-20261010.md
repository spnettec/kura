# Complete Mac MQTT core protocol acceptance — 2026-10-10

The complete Maven macOS application passed **six unchanged legacy assertions
and twelve authenticated, UUID-correlated MQTT requests**. Maven 3.10.0,
Temurin 21.0.12.1, Jupiter 5.14.4 assertion classes; 284 bundles including fixtures.
The host service is production `org.eclipse.kura.core.system.SystemServiceImpl`.
All 279 immutable runtime artifact hashes still match the assembly inventory.

## Verified paths

- Existing legacy service/local configuration/remote handler/snapshot-limit
  methods, plus DeploymentAdmin package/bundle methods, execute inside the actual
  fixture bundle with genuine host services. Temporary direct-registry fixtures
  are closed before the MQTT phase.
- An independent authenticated Paho client sends CONF-V1 GET, snapshot EXEC,
  configuration PUT, updated GET, rollback EXEC and restored GET. Actual SCR
  updates and restoration of `prop.string` are asserted.
- MQTT INVENTORY-V1 deploymentPackages/bundles/merged inventory enumerate a
  genuinely installed, ACTIVE manifest-only DeploymentAdmin fixture. Version,
  bundle state and DP/BUNDLE entries are checked; uninstall reaches UNINSTALLED.
- The actual Mac system-package API returns **zero packages**, and the MQTT
  systemPackages response returns the same count with code 200. This is empty
  development-host behavior, not proof of Linux package-manager enumeration.
- MQTT CONF-V2 writes an actual encrypted snapshot through host paths, then reads
  it by ID through the real configuration/crypto path. The response includes the
  owned cloud configuration.
- Cloud factory PID, requested cloud service PID, Chinese name and description
  are checked. The real three-service Kapua stack is deleted after disconnect.
  The loopback broker records authentication of both actual clients.

The first run exposed an immutable password Map in this new test helper. The
existing encryption path mutates password entries; the corrected helper follows
its established fixture's mutable Map pattern and waits for transport/cloud
configuration arrival. The failed run is preserved. A preliminary passing run is
also retained; the final run adds the host/MQTT package-count comparison. No
production fix was needed for these helper adjustments.

The independently owned application and broker JVMs exited, with no forced
shutdown, and ports 18480/18443/18444 were released. The 33 protected personal
profile files, stopped template keystores and template log remained unchanged.
Bootstrap keystore paths in the copied profile were relocated into its owned home.

[JSON evidence](mac-complete-protocol-validation-20261010.json) contains source,
artifact and log hashes, per-request UUID/code results and limits. Raw archives:
`/Users/heyoulin/iot-kura-develop/migration-baseline/mac-complete-protocol-final-20261010`.
The helper lives in the cloud repository's
`acceptance/full-runtime-protocol-probe/`, outside its default reactor. Its commit
is recorded in the JSON. The six methods and twelve requests are separate
executable evidence and are not added to the 5515 workspace JUnit invocations.

Five core-protocol rows now meet complete Mac assembly acceptance; inventory row
186 retains Linux package-manager enumeration. The source inventory remains
465 reviewed, zero unreviewed and zero deferred scenarios, with **31 rows / 31
strings of deferred validation**. Installed Debian, hardware, D-Bus/GPU and
additional Linux acceptance remain unclaimed. Restoration is still in progress.
