# Debian package data retention

Before `kura-core` is removed, its maintainer script stops Kura and copies the
`user/`, `data/`, `packages/` and `log/` trees to `/var/lib/kura-retained`. This
includes snapshots, keys, custom properties, runtime state, deployment packages
and their registry. The systemd service unit is also retained because it can
contain the snapshot master key; local systemd drop-ins remain in place. The
private recovery directory is retained after a normal
package removal; a subsequent installation restores the trees automatically.
Kura files under `/var/log` are left in place on removal and reinstallation.
The installer refreshes its recovery copy of `snapshot_0.xml` after restoration.

Removal fails if a recovery copy already exists or the new copy cannot be
created. An interrupted recovery copy is not overwritten automatically. The
administrator should examine and recover it before retrying. Upgrade recovery
uses the separate `/opt/eclipse/.kura-preserve` directory; if both recovery
directories exist, installation stops instead of choosing between them.
During an upgrade, the new service template is installed while the previous
snapshot master-key and `EnvironmentFile` settings are carried forward.
Files referenced by `EnvironmentFile` outside Kura's managed directories are
not deleted by purge; they may be shared or managed independently.

`purge` removes the installation, retained data, Kura logs, recovery copies and
local Kura systemd configuration. A Debian
conffile keeps the package in the `config-files` state after a normal removal so
that a later purge still invokes the package's cleanup script.

### A pending deployment job can refuse removal

When the resolved deployment registry has a pending publication receipt, Core's
pre-removal hook refuses both removal and direct purge of an installed Core.
The existing installation and the original receipt remain available. Once a
compatible Deployment addon is installed again, query the original cloud job
on the same gateway with the original connection and job ID. An `UNKNOWN`
outcome remains attached to that job. Preserve the receipt and its staged files.

After a refusal, check both the requested selection and the actual package state.

```sh
dpkg-query -W -f='${db:Status-Want} ${db:Status-Status}\n' kura-core
```

A refused remove can leave `deinstall installed`, and a refused purge can leave
`purge installed`. If the operator cancels that maintenance request and intends
to keep Core installed, restore the package selection as root and verify it.

```sh
printf 'kura-core install\n' | dpkg --set-selections
dpkg-query -W -f='${db:Status-Want} ${db:Status-Status}\n' kura-core
```

The expected output is `install installed`. Changing this selection updates
dpkg's requested action and leaves the cloud job and original receipt intact.

For an end-to-end regression test in a **disposable** Debian or Ubuntu VM with
no existing Kura installation or recovery data, run as root:

```sh
KURA_TEST_PACKAGE=/absolute/path/to/kura-core.deb \
KURA_TEST_ALLOW_DESTRUCTIVE=1 \
bash kura/distrib/src/test/verify-deb-retention.sh
```

The test exercises a rejected removal, removal and reinstall with checksummed
snapshots, keys, systemd configuration, state and deployment packages, purge after removal, and direct
purge. It installs and deletes test data and must not run on a real gateway.
