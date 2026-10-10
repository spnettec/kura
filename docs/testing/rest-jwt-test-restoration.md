# REST JWT upstream test restoration

Five scenario sources and five helper sources from `org.eclipse.kura.rest.provider.test`
at upstream `e500a68d7b3f4a970aca3e13c038947269278827` are restored under JUnit Jupiter.

| Source | Passing scenarios |
| --- | ---: |
| AccessTokenAuthenticationTest | 8 |
| IssueTokenPairTest | 6 |
| JwtAuthenticationConfigurationTest | 7 |
| RefreshTokenPairTest | 10 |
| RefreshTokenReplayTest | 1 |

The 32 new scenarios send actual HTTP requests to Jetty 12.1.8/Jersey 3.1.9 on a
loopback random port. `RestService.activate` creates the production filters,
serializers, exception mapper, session and JWT resources. The fixture registers
those instances with Jersey and exercises actual route matching, servlet context
injection, authentication, authorization, JSON, status codes and response headers.

The stack uses real `IdentityServiceImpl`, password policy, Felix UserAdmin/groups,
`CryptoServiceImpl` hashing, JWT 4.6.0 signing and verification, and newly generated
RSA keys/X.509 certificates. No production sources, dependency versions or OSGi
metadata change; new dependencies are test scoped and use existing managed versions.

## Fixture adaptations

- Original `jwt-alice` was created directly in UserAdmin, bypassing identity name
  validation. The new fixture uses valid `jwt.alice` and the public local identity
  API, followed by configuration update. No new identity API is introduced.
- Each scenario owns the server, HTTP client, identities and token services.
  Clients close; Jetty and its thread pool stop; REST registrations unregister;
  issuer and verifier deactivate even after test failure. Requests have five-second
  deadlines and scenarios have a 30-second bound.
- The original two-second replay wait remains because the test intentionally crosses
  actual token expiry. An added check proves the expired first token is still
  accepted by the real verifier's clock-skew tolerance before REST rejects its
  replay, preventing an expiry-only false positive.
- Signing-key misconfiguration, JWT disable/enable, unbinding/rebinding, malformed
  headers, forged signatures, permission changes, deleted identities, body-size
  limits and refresh recovery retain their original assertions.

## Remaining acceptance boundaries

The OSGi registration boundary is captured and configuration updates call the real
service directly. DS target-matching cases invoke its binding callbacks; they do not
claim actual SCR filter evaluation. UserAdmin storage is per-test memory, event
dispatch is mocked, and KeystoreService exposes real key material through a mock
boundary. Persistent keystore factories, the deployed OSGi HTTP whiteboard, TLS,
full Kura runtime assembly and IDEA execution remain separate acceptance work.

Validation: Maven 3.10.0 / Temurin 21, **54 module tests, zero failures/errors/skips**,
including 22 existing cases. The password-change source was subsequently restored with a separately committed
production fix; see `rest-password-session-fix.md`. The larger `RestServiceTest`
source was subsequently restored with 63 scenarios, including real mutual TLS; see
`rest-authentication-test-restoration.md`. Runtime assembly and IDEA acceptance
remain open.
