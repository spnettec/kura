# Explicit persistent firewall domain on a new native Root

The native Core worker supports a fresh persistent publication domain. Existing
legacy history is never converted, rebound or re-signed. This is an explicit
administration step before the first firewall publication, separate from normal
Core installation. Core remains usable without an Agent.

Install the paired Core package and complete its normal configuration/READY
sequence. Before the first Main/provider publication, run as Root:

```sh
/usr/bin/python3 -I -B /opt/eclipse/kura/bin/kura_firewall_publish.py --initialize-persistent-root
```

The command accepts no Root, operation ID, Scope or kernel identity arguments.
It holds the real dpkg backend lock, Core admission lock and Core's exclusive
writer lease, checks package/cohort files and the loaded, idle Main unit, and passes the original writer FD as
FD3 to the pinned native worker. The worker runs with no capabilities and NNP1.
A running/starting Main, its shared lease, active package change or Core maintenance refuses
the command. It neither stops Main nor starts an Agent or sends Netlink work.

Initialization requires an empty publication directory and no retained rules or
boot-restore history. A valid existing v2 domain returns `EXISTS` without a new
binding; ordinary requests and outcome receipts retain their existing schemas.
The Root/publication filesystem objects are bound by the native 0.1.17 format.
Unsupported kernel identity and partial/foreign metadata fail explicitly. No
fallback identity or legacy operation adoption is performed.

The new marker is Root-owned and the resulting Scope is opaque. Preserve the
marker and all original intents/results. An interrupted initialization may be
finished by this same command only from the complete original staged bytes and
the same actual kernel objects. A successful initializer response is metadata
setup evidence, never a firewall operation result.

Core and Networking must use the same source archive and workerless maintenance
helper before a v2 domain is used. Their current pin is native source 0.1.17,
Git `f11d66f44ec8eadb54abd922a85f085ca79d5ef5`, archive SHA256
`0fdd973271e641b70098d2ab9c0d1f3b943cb0221a1552374772d0a16acac066`.
Networking verifies its installed/helper source bytes against that archive at
package assembly; all control hooks embed the same helper. Pending/foreign
domains prevent package maintenance even when the installed worker is absent.

This does not authorize any old ID on a changed Root. In particular, new format
initialization must not be used to recover an existing v1 UNKNOWN. Normal reboot,
device reassignment, storage clones and each launcher require their own evidence;
native format support alone does not establish those boundaries.
