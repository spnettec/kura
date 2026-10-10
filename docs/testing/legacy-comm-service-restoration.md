# Legacy communication service presence

Upstream CommTest has one active test: service existence. Its historical serial
open/read/write/dual-port cases are commented out and are not restored as tests.

The Jupiter CommServiceRuntimeIT installs the actual core.comm and jSerialComm
2.11.4 bundles, resolves their imports and obtains the real SCR service through
the current `org.eclipse.kura.comm.CommConnectionFactory` contract. It checks the
provider, active bundle state and actual API/serial package wires. The controller
has no business API classes. No serial port is enumerated or opened; old OSGi IO
ConnectionFactory adapters and legacy RXTX dependencies are not reintroduced.

Root osgi-it reactor verification selected this class and built all 18 dependency
modules successfully. The new runtime case passed (1/0/0/0); four existing comm
unit tests also passed in that reactor. The previously validated six bundle and
47 configuration tests were not selected again in this targeted run. The fixture
uses a separate comm-it-bundles directory and the existing EquinoxExtension for
service/framework cleanup. Hardware and actual IDEA execution remain separate.
