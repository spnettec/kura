# SecurityService upstream implementation audit

Official remote HEAD was checked on 2026-10-11 and matched the indexed snapshot
and local `origin/develop`: `e500a68d7b3f4a970aca3e13c038947269278827`.
The checked tree contains the SecurityService API, REST callers and mock-backed
endpoint tests. It contains no production provider implementing policy-file
application. The REST SecurityService reference is optional.

History supports the external-provider boundary:

- [2015 UI introduction](https://github.com/eclipse-kura/kura/commit/a4757d07efff3f40c353d67293ee000023347dce)
  explicitly enables the security tab only when an implementor is available.
- [2024 policy API/REST update](https://github.com/eclipse-kura/kura/pull/5230)
  adds default/custom policy application methods and REST V2. It adds no policy
  provider; the endpoint tests register a mock SecurityService.
- [Eurotech ESF policy documentation](https://esf.eurotech.com/docs/security-policy-file)
  describes ESF's XML policy mechanism. That documentation does not supply an
  implementation in the checked Eclipse Kura source tree.

Inventory indices 230/231 therefore require an externally supplied actual
SecurityService provider before policy-file application can be accepted. Their
existing HTTP/MQTT and IDEA results remain valid at the controlled service
boundary. Actual policy-file application remains unverified; no provider or
security feature is added during test restoration. The inventory remains 465
reviewed, zero unreviewed, zero deferred scenarios and 31 deferred-validation
rows/strings. See the JSON companion for source hashes and retained Git evidence.
