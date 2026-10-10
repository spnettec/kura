# Keystore endpoint tracker references

KeystoreRemoteService acquired an OSGi service in `addingService`, acquired it again
on every property update, and never released it when the tracker closed. This can
retain service use after the HTTP/MQTT endpoint stops.

The fix reuses the service already supplied to `modifiedService` and balances the
original acquisition with `ungetService` in `removedService`. Endpoint APIs, PID
mapping policy, HTTP/MQTT responses and handwritten OSGi metadata are unchanged.

Two regressions use a real Equinox registry and ServiceFactory, covering no property
update and two non-PID property updates. Both require one factory release callback
and no remaining using bundle after tracker closure. Both failed before the change
(2 assertion failures, no errors); framework shutdown cleans up the negative run.

Maven 3.10.0 / Temurin 21: all 22 REST keystore tests and isolated installation pass,
zero failures/errors/skips. These tests cover acquired-service ownership, not changes
to PID collision/renaming policy or full deployed SCR wiring.
