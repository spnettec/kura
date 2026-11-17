# Installed Main, GWT and Root integration

The disposable Ubuntu 24.04 ARM64 fixture installs supplied Core and GWT Debian
packages with their declared dependencies. PID 1 is systemd; Main, Root and
recovery run under their actual service identities. No historical gateway,
operation ID, key, database or acceptance script is adopted.

Build `Dockerfile.installed-main-fixture` as
`yofc-kura-main-archive-tests:ubuntu24.04`, then run
`provision_installed_main_fixture.py --disposable-fixture` with explicit
`--core`, `--core-sha256`, `--ui`, `--ui-sha256` and a new `--results` directory.
It installs once, keeps Main stopped and disconnects the Docker network after
installation. Only loopback remains; local hostname resolution is retained.
Failure retains the same fixture. Do not restart provisioning to hide a failure.

Before the first normal Main start, send `inspect_installed_main_fixture.py` to
the owned container's Python stdin with `--stage before`. That saves a private
hash/stat baseline and refuses any existing operation or startup journal.
Start Main normally and wait for its actual HTTPS endpoint. The browser entry
is `/`, which redirects to `/admin/auth`, then `/admin/console` after login.
`/admin` is a resource prefix, not the login document.

Use the normal initial-account login and password-change UI. For this fixture
only, save its temporary username/password in `fixture-login.json` in the new
results directory, mode 0600. Never put a personal or gateway credential there.

Run `test_installed_main_archive_tab.mjs --disposable-fixture --fixture <results>
--report <new-report.json>`. It verifies the owned UUID container, network and
memory limits, actual credentials and running Main before opening a transparent
TCP relay. The actual GWT bundle, HTTP responses, ADMIN session and Root service
remain in use. It selects the initially hidden key tab, leaves and selects it
again, checks all eight history/status replies, and checks private-file and
process continuity. It never creates a backup, restores a key, archives a
record, publishes, renews or starts a journaled operation. Its browser permits
the isolated self-signed certificate; it does not provide general TLS trust
acceptance. Main retains its existing capabilities, so this is not full
privilege-broker or platform acceptance.

The one new 2026-11-17 installed backup/metadata scenario is closed. Its IDs and
scope are in the management-console checkpoint. Do not recreate that fixture,
repeat the backup or metadata sends, or query those IDs in another Root state.
Future validation starts from current source and a separately justified fresh
fixture. Closed fixture keys, downloaded backups and passwords are disposable;
unknown outcomes and user gateways must instead retain their original state.
