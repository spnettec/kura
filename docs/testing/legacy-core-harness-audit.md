# Legacy core harness audit

- AllCoreTests is a JUnit 4 suite and global broker/configuration bootstrap. Jupiter
  discovery and the existing private BaseCloudTests fixture replace this harness.
  Pending configuration, inventory and network sources in that suite remain pending.
- ExampleTest contains one QoS-1 publish/confirmation scenario. It maps to the
  previously restored DataServiceTest.testPublish(qos=1): 100 unique message IDs
  must match publication and confirmation callbacks, and actual H2 records retain
  payload and confirmation timestamps. Explicit listeners replace static JUnit/DS
  dual instances. No duplicate example test or additional invocation is counted.
- RxTxTest has no executable test method: its physical serial-port example is
  entirely commented out upstream. It is recorded as not applicable, without
  enabling commented hardware code or claiming serial-device coverage.

These are source-audit dispositions based on current source and the already
validated cloud batch. No new workspace-wide run is claimed. The actual SCR,
hardware and IDEA acceptance boundaries are unchanged.
