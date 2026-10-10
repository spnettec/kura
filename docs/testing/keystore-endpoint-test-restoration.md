# Keystore endpoint restoration

All eight upstream V2 private-key scenarios run over actual HTTP and MQTT: 16
passing invocations, zero failures/errors/skips, Maven 3.10.0 / Temurin 21.

The tests upload and update entries with one- and two-certificate chains, retain
the private key when replacing the leaf certificate, and reject missing request
fields. Real RSA keys/certificates and temporary filesystem PKCS12 stores are used.
HTTP and MQTT use their actual separate endpoint implementations and path shapes.

A private Equinox registry supplies real service tracking and the actual JSON
unmarshaller. CryptoService encrypt/decrypt and EventAdmin are controlled boundaries;
there is no claim of testing the runtime master key. Each test closes both trackers,
checks that keystore and codec service uses are balanced, unregisters services,
terminates each password updater and stops its framework with bounded waits.

The first run passed HTTP but failed all MQTT requests because the fixture omitted
the JSON unmarshaller registration. Registering the actual implementation under its
expected service PID resolved the fixture error without changing endpoint behavior.
Separate production fixes 05484a52dd and 6837913634 provide the previously verified
password-updater and tracker cleanup; they are not folded into this test commit.

Validation selected KeystoreEndpointsV2IT using Failsafe verify in the isolated
migration repository. Mac IDEA class Run passed 16/16. An isolated Equinox/SCR
runtime with real JKS and external master key returned authenticated HTTPS 200
for keystore and entry lists. In that isolated Mac assembly, the SCR registered
PKCS12 service also accepted a new private key and certificate chain through
the V2 HTTPS endpoint (204), returned the new private-key entry (200), and
deleted it (204); entry lists matched before and after cleanup. Temporary key
material was removed. Installed Debian package acceptance remains open. See
`mac-idea-rest-endpoints-validation-20261010.json` and
`mac-rest-scr-endpoint-validation-20261010.json` and
`mac-keystore-privatekey-scr-validation-20261010.json`. Handwritten OSGi metadata and
fork behavior are unchanged.
