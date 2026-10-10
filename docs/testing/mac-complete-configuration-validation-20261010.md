# Complete Mac configuration scenario acceptance — 2026-10-10

**47/47 restored configuration scenarios passed**, with no failures or skips,
inside 47 fresh complete Maven macOS applications. Maven 3.10.0, Temurin
21.0.12.1, Jupiter 5.14.4 assertion classes. Every case used production
`org.eclipse.kura.core.system.SystemServiceImpl`, the production configuration
service and actual OCD/ConfigAdmin/SCR fixtures; no SystemService proxy was
registered. The source selection and scenario assertions are unchanged.

The complete runtime has 277 production bundle entries plus framework/launcher;
fixtures bring each case to 284 installed bundles. All 279 original runtime
artifact hashes still match its assembly inventory. Runtime production core is
`adfac0954eb0`; the current `d52553e43b` checkout differs through the prior
acceptance helper/evidence only. The current upstream scenario/controller source
hashes and all copied helper artifact hashes are recorded in the JSON.

Covered paths include singleton/self configuration reads, factory creation and
deletion, default/custom password values, null/invalid/empty updates, filtered
reads, snapshot counts, rollback by latest/id, factory restoration/deletion,
metatype discovery, password type/value restoration and fork plaintext CDATA.
46 scenarios use encrypted snapshots; the added fork scenario uses plaintext.

The [runner](../../kura-dev-runtime/acceptance/full-runtime-probe/configuration-scenarios.py)
copies an isolated template into a fresh owned home and Equinox configuration
area per case, including relocation of snapshot/bootstrap keystore paths into
that owned copy. The final plaintext snapshot confirms both active filesystem
keystore paths point into its case home. The probe checks the ownership marker
and actual host snapshot
path before invoking `prepare()`. Each owned JVM exited after its result; all
47 cases released ports 18480/18443/18444, with **zero forced shutdowns**. The
33 existing protected personal profile files stayed identical, with no new or
removed files. The runtime template and previously archived profile were not
cleaned or rewritten.

[JSON evidence](mac-complete-configuration-validation-20261010.json) records every
scenario result, source/artifact digest and limit. Raw results, launch commands,
console logs, copied test helpers and build log are archived at
`/Users/heyoulin/iot-kura-develop/migration-baseline/mac-complete-configuration-relocated-suite-20261010`.
The first complete batch also passed 47 assertions, but archival inspection
found two bootstrap snapshot keystore paths still pointing to the stopped
acceptance template. Both template keystore hashes were unchanged. The runner
was corrected to relocate copied profile references, and the final 47-case batch
passed again. The earlier batch, original runner and reconciliation are retained
as diagnostic evidence and are not added to the final count.

The initial one-case plaintext/encryption checks are also overlapping prechecks
and are not added to the 47-case batch. These reflectively invoked
Jupiter assertions are also not added to the 5515 workspace JUnit invocations.

The three configuration inventory rows now meet their complete Mac host-service
acceptance within the user's macOS scope. Installed Debian, hardware and Linux
acceptance are not claimed. The development encryption profile uses the default
test key and emits its existing warning; production master-key provisioning is
outside this evidence. Invocation waits for the scenario's actual SCR fixtures;
unrelated background application services are not independently exercised.

Restoration remains in progress: **465 reviewed sources, zero unreviewed, zero
`deferredScenarios`, 36 rows / 37 strings of `deferredValidation`**. The separate
IDEA JUnit and application Run/Debug/restart evidence remains valid and is not
replaced by this CLI acceptance.
