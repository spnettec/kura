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
