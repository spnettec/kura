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
