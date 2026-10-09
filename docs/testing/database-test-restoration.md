# Database upstream-test restoration

The 28 upstream MessageStoreProviderTest scenarios run against both actual H2 and
SQLite providers (56 executions). They cover complete message metadata/payload,
identity overflow, publish/confirm/drop states, priority/age selection and retention.
The old test bundle is not reintroduced: a shared abstract Jupiter contract source
under build-support/message-store-tests is compiled into each existing provider's
test sources using build-helper 3.6.2. Concrete fixtures replace OSGi factory tracking,
use in-memory databases and deactivate providers after each case.

Retention fixtures age actual SQL timestamps instead of sleeping for two seconds.
The upstream topic assertion now respects its requested message index. Production SQL,
identity behavior and handwritten OSGi metadata are unchanged. Real SCR/factory
registration, runtime persistence/restart behavior and IDEA acceptance remain open.

Three SQLite test sources already marked restored were compared with their
upstream originals and reviewed against the current implementation: loader 21,
options 4, activator 6 cases. They are not counted as newly restored sources. The activator suite left org.sqlite.tmpdir pointing at
an unavailable directory; the first full run then failed all 28 new SQLite contracts
with database initialization/JNI errors. Each case now restores the original property,
and Jupiter owns the temporary directory. The full suite passes with all 59 SQLite
cases and all 41 H2 cases (100 total), zero failures/errors/skips, on Maven 3.10.0/JDK 21.

Loader tests retain their mocked JDBC boundary for encryption-key selection, SQL
rekey/vacuum/checkpoint commands and CryptoService updates. They do not demonstrate
actual SQLite encryption support. No production encryption feature is added or changed.

## SQLite persistence and debug-query continuation (2026-10-10)

Three additional source entries are audited: 16 service cases, six debug-query cases
and their shared fixture. Full SQLite suite passes 81 cases, zero failures/errors/
skips on Maven 3.10.0/JDK 21/Jupiter. No production, POM or metadata changes.

Tests execute native SQLite and Hikari against Jupiter-owned temporary database files.
They verify rollback/WAL sidecars, checkpoint truncation, vacuum shrinkage and disabled
maintenance, journal-mode changes, duplicate path rejection and corrupt-file reset or
preservation. Captured scheduler callbacks replace six ten-second sleeps while real SQL
still runs; scheduled initial/period units and executor shutdown are checked. Every
provider and connection closes before its temporary directory is removed.

Debug-shell cases call the actual query entry point with real SQL; access defaults,
updates, typed tabular output and query failures are verified. Output capture restores
System.out in finally and holds a Jupiter resource lock. This does not restore the
deleted Kura Command API/UI. Felix Gogo parsing and OSGi service registration remain
runtime acceptance items. The upstream native-extraction test scans the whole shared
java.io.tmpdir and requires the OSGi activator; its runtime placement assertion remains
explicitly deferred. Existing six activator unit tests are not counted again.
