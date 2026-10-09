# Password change must preserve the authenticated identity

`SessionRestService.updateUserPassword` passed the new password as the username
when creating the replacement session. Ordinary changes therefore left the session
bound to a nonexistent identity; a password equal to an existing identity name
instead selected that identity and its permissions.

The replacement session now uses the original authenticated username. The password
still changes through the existing identity/password-policy path, and the session
is rotated and unlocked as before. No API, OSGi metadata or dependency changes.

Two actual Jetty/Jersey HTTP regressions first failed on the old implementation:

- A required password change keeps the original identity and permissions and allows
  subsequent resource access without logging in again (upstream scenario).
- A new password matching a different administrator identity still keeps the original
  identity and its limited permissions (local regression).

Both check the changed password, rejection of the old password, current identity,
permissions, unlocked state, XSRF access and the protected resource. The fixture uses
real identity/role/password logic and a private cookie store per test.

Validation: Maven 3.10.0 / Temurin 21 / JUnit Jupiter; both negative confirmations
failed before the fix. All **56 REST provider tests** and isolated bundle installation
pass after the fix, with zero failures/errors/skips. Actual Kura SCR/HTTP whiteboard
assembly, deployed cookie policy and IDEA execution remain separate acceptance work.
