# Offline snapshot validation and optional controlled startup

## Empty Password encryption boundary (2026-11-07)

`ComponentUtil` now encrypts an actual empty `Password` instead of treating the
legacy AES decoder's successful empty-input return as proof of ciphertext.
Scalar, array, Vector and List elements use real AES-GCM ciphertext, including
the authentication tag for empty plaintext. An already authenticated ciphertext
is retained, and the caller's cleartext object is unchanged. The XML format and
the legacy decoder's read compatibility are unchanged.

This does not relax `--password-policy authenticated`. Existing snapshots can
still contain historical clear/Base64-only values; their audited baseline policy
must remain an independent explicit choice. A normalized uploaded candidate must
pass its own fixed policy. Wrong-key ciphertext for an empty password is refused
under both authenticated and legacy policies. Unit validation alone does not
prove Kura business restoration or complete provider coverage.

## Container format increment (2026-11-07, development validation)

Historical scalars and boxed arrays retain their existing XML representation.
An optional `container` attribute, only with `array="true"`, distinguishes
`PRIMITIVE_ARRAY`, `VECTOR`, and `LIST`. Primitive arrays retain their primitive
component type; Vector retains its XML round-trip representation. Other homogeneous
collections normalize to an ordered ArrayList, including empty collections. CM/SCR
may deliver a different Collection implementation; element types, order, duplicate
values and emptiness remain the contract. Empty arrays are now persisted rather
than silently omitted. An empty scalar still means null.

Both DOM and stream writers/readers and the standalone validator share this
representation. Password collections follow the same AES/type conversion as scalar
Password and Password arrays. Unknown objects, nested containers, mixed element
types and null elements are refused instead of producing a partial snapshot.
New container-bearing snapshots require the matching updated mapper and validator;
compatibility with old *readers* is not claimed. Existing snapshots without the
attribute remain readable. Runtime profiles must pin the matching artifacts.

This increment does not establish complete component/provider/metatype coverage,
business recovery, formal release compatibility, or `fullRecoveryVerified=true`.

This short-lived Java 21 tool reads persisted Kura snapshots without starting OSGi,
activating components, loading business scripts, changing Configuration Admin or
publishing a snapshot. It uses the real Kura XML/property adapter and AES-GCM
implementation, with an explicit crypto dependency instead of an OSGi lookup.
The default constructors used by the running gateway retain their existing lookup.

Build from the repository root, using the same Maven cache as Kura:

```sh
mvn -o -pl :org.eclipse.kura.core.crypto,:org.eclipse.kura.core.configuration,:org.eclipse.kura.xml.marshaller.unmarshaller.provider,:kura-offline-recovery -am install -Dmaven.repo.local=/absolute/cache
```

Keep the resulting JAR and its `target/lib/` together. Select the actual deployment
key explicitly; no system properties, environment variables, running Kura service,
key generation or fallback to a different key are used:

```sh
java -Xmx256m -XX:+ExitOnOutOfMemoryError -jar /absolute/tool/kura-offline-recovery-1.0.0-SNAPSHOT.jar validate \
  --input /absolute/staging/snapshot.xml --mode plain --key-file /absolute/private/kura-key
```

`--key-file` reads the exact raw 16/24/32 bytes, without trimming or Base64 decoding.
The file must be a regular non-symlink with no group/other permissions. Use a
private directory controlled by the invoking administrator. Keys never appear in
arguments or output. `--default-key` is a mutually exclusive, explicit choice for
an existing deployment that actually uses Kura's legacy default AES key; it never
changes the running deployment key. Whole-snapshot encryption requires
`--mode aes-gcm`; auto-detection and plaintext fallback are intentionally absent.
Decryption is authenticated and bounded in memory, with no plaintext temporary file.

The generation-aware internal validator additionally accepts an explicit
`--keyring-file` and `--keyring-sha256` pair instead of `--key-file` or
`--default-key`. The binary ring follows the Core generation-reader contract and
is bounded to 512 bytes. Its independently supplied lowercase SHA-256 must match;
there is no adjacent-file discovery or fallback. Key/ring files must have one
hard link, private permissions and stable metadata, inside a directory with no
group/other write permission. These are internal validator parameters, not a
released gateway installation or GUI rotation procedure. The agent's current
single-key preflight has not been extended to acquire Root-owned generation keys.

The default `--password-policy authenticated` requires every Password
value to authenticate with the selected key, including direct AES and the Kura
Base64-wrapped AES representation. A zero-value scalar denotes null; a zero-value
array/collection denotes an empty container. Neither contributes an authenticated password. For audited historical
snapshots containing cleartext or Base64-only Password values, explicitly add
`--password-policy legacy`. Ciphertext with a normal AES IV or versioned KURA prefix still must
authenticate; wrong-key ciphertext is never reclassified as a legacy password.
Legacy compatibility does not establish that every password is encrypted.

Only the persisted configuration format is accepted: `esf` namespace/prefix,
configuration PID, one properties group per configuration, known property types,
scalar/array values, and optional boolean flags (absent means false, as in Kura's
stream writer). The unused `ocd` namespace declaration emitted by Kura is accepted;
OCD metadata/export documents are not persisted snapshots and are rejected.
Duplicate PIDs/properties, unknown content, invalid flags/types/cardinality,
non-finite floating values, DTD/entities/processing instructions and excessive
structure are rejected before the real mapper converts values. Limits are 32 MiB
input/decrypted bytes, depth 5, 400,000 XML events, 4,096 configurations,
65,536 total properties/values and 1 MiB text per value. Keys have a separate 32-byte
limit (512 bytes for the explicit generation ring). Files are read-only; symlinks at the input/key leaf are refused.

Exit 0 writes one JSON report with artifact SHA-256 and counts; exit 2 writes only
`{"error":"SNAPSHOT_VALIDATION_FAILED"}` to stderr. XML values, passwords, paths and
exception messages are never printed by the tool. Missing/broken JVM dependencies
and resource exhaustion are process-level failures and must also block recovery.
`keyAuthenticated=true` means whole-snapshot or at least one password authenticated;
consult the legacy count to understand other fields. Plain XML without authenticated
passwords cannot prove key correctness. `fullRecoveryVerified` is always false.

## Optional controlled startup (increment 2)

The same JAR also has an OSGi Bundle-Activator. Normal startup without
`-Dkura.recovery.request=/absolute/private/request.properties` is a no-op.
Standalone `validate` remains read-only and never starts OSGi. The Rust agent
now invokes standalone validation in its recovery preflight. An optional fixed
startup grant publishes this request and verifies the CM application receipt,
then remains AWAITING_COMPLETION with writes blocked. CM-aware compensation,
business health and transaction finalization are still pending.

This is an experimental startup profile, not an installed release. The bootstrap
must run at framework level 1 before business activation, with the standard
launcher targeting level 5. It holds SCR and business bundles at level 50,
initializes only the required logging and Configuration Admin infrastructure,
then uses Configuration Admin APIs to replace Kura-managed records. It retains
factory identities when compatible, removes missing managed instances and stale
properties, and preserves unrelated unmanaged records. Ambiguous identities,
unmanaged collisions and unsupported values fail before mutation. The 2026-11-07
container increment supports primitive arrays and homogeneous collections through
the shared XML adapter; arbitrary objects, nested containers, mixed element types
and null container elements are rejected before mutation.

The administrator-controlled request is a private regular file, at most 16 KiB,
with LF-separated `key=value` entries and no duplicate or unknown keys:

```properties
schema=1
restore.id=rec-00000000-0000-0000-0000-000000000000
snapshot.path=/absolute/kura-home/user/snapshots/snapshot_123.xml
snapshot.sha256=<64 lowercase hex digits>
snapshot.mode=plain
password.policy=authenticated
receipt.path=/absolute/private/applied.properties
crypto.key.file=/absolute/private/original-kura-key
```

Use exactly one of `crypto.key.file` or explicit `crypto.default=true`. Existing
key and password-policy semantics are the same as standalone validation. Paths
must be absolute, leaf symlinks are rejected, and immediate parent directories
must not be group/other writable. Administrators must also control ancestor
paths and the startup profile. The snapshot must be the exact admitted artifact
and no higher numbered snapshot may exist. The deployment must use the same
original Kura key; provisioning that key to this profile is not yet automated.
Profiles with `kura.configuration.external.pids` are rejected until current Rust
network/firewall authority can be injected safely.

Before changing CM, the bootstrap publishes a create-only bundle-level ledger
and an AES-GCM encrypted API-level backup beside the receipt. It never edits
CM's private database. Receipt `CM_APPLIED` records the restore ID, artifact and
backup hashes, and per-PID actions. It explicitly says
`fullRecoveryVerified=false` and `businessHealth=UNVERIFIED`. Only after this
step does the bootstrap restore business levels and let the standard launcher
advance. Core ConfigurationService loads the admitted configuration directly,
without merging old CM values or falling back to older snapshots. Ordinary
configuration, factory, snapshot and rollback writes remain blocked for the
entire controlled JVM lifetime; no implicit acknowledgement is provided.

Any failure stops the framework, retains state and attempts a create-only
`RECOVERY_REQUIRED` receipt. Existing receipts/ledgers/backups are never
replayed or overwritten. A partial CM mutation requires explicit compensation;
Agent transaction integration for API-level compensation, bridge/business health
and completion that releases writes remain pending. The agent request/CM receipt increment preserves this
nonterminal boundary. Do not remove the request
or restart normally as a substitute for completion. Tests establish selected
real DS business restoration, not complete component or gateway recovery.

## Compensation evidence and experimental inverse startup (increment 3)

Before its first CM mutation, bootstrap now persists an encrypted exact CM intent
(`.cm-intended.aes`), the original encrypted CM backup and a create-only
`.cm-plan.properties` anchor binding restore ID, source snapshot hash, backup hash
and intent hash. The intent converts Password/Password[] to the exact CM String
representation, preserving randomized ciphertext. Re-decoding/re-encrypting a
snapshot cannot reconstruct this representation. After a verified application,
`.cm-applied.aes` captures actual managed CM records; CM_APPLIED includes its
`applied.sha256`. Pre-mutation backups must fit the offline reader's 32 MiB artifact limit before
CM mutation; the actual applied-state copy has the same bound. In-memory
XML/encrypted buffers are wiped.

An experimental inverse request adds all three fields:

```properties
compensation.source.receipt=/absolute/private/original-applied.properties
compensation.source.receipt.sha256=<exact original decision hash>
compensation.source.plan.sha256=<exact pre-mutation plan hash>
```

Its new highest `snapshot_N.xml` is an exact copy of the original `.cm-backup.aes`
and uses `snapshot.mode=aes-gcm`. A new restore ID/request/receipt is required;
original evidence is never overwritten/replayed. Bootstrap authenticates and
checks the retained source decision/plan/backup/intent before calling public CM
APIs in reverse, with SCR/business still held. Original records are recreated,
new records removed and stale/changed properties restored. Current records must
be wholly original or intended, or absent only where delete/create can account
for absence. Unknown managed identities, changed values, missing retained
in-place records and unmanaged collisions reject before inverse mutation. A
fresh backup/plan is saved before the inverse itself mutates CM.

These Java helpers/source checks have unit and real Equinox persistence contracts.
Native IDEA full-Kura and subsequent Orb validation passed for selected real DS
forward/inverse activation and original GWT login. Each exact CM audit restored
26 managed configurations and 187 properties, including original ciphertext.
A wrong source-plan hash rejected before CM mutation/business activation.
Agent re-open with Kura stopped retained evidence, entered RECOVERY_REQUIRED
and blocked upload without replay. All new test processes are stopped. The inverse branch is not yet wired into agent's
rollback workflow and does not release ordinary writes or establish business
health. The helper can compensate to an originally empty managed set, but the
bootstrap's nonempty snapshot admission still rejects an empty source backup;
that startup edge remains pending. Complete snapshot-file compensation,
agent transaction binding and explicit completion are also pending. Do not use
normal boot or journal changes to substitute for those unfinished steps.

## Guarded ordinary loading (2026-11-06 development phase)

A separately granted `verification.mode=normal-read-only` request authenticates
the exact inverse CM evidence before SCR, then admits Kura's original snapshot/CM
loader while retaining all ordinary-write gates. It emits NORMAL_BOOT_ADMITTED,
not CM_APPLIED or recovery success. The optional bundle remains inert without a
request. Baseline format policy is independently explicit; authenticated upload
policy is never automatically downgraded for historical passwords. The agent
contract and nonterminal boundaries are in
`../../../../kura-management-agent/docs/guarded-normal-startup-v1.md` (workspace sibling).

## Authenticated empty-original CM inverse (2026-11-07, d1994c05)

The optional bootstrap can restore an originally empty Kura-managed CM set only
as the inverse of a retained, authenticated application. It authenticates the
source receipt/plan and exact original AES-GCM backup before using the dedicated
retained-backup decoder and compensation admission. The ordinary `validate` CLI,
upload decoder, apply, and admission continue to reject empty targets. There is
no caller-supplied `allowEmpty` option. The pure expected-value projection can
represent an empty set; it does not admit or perform an ordinary write.

An empty inverse retains the snapshot hash/highest-file checks and ordinary-write
gate. It preserves foreign CM records and cannot fall back to an older snapshot
or seed missing defaults. It does not authorize normal boot, health acceptance,
completion, or write release for an unconfigured gateway. Actual evidence and
remaining scope are recorded in the console review
`docs/reviews/empty-original-cm-inverse-20261107.md`.

## Versioned logical passwords (2026-11-08)

`passwordEncoding="BASE64_LOGICAL_V1"` is the current Core snapshot format.
Base64 represents logical password characters and is never evidence of AES
authentication, including when the decoded text happens to resemble ciphertext.
The tool preserves those logical values and containers using the actual Kura
mapper. Unknown encodings, invalid Base64 or invalid UTF-8 are rejected.

The default `authenticated` policy accepts V1 passwords only when the whole
artifact has actually passed AES-GCM authentication. A private validator grant
may explicitly select `passwordPolicy: "logical-v1"` for a plain V1 snapshot.
The latter reports `logicalPasswordCount`, the exact `passwordEncoding` and
`keyAuthenticated: false`; it does not claim password or artifact authentication.
The existing `legacy` policy does not silently opt into V1. Unmarked legacy
password authentication and wrong-key failures keep their existing contract.
Normal-startup validation needs its own appropriate fixed policy as before.

The optional bootstrap additionally requires snapshot.codec 1.x, whose provider
requires password.sources 1.x. This format support does not authorize business
health, write release or ordinary unit handoff.

The generation-aware bootstrap also requires `kura.crypto.key.generations` 1.x.
Its private request may explicitly select `crypto.keyring.file` and
`crypto.keyring.sha256` instead of `crypto.key.file` or `crypto.default`; the
same bounded private reader validates the material. The current agent request
allowlist remains single-key and cannot produce this new selection yet. Complete
package/cohort acceptance and a Core-owned delegation path remain release gates.

When a logical-V1 snapshot is converted to CM properties, every logical Password
is encrypted exactly once, including an empty value or text that happens to be
valid ciphertext. Scalar, array, Vector and List representations retain their
logical values without modifying the source. Unmarked authenticated ciphertext
retains its original representation through the existing CM conversion helper.
