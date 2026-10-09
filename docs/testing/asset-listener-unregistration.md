# Asset driver listener unregistration

Wires test restoration exposed an existing listener-lifecycle defect in `DriverState`.
Both bulk and legacy registration pass `BaseAsset.ChannelListenerHolder` to the driver.
Unregistration passed the holder's delegated listener instead, so drivers removing
registrations by identity retained the old callback after asset updates or shutdown.

The fix unregisters the same holder in both paths. The public Driver API, listener
wrapping (including scale/offset), handwritten manifest and DS configuration are unchanged.

`DriverStateTest` uses an identity-based recording driver in both bulk and legacy
modes. It checks registration, callback delivery, reconfiguration removal, no callbacks
after removal, re-registration and repeated shutdown. Before the fix both parameterized
cases failed the removal assertion; after the fix both pass. The asset module's existing
three channel-record cases also pass (five total, zero failures/errors/skips).

Validation: Maven 3.10.0 / Temurin 21, migration-m2, asset provider `install`; the Wires
component/provider consumer suites then pass 77 cases, including listener cleanup in
all restored event and scale/offset cases. Only the listener fix and its regression
coverage belong to this production commit; the Wires restoration is a separate batch.
