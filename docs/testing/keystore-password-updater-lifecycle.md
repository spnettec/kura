# Filesystem keystore password updater lifecycle

While restoring the real keystore endpoint fixture, source review found that
FilesystemKeystoreServiceImpl deactivation cancelled a scheduled password update
but never shut down its owning executor. Once random password activation starts
that worker, service removal can retain its thread.

Two parameterized regression cases activate the actual service in a temporary
PKCS12 store with randomization disabled/enabled. The latter confirms the pending
configuration update was scheduled and is cancelled at deactivation. Both then
require the owned executor to be shut down and terminate within two seconds.
The pre-fix run failed both shutdown assertions (2 failures, no errors); test-only
finally cleanup prevents the negative run leaking resources.

The production change shuts down the executor during deactivation, before the
existing base CRL cleanup. It does not alter password generation/storage, update
scheduling, crypto policy, local metadata or API behavior.

Validation: Maven 3.10.0 / Temurin 21, isolated repository. All 78 keystore unit tests
and installation pass, including the two regressions, zero failures/errors/skips.
Deployed lifecycle and endpoint integration remain separate validation work.
