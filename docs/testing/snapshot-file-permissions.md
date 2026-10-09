# Snapshot permissions regression

The restored upstream `testWriteSnapshotFilePermissions` exposed a local snapshot file creation difference: the fork used `FileOutputStream` with the process umask, producing `644` on this development machine. Upstream `e500a68d` creates private snapshot files and the test expects `600`.

The fork now creates new POSIX snapshot files with owner read/write permissions and tightens the same permissions before overwriting an existing snapshot. This applies to both `kura.snapshots.encrypt=false` and the default encrypted path. Paths that are not regular files are rejected before writing. The snapshot encryption switch, XML layout, password handling and corrupt `.bad` preservation are unchanged.

The existing `SnapshotPersistenceTest` checks actual file permissions for default/true/false settings, deliberately widens a saved file to `644`, then confirms a second write restores `600` without changing the expected data. The restored cross-module snapshot test covers the upstream file creation expectation too. POSIX permission acceptance is for macOS/Linux; no Windows ACL behavior is claimed.
