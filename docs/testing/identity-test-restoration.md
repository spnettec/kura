# Identity upstream test restoration

Three sources from `org.eclipse.kura.core.identity.test` at upstream
`e500a68d7b3f4a970aca3e13c038947269278827` are audited against the local API.

`IdentityServiceImplTest` restores **71 of 73 upstream methods** using actual
`IdentityServiceImpl`, `PasswordStrengthVerificationServiceImpl`, Felix 1.0.4
`UserAdminImpl`, `RoleRepository` and roles/groups. It covers identity and permission
creation/deletion/listing, naming limits, membership changes, password configuration
and validation, and additional configuration extensions. The extension service
bindings are invoked directly and cleaned up after each test.

`IdentityServiceTestBase` supplies isolated role persistence and crypto boundaries:
a per-test memory store and a mock CryptoService backed by JDK SHA-256. It does not
claim to test the installed crypto provider or persistent UserAdmin configuration.
No live identities, global service registry or scheduler are modified.

Adaptations preserve the local contract:

- Supply `ComponentConfiguration.getLocalizedDefinition`, required by local i18n.
- The overlong identity case now submits 256 characters; upstream accidentally
  submitted spaces, leaving the intended boundary untested.
- Rename the identity-name/password equality case to describe its actual short
  password input; it does not establish a separate username-equality policy.
- Use Jupiter assertions and explicit per-test fixtures. Felix's old framework and
  compendium transitives are excluded; existing OSGi APIs remain in use.

## API exclusions and acceptance still required

The two excluded methods require absent `createIdentity(IdentityConfiguration)`
and temporary identity APIs. The separate `TemporaryIdentityServiceTest` source
also requires absent `createTemporaryIdentity(name, Duration)` and is not imported.
Its ordinary nonexistent-identity deletion behavior is already covered by
`shouldReportIdentityNotExistingOnDeletion` in the restored suite. No temporary
identity functionality or container integration is added.

Full identity module: **87 tests, zero failures/errors/skips**, Maven 3.10.0,
Temurin 21, JUnit Jupiter. This includes the 16 previously restored password-policy
cases; they are not counted as newly restored sources. Production code and OSGi
metadata are unchanged. Actual SCR binding, persistent role store, authentication
transport and IDEA execution remain separate acceptance work.
