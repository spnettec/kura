# Container upstream test restoration

2026-10-09; core-origin sources pinned to kura@e500a68d and relocated into the
existing kura-container bundles. Branch codex/maven-bundle-idea verified clean at
entry. Project knowledge vault remains unregistered; no global-scope fallback.

## Configuration, descriptors and service options

Four source files restore 19 upstream scenarios and add two local option checks,
21 passing cases with Maven 3.10.0/JDK 21/Jupiter, zero failures/errors/skips.
Production code, docker-java 3.2.12, private Jackson 2.10.3, handwritten metadata
and DS activation remain unchanged. Only a test-scope Jupiter dependency is added.

Required-field exceptions use scoped assertThrows; configuration values, ports,
resources and registry credentials are verified. Generic device mapping fixtures
use ttyUSB names rather than the removed GPIO feature. Descriptor comparisons use
Jupiter collection equality. Options tests preserve local enforcement.enabled /
enforcement.allowlist keys and disabled-by-default empty properties. The old
upstream "default enabled" fixture actually supplied enabled=true; it is renamed
and a genuinely empty-properties case verifies the local false default. Equality
uses distinct equivalent objects; hash checks use the equality contract rather
than duplicating the implementation formula.

## Upstream-only APIs excluded after source audit

- TokenFileManagerTest: all eight tests require the absent token-file manager,
  kura.tmpfs.base layout and associated lifecycle. No token identity feature is
  introduced to run them.
- ContainerOrchestrationActivatorTest: all three tests require the absent Docker
  reachability activator and SCR component-enablement path. Local handwritten DS
  configuration activation stays unchanged.

Graph searches and fallback source/metadata checks confirm both APIs are absent.
These are explicit not-applicable inventory entries, not skipped passing tests.
Six Container source files remain unreviewed. Docker daemon/real container, DS and
IDEA acceptance remain open; the 21 cases do not connect to Docker.

## Docker failure and digest enforcement continuation

Four command-failure and six allowlist scenarios restore the upstream coverage.
An extra case verifies the local per-container digest allowlist fallback through
the actual stored digest map. Seven enforcement cases check accepted/whitespace
allowlists, rejected digests, running/stopped state actions and local fallback.
Mockito and Log4j API are test-only dependencies; Docker commands are mocked and
no daemon connections or event subscriptions are opened. All 32 orchestration cases
pass on Maven 3.10.0/JDK 21/Jupiter, zero failures/errors/skips. Production unchanged.

All 19 ContainerIdentityIntegrationTest scenarios and helpers were also audited.
The local ContainerInstance lacks the identity/password-strength/network bindings,
temporary-password state and token lifecycle used by those scenarios. Its existing
ConfigurationService binding persists signature digests, not container identities; associated container.identity.enabled and container.permissions
metadata is absent too. This source is explicitly not applicable, not silently
skipped, and no identity integration is imported. Three Container sources remain:
service behavior, instance options and instance lifecycle. Runtime/DS/IDEA work open.

## Orchestration service behavior continuation

All 21 upstream service scenarios pass, bringing orchestration to 53 passing
Jupiter cases, zero failures/errors/skips with Maven 3.10.0/JDK 21. Production and
private connect visibility remain unchanged. Scoped Docker configuration/factory
and HTTP transport-construction mocks let the real local connect method run while
preventing daemon access and personal Docker configuration reads. Enabled cases
verify transport construction/host; disabled cases verify no transport construction.

Fixtures now use the actual enabled/container.engine.host keys. The update case
calls updated, deactivation follows activation and verifies client closure. Creation
uses no existing matching container and verifies create/start commands; stopping
verifies the actual stop command. Descriptor assertions compare complete values
(including local empty version for an untagged image); port checks require all three
TCP/UDP/SCTP entries. Legacy repository-property scenarios are named accordingly,
not claimed as registry authentication integration. Generic device fixtures use ttyUSB.
All static/construction mocks are closed; test teardown deactivates the service.

Two Container sources remain: ContainerInstanceOptionsTest and ContainerInstanceTest.
Real Docker containers, SCR and IDEA acceptance remain open.

## Instance options continuation

All 57 upstream option scenarios and one local empty-properties regression pass,
58 cases with zero failures/errors/skips on Maven 3.10.0/JDK 21/Jupiter. They cover
registry credentials, environment/volume/device/port parsing, retry limits,
entrypoint normalization, memory units, CPU/GPU/runtime and enforcement digest.

CPU fixtures use Float values instead of ignored string values. Equal distinct
options now require equal hashes; the upstream check compared against an
uninitialized zero field. Other hash comparisons now use the compared object.
The explicit upstream hello-world fixture stays explicit; truly empty properties
retain local nginx/disabled defaults and absent optional CPU/GPU/registry values.
Only test-scope Jupiter is added to container.provider; production unchanged.
ContainerInstanceTest is the only Container source still unreviewed.
