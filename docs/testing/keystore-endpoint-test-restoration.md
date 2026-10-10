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
migration repository. Deployed SCR/configuration, actual master-key assembly and
IDEA execution remain open. Handwritten OSGi metadata and fork behavior are unchanged.
