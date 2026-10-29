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
