# REST authentication and session upstream restoration

All **63** methods in upstream `RestServiceTest` at
`e500a68d7b3f4a970aca3e13c038947269278827` now run with Jupiter against actual
loopback Jetty/Jersey HTTP endpoints. No upstream test method is omitted.

Coverage includes route absence, public/protected resources, basic authentication,
custom provider lifecycle and priority, authentication switches, password and
certificate login, XSRF, logout, required password changes, password policy, identity
information, login banners, inactivity expiry/extension, credential changes, cookie
rotation/replay, failed login invalidation, audit IP and error JSON.

Certificate scenarios perform actual mutual TLS with separate ephemeral CAs,
PKCS12 key stores, RSA keys and signed client/server certificates. The server requires
a trusted client certificate. The client validates the server certificate chain and
hostname; there is no trust-all manager or hostname bypass. Certificate CNs drive
the actual production authentication providers. HTTP and HTTPS use the same
`localhost` host and private random ports rather than shared 8080/9999 listeners.

## Adaptations and boundaries

- The existing real-HTTP fixture now supports additional Jersey resources and a real
  `LoginBannerServiceImpl`; production REST filters/resources still come from
  `RestService.activate`. JWT and prior password-change tests share the fixture.
- Identities and permissions use the current local identity API and actual Felix
  roles. Password-policy tests model credentials created under an earlier policy:
  fixture setup creates them under a permissive policy, then restores the required
  current policy before any HTTP password-change request. No production policy is
  weakened. Certificate-only identities explicitly have no password credential.
- Permission response order is compared as a set. Cookie rotation asserts a cookie
  exists and changed; replay requests explicitly send the captured old cookie.
- The three inactivity tests retain bounded real waits, including activity extending
  the lifetime. HTTP requests have five-second deadlines and tests have a 30-second
  bound. Each test closes its clients and stops/destroys the server and thread pool.
- Two irrelevant upstream `access.banner.enabled` settings (on password-policy/Web UI
  components) are omitted; real pre/post-login banner cases remain intact.
- Provider binding and configuration callbacks are invoked directly. Jersey resource
  registration/reload substitutes for OSGi whiteboard service discovery; temporary
  JDK key stores substitute for persistent KeystoreService factories. Actual Kura
  SCR/whiteboard/HTTP-manager assembly, persistent stores, deployed cookie policy
  and IDEA execution remain separate acceptance work.

Validation: Maven 3.10.0, Temurin 21, JUnit Jupiter; **119 REST provider tests**, zero
failures/errors/skips (63 restored here plus 56 existing). This batch changes only
tests and audit records. Production sources, OSGi metadata and dependencies are
unchanged. All inventory sources for this test module are now audited; runtime and
IDEA acceptance are not declared complete.
