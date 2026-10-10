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


## SQLite native placement in actual Equinox (2026-10-10)

The previously deferred `shouldNotExtractNativeLibrariesInJavaTempdir` now runs as
`SqliteNativeRuntimeIT`. It installs the actual SQLite provider, util, Xerial JDBC
3.47.1.0 and HikariCP 5.1.0 bundles into the existing isolated Equinox fixture.
The controller classpath contains neither Kura database API nor the SQLite driver.

The real activator selects its bundle data area for `org.sqlite.tmpdir`. Actual
SCR/ConfigAdmin activate an in-memory database after configuration arrives; the
bundle-loaded BaseDbService returns a real JDBC connection and `SELECT 42` returns
42. Assertions check native mode, package providers, an actual extracted native
file in bundle storage, and absence of SQLite native files in an isolated
`java.io.tmpdir`. Stop unregisters the service and clears the activator override;
all original system properties are restored. CryptoService is a controlled required
reference and fails on unexpected business calls; this case does not exercise keys
or encryption. No production source or metadata changed.

Maven 3.10 / JDK 21 targeted reactor validation passes, including the new runtime
case and existing SQLite tests. This resolves the last named `deferredMethods`
entry in the source inventory; other deferred scenario/validation fields remain
open. Runtime coverage is not a claim of deployed database or IDEA GUI acceptance.
