# Shared request test helpers

Five upstream helper sources are restored in `build-support/kura-test-support`:
`Transport`, `TransportType`, `AbstractRequestHandlerTest`, `RestTransport` and
`JsonProjection`. They have no standalone upstream test cases; six new Jupiter
fixture checks validate their behavior over a real loopback HTTP server.

The shared artifact uses the already managed minimal-json and Jupiter API versions.
Its existing main-repository consumers all declare test scope, so these helpers are
not added to production bundle contents or imports.

The HTTP helper requires an explicit server prefix and service path. Initialization
no longer discovers services, changes live Kura configuration, assumes port 8080 or
continues after a failed readiness probe. The owning scenario starts/registers its
services and supplies its private port. Authentication is explicitly supplied;
hostname verification defaults to enabled. Callers can still supply an SSL context,
headers, cookie store and an explicit hostname-verification setting for TLS tests.

Requests have positive bounded connect/read timeouts, preserve UTF-8 request/error
bodies, do not follow redirects, close upload/download streams and disconnect even
on failure. Cookie state is per fixture and cleared by `close`. Port probes use
bounded socket connects and deadlines. No MQTT implementation is claimed by the
transport enum: `MqttTransport` and actual runtime service-discovery helpers remain
pending and are separate inventory entries.

The assertion helper now accepts only 2xx as success (the original integer division
also accepted 3xx). Cookie rotation requires both captured and current cookies to
exist, preventing deletion alone from passing. Jupiter replaces JUnit 4 assertions.
Transport type is reported through its interface so the helper does not require
loading a concrete MQTT/OSGi runtime merely to make HTTP assertions.

Validation: Maven 3.10.0 / Temurin 21; six passing tests and isolated installation,
zero failures/errors/skips. Checks cover UTF-8 DELETE bodies and authentication,
case-insensitive headers, empty/error responses, redirect rejection, isolated and
replayed cookies, read/port timeouts, JSON composition/matching and method mapping.
Endpoint integration, OSGi discovery, MQTT runtime and IDEA acceptance remain open.
