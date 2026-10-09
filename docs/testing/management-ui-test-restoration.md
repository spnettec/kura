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
