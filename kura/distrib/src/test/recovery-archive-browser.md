# Independent recovery archive browser fixture

This tests the production recovery HTML/CSS/JS and HTTPS handler, real private files and Root archive HMAC in a fresh disposable Linux container. Historical native results, Main/systemd, identity mapping and backup inspection are explicit models. The handoff fixture creates its own test grant/history; it never contacts an installed gateway or retained runtime.

Use the normal workspace build to prepare current reader, key-cipher and offline-recovery JARs. The existing console frontend Playwright installation and Chromium are also required. No previous test reports, private fixtures or special historical Docker images are inputs.

From the `kura` repository:

```sh
docker pull eclipse-temurin:21-jdk
docker build -t yofc-kura-key-metadata-tests:ubuntu24.04 \
  -f kura/distrib/src/test/Dockerfile.metadata-fixture kura/distrib/src/test
node kura/distrib/src/test/test_recovery_archive_browser.mjs
```

The script mounts current source read-only, creates its own random-named JDK volume, publishes only a loopback HTTPS listener and removes its owned container and volume on exit. Certificates and synthetic private state live only in the container's temporary filesystem. Results and a mobile screenshot default to `kura/distrib/target/recovery-archive-browser`; an optional first argument changes that output directory. The outputs can be deleted after the run stops.

The cases cover all four record classes and six admission subtypes, original authorization, pagination, immutable originals and IDs after reload, stale proofs, missing/lost replies, same-ID metadata continuation, lifecycle invalidation, native confirmation keyboard handling and bilingual mobile layout. They do not establish installed Main, real human-session acceptance, full provider coverage or another cryptographic recovery acceptance.
