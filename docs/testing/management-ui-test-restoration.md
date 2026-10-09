# Management UI upstream test restoration

2026-10-09; pinned upstream kura-management-ui@3518ad6e.

## Audit context and scale/offset enum

ConsoleTest was already migrated to Jupiter in the existing org.eclipse.kura.web2.test
module. All five cases were compared with upstream and validated without rewriting
it. ScaleOffsetTypeTest adds eight Jupiter cases; negative inputs use scoped
assertThrows. Full test module passes 13, zero failures/errors/skips with Maven
3.10.0 and JDK 21. Production Web2 and GWT retain their Java 11 target; the existing
separate test module retains release 21. No production or dependency changes.

The tests verify audit remote-address/forwarded-header handling and the supported
scale/offset values, case-insensitive conversion and invalid-input errors. Browser
GWT, servlet/OSGi and IDEA acceptance remain open. Five UI sources are unreviewed.

## Modem password placeholder repair

All four upstream cases now use the local one-argument builder constructor, with a
scoped construction mock only at NetworkConfigurationServiceAdapter. The test verifies
that the constructor requests the correct interface. No upstream constructor/API or
network backend change was imported. Mockito and GWT user are test-scope dependencies.

The non-Modem previous-configuration case failed before the production repair:
the UI placeholder was persisted as the actual Modem password. The builder now
preserves a previous Modem password when present and otherwise omits the placeholder.
Actual replacement passwords retain their existing behavior. This production repair
is a separate commit. The full production Web2/GWT build passes with Java 11 target;
all 17 test-module cases pass on Maven 3.10.0/JDK 21, zero failures/errors/skips.
OSGi configuration wiring, real networking/D-Bus and browser acceptance remain open.
Four UI sources remain unreviewed.

## General configuration password placeholder repair

Eight upstream password cases and four additional caller/local-behavior cases pass.
Seven failed before the separate production repair. An unchanged scalar password
with no stored value now remains unset instead of persisting the UI placeholder or
inventing a default in the UI layer. All three callers omit only that unset
placeholder. Unlike a broad omission of every null password, explicit empty/null
input retains the local clearing behavior. Array conversion is unchanged.

Regression coverage preserves existing/empty passwords, real replacement values,
legacy name-based lookup in fillPropertiesFromConfiguration, ID-based lookup in the
other conversions, and local service PID/Chinese name/description metadata. The
private component-service method stays private and is exercised through reflection.
Full Web2/GWT production build passes with release 11; test module passes 29 cases
(including 12 in this class), zero failures/errors/skips on Maven 3.10.0/JDK 21.
Three UI sources remain unreviewed; runtime/browser/IDEA acceptance remains open.

## Metatype default rendering repair

Nine upstream scenarios and one additional localized rendering case pass. Six
failed before the separate production repair: escaped scalar/array defaults leaked
into UI values and the component-service conversion omitted defaults entirely.
The existing StringUtil metatype decoder now serves all three parameter conversion
paths. Arrays retain escaped comma separators; null/empty defaults and explicit
configured values retain their behavior. No metatype XML or OSGi metadata changes.

The local getLocalizedDefinition path remains in place. Tests reject accidental
getDefinition use in the component-service path and verify explicit zh labels and
descriptions in the locale-aware server conversion. Private methods remain private.
Full Web2/GWT production build passes with release 11; test module passes 39 cases
(7 default decoder/localization, 3 component defaults), zero failures/errors/skips.
One UI source remains unreviewed; browser/OSGi/IDEA acceptance remains open.

## Log ZIP restoration and separate production repair

All 15 upstream scenarios were reviewed. Eight ZIP/entry-name scenarios execute
through the existing private byte-array zipFiles method; no streaming API is
introduced. Two extra cases check a suffix colliding with an existing entry and
actual createReply bytes plus the local fixed Kura_Logs.zip header. A multi-buffer
Unicode fixture checks complete contents. TempDir owns every test file.

Six cases failed before the separate repair: duplicate names raised ZipException,
and a disappeared rotated log raised FileNotFoundException, aborting the entire
archive. A per-archive set now suffixes colliding names while retaining extensions;
files unavailable at open are logged and skipped. Other read/write errors still
propagate. Existing authorization, journal commands/paths and fixed archive name
remain unchanged. No servlet authorization or real journald acceptance is claimed.

Seven upstream-only scenarios are explicitly excluded, not disabled passing tests:
four device/timestamp archive-name/sanitization cases and three private temporary
directory lifecycle cases. Those APIs do not exist locally; importing them would
change the local download/journal design. The existing fixed journal temp paths
and concurrent-download lifecycle remain an open runtime/design limitation.

Full Web2/GWT build passes with Java 11 target; all 49 Jupiter cases pass on Maven
3.10.0/JDK 21, zero failures/errors/skips. All seven UI sources are audited; browser,
servlet authorization, OSGi and real IDEA JUnit acceptance remain open.
