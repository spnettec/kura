# Upstream test resume evidence audit (2026-10-11)

The resumed workspace matches the prior 19-repository handoff. All repositories
were clean on `codex/maven-bundle-idea` before this documentation reconciliation.
Fifteen same-named published branches match their forks; PLC4X matches the existing
`heyoulin` fork branch. The three management repositories remain local with no
remote. Exact baseline revisions are in the companion JSON.

The inventory remains 465 reviewed records, zero unreviewed and zero deferred
scenarios, with 22 deferred validation records and nine user-excluded Triton
records. All 458 local-source references and 36 explicit evidence references
resolve; referenced JSON parses successfully.

The frozen CI manifest, build log, 409 XML reports and their source snapshots pass
820 SHA checks. Parsing those reports reproduces 5521 invocations, zero failures
or errors and nine skips. All 14 archive revisions match the recorded pins and are
ancestors of the corresponding current branches. This verifies existing evidence;
it is not a new full CI run of current HEADs.

Separate follow-up checks verify the seven DataService cross-JVM artifacts,
22 Sparkplug interruption manifest/artifact checks, three Camel IDEA artifacts
and the packaged Camel result SHA. The Sparkplug evidence retains 155 module,
13 real SCR and three IDEA invocations; Camel IDEA retains three DSL cases.
None of these overlapping/separate results is added to the frozen CI total.

The reconciliation corrects a stale WireTestUtil sentence and the helper audit's
initial runtime-gap wording. Mac SCR/factory/EventAdmin/WireAdmin acceptance is
already covered by the linked follow-up evidence. Installed Debian and deployed
gateway boundaries remain deferred. No Kura tests are rerun by this audit.

The remaining records require installed Debian packages (14), system/network
behavior (three), physical watchdog behavior (one), an external SecurityService
provider (two), or deployed gateway acceptance (two). They are not closed by Mac
fixtures. Linux and additional Triton validation remain outside the requested
scope; no external provider or hardware/gateway environment was supplied.

Overall restoration remains incomplete. No production source, runtime assembly,
YOFC/PLC4X scope or OPC UA behavior changed. Shared knowledge routing was repaired
separately: existing migrated vaults no longer restore deleted bootstrap notes,
ZCode SessionStart uses its own session directory, and WorkBuddy's rules agree
with the common manager. The original 57 migrated files were preserved before
appending the repair record, and 13 routing/manager regressions passed.

Detailed results: `upstream-test-resume-audit-20261011.json`.
Raw reconciliation archive:
`/Users/heyoulin/iot-kura-develop/migration-baseline/upstream-test-resume-audit-20261011`.
Knowledge repair backups and actual entrypoint verification:
`/Users/heyoulin/iot-kura-develop/migration-baseline/vault-migration-repair-20261011`.
