# Gateway AES master-key backup cipher

This private Java 21 worker supports the Core-owned key service. It is separate
from OSGi, the optional management agent, TLS identity keys, CA custody and the
center's task-encryption key. It does not change the YOFC configuration layering
or `kura.snapshots.encrypt`.

The worker accepts exactly one binary request on stdin and writes only the result
to stdout. It accepts no command-line arguments. A caller must remove inherited
Java option variables, bound its pipes and process lifetime, and supply the trusted
packaged JAR and its fixed Bouncy Castle dependency. Never pass secrets in argv,
environment variables, temporary files, logs or journal fields.

Request fields use network byte order: `KKB1`, one mode byte (1 encrypt, 2 decrypt),
four-byte password length, UTF-8 password bytes, four-byte data length and data.
Trailing bytes and oversized fields are refused. The key-service schema enforces
12 to 256 password characters and at most 1024 UTF-8 bytes.

Backup bytes contain a fixed purpose/version header, a random 16-byte salt, a
random 12-byte nonce and AES-256-GCM ciphertext with a 128-bit authentication tag.
The entire header is authenticated. The key is derived with Argon2id version 1.3,
19 MiB, two iterations and one lane. No uploaded parameters can raise or reduce
the KDF cost. The encrypted payload additionally binds the backup's original
operation UUID and purpose. The outer JSON contains only the version, UUID and
base64 ciphertext. Bouncy Castle 1.86 is pinned explicitly.

Root private operation records store an HMAC request tag and the encrypted result,
never the passphrase or plaintext key. A lost response is recovered by querying
the original UUID. An intent without its exact durable result remains UNKNOWN and
fences new writes; the current key's presence cannot settle that old operation.
Existing matching keys are left unchanged. Missing-key recovery requires an
existing valid provisioning receipt with the same fingerprint, and uses Linux
`renameat2(RENAME_NOREPLACE)` so another key cannot be overwritten. This is not key
rotation and does not authorize foreign-key or receipt-free disaster recovery.

Core now packages the worker, a root-owned systemd socket/service and protected
journal initialization. Package admission takes the same operation lock, refuses
active or unresolved work, then writes a persistent maintenance fence before
stopping services or replacing code. Activation follows retained-data restoration
and validation of the private package manifest. Keys, journal secrets and original
receipts survive scoped upgrade/remove/reinstall checks on Ubuntu 24.04 ARM64.
Account cleanup runs in prerm from tracked root code; postrm never executes the
daemon-writable historical user-manager copy.

Restricted admin/XSRF GWT RPC, download/upload controls and original-UUID browser
recovery remain required. Cold recovery, all launcher/provider/platform modes,
purge and resource-failure matrices also remain pending. This is an unsealed
development candidate; the current package does not yet provide the key GUI.
