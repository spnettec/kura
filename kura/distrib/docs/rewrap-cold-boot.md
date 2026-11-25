# Continue an issued provider rewrap after a cold boot

`/run/kura-key-service/writers/lease.lock` is a volatile kernel-lock coordinator.
After a normal shutdown it may not exist until the first managed writer starts.
A pending rewrap intentionally blocks that ordinary start. Maintenance therefore
creates the empty coordinator, with the existing Root ownership and 0600 checks,
before acquiring its nonblocking exclusive flock. It preserves every existing
coordinator; a nonempty, exposed, linked or otherwise untrusted file is refused.
The containing service runtime directory must still be managed and valid.

This creates no writer registration, key operation, intent or success receipt.
Ordinary writers still pass the unresolved-operation gate and must acquire a
shared flock on the same inode. Publication and handoff recovery retain their
original boot and inode checks; creating a fresh volatile lock does not adopt an
old owner or settle an uncertain dispatch.

For an existing snapshot operation, use `--snapshot-rewrap read` with its original
operation UUID, namespace digest and snapshot number on its original Root. Keep
the signed intent, pending marker, archived original and complete package inputs.
`UNKNOWN` is an observation, never permission to run `apply` again.

When the original `apply` already replaced the snapshot but did not complete its
receipt, `continue` authenticates the original intent and installed cohort. It
rechecks the publication, explicit start grant, stopped Main and Agent bindings,
then accepts only the exact inode and bytes recorded for the staged replacement.
It syncs that existing replacement and publishes the original operation's
completion receipt. It does not run the Java rewrap worker or replace the snapshot
again. A rejected continuation leaves the operation unresolved.

## Recover an older installed package

An older installed entry point may fail with `PROVIDER_STORE_REWRAP_REFUSED`
because its exclusive-writer path opens an absent coordinator without creating
it. Preserve the refusal and confirm the missing volatile directory through
read-only diagnostics. Do not patch the installed code, create a receipt, start
Main through a pending fence, or replace the original operation UUID.

The corrected CLI can be run directly from an unpacked, Git-built ARM64 Core
candidate. Retain and verify the complete candidate archive, Git revision and
every extracted Python source digest before running its entry point with Python
isolated mode. Keep the installed package, manifest and all persistent original
records in place. The candidate Manager loads the generation module from that
installed manifest and verifies its exact bytes; it does not substitute a newer
cohort for the one bound by the original intent. This compatibility path changes
only the absent volatile coordinator before the normal original-id continuation.

Run the candidate CLI with the same original arguments:

```text
python3 -IB <verified-candidate-bin>/kura_key_service.py --snapshot-rewrap continue <original-uuid> <original-namespace-sha256> <original-snapshot-number>
```

This path is suitable only when the candidate's audited change is compatible with
the installed generation module and original signed fields. Retain the source
and package comparison as part of the specific recovery record. A different
schema or cohort requires its own reviewed migration; this procedure grants no
general cross-cohort recovery.

Read the original result with the installed CLI. Verify unchanged snapshot inode,
intent and archive, removed pending, one actual completion publication, and no
second Java rewrap or snapshot replacement. Then verify provider behavior from
the retained configuration through a legal Main, stop services normally and cold
read the same Root again. Tests cover cold-boot lock initialization, actual shared
and exclusive Linux locks, preservation of pending journals, and refusal of
untrusted existing coordinators.

## Install the corrected package after completion

A normal published-generation upgrade still needs the original installed manifest
as a `KURA_PUBLISHED_GENERATION_PREDECESSORS` build input. The package builder
accepts the reviewed service-source transition from a047e63 to d016e78 by its two
exact SHA-256 values. The only service change is volatile exclusive-lock
initialization. Other service edits and the reverse transition stay byte-bound;
reader, unit, writer-protocol and all other stable-asset checks remain in force.
The generated package records the complete original manifest digest, not a
general permission to accept arbitrary service or cohort changes. Retain both
package archives, the supplied predecessor manifest and its source digest before
the native upgrade. The original rewrap must already be terminal; never install
through a pending fence or retry an issued rewrap to obtain a new upgrade scene.
