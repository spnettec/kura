# SPDX-License-Identifier: EPL-2.0
from pathlib import Path
import os
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import Mock, call, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_modem_reset as service
from kura_clock_journal import Refused, digest

DEVICE = '/org/freedesktop/NetworkManager/Devices/12'
DEVICE_ID = '1-4'
MODEM = '/org/freedesktop/ModemManager1/Modem/1'


class ModemResetRequestTest(unittest.TestCase):
    def test_only_nm_device_paths_and_fixed_actions_are_accepted(self):
        scope = 'a' * 64
        operation = str(uuid4())
        self.assertEqual(service.request(f'reset:{scope}:{DEVICE}:{DEVICE_ID}', operation)['device'], DEVICE)
        for unsupported in (f'reset:{scope}:{MODEM}', f'reset:{scope}:{DEVICE}/child',
                            f'reset:{scope.upper()}:{DEVICE}', f'settle-publication:{scope}',
                            f'enable:{scope}:{DEVICE}', f'gps-raw:{scope}:{DEVICE}:{DEVICE_ID}'):
            with self.subTest(action=unsupported), self.assertRaises(Refused):
                service.request(unsupported, operation)


@unittest.skipUnless(os.geteuid() == 0, 'Requires a root-owned temporary state directory on Linux')
class ModemResetOutcomeTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.state = Path(directory)
        self.root = ['0' * 32, self.state.stat().st_dev, self.state.stat().st_ino]
        self.scope = digest(self.root)
        self.operation = str(uuid4())
        self.bus = Mock()
        dbus = types.SimpleNamespace(bus=types.SimpleNamespace(BusConnection=Mock(return_value=self.bus)),
                                     UInt32=int, DBusException=RuntimeError)
        self.enterContext(patch.dict(sys.modules, {'dbus': dbus}))
        self.enterContext(patch.object(service, 'STATE', self.state))
        self.enterContext(patch.object(service, 'state_binding', side_effect=lambda: self.root))
        self.enterContext(patch.object(service, 'legacy_owner'))
        self.target = self.enterContext(patch.object(service, 'target',
                                        return_value=(((':1.2',), (':1.3',), MODEM, '/sys/devices/a', 5, 6), 6)))

    def operate(self, action, operation=None):
        return service.operate(service.request(action, operation or self.operation), lambda: True)

    def reset(self, operation=None):
        return self.mutate('reset', operation)

    def mutate(self, mode, operation=None):
        return self.operate(f'{mode}:{self.scope}:{DEVICE}:{DEVICE_ID}', operation)

    def test_positive_reply_must_be_observed_and_acknowledged(self):
        status, proof = self.reset()
        self.assertEqual(status, 'APPLIED')
        self.bus.call_blocking.assert_called_once_with(':1.3', MODEM, service.MM + '.Modem',
                                                       'Reset', '', (), timeout=20)
        with self.assertRaisesRegex(Refused, 'PENDING_MODEM_RESET_OUTCOME'):
            self.reset(str(uuid4()))
        self.assertEqual(self.operate('outcome:' + self.scope), ('APPLIED', proof))
        self.assertEqual(self.operate(f'acknowledge:{self.scope}:{proof}'), ('APPLIED', None))
        self.assertEqual(self.reset(), ('APPLIED', proof))
        self.bus.call_blocking.assert_called_once()

    def test_lost_dbus_reply_leaves_an_intent_and_never_dispatches_again(self):
        self.bus.call_blocking.side_effect = OSError('lost reply')
        with self.assertRaises(OSError):
            self.reset()
        self.assertEqual(self.operate('outcome:' + self.scope), ('UNKNOWN', None))
        with self.assertRaisesRegex(Refused, 'PENDING_MODEM_RESET_OUTCOME'):
            self.operate('ready', str(uuid4()))
        with self.assertRaisesRegex(Refused, 'PENDING_MODEM_RESET_OUTCOME'):
            self.reset(str(uuid4()))
        with self.assertRaisesRegex(Refused, 'UNPAIRED_BIND_QUERY'):
            self.operate('outcome:' + 'f' * 64)
        self.bus.call_blocking.assert_called_once()
        self.assertFalse((self.state / (self.operation + '.result')).exists())

    def test_target_change_after_intent_stops_dispatch(self):
        first, state = self.target.return_value
        self.target.side_effect = [(first, state), ((*first[:-1], 99), state)]
        with self.assertRaisesRegex(Refused, 'MODEM_RESET_TARGET_CHANGED'):
            self.reset()
        self.assertEqual(self.operate('outcome:' + self.scope), ('UNKNOWN', None))
        self.bus.call_blocking.assert_not_called()

    def test_ineligible_device_stops_before_creating_an_intent(self):
        self.target.side_effect = Refused('NOT_A_MODEM_DEVICE')
        with self.assertRaisesRegex(Refused, 'NOT_A_MODEM_DEVICE'):
            self.reset()
        self.assertEqual({item.name for item in self.state.iterdir()}, {'lock'})
        self.bus.call_blocking.assert_not_called()


    def test_main_must_still_be_paired_after_rechecking_the_target(self):
        expected = service.request(f'gps-disabled:{self.scope}:{DEVICE}:{DEVICE_ID}', self.operation)
        authorize = Mock(side_effect=[True, True, False])
        with patch.object(service, 'property_value', side_effect=[22, 6]), self.assertRaisesRegex(
                Refused, 'UNAUTHORIZED'):
            service.operate(expected, authorize)
        self.assertEqual(self.operate('outcome:' + self.scope), ('UNKNOWN', None))
        self.bus.call_blocking.assert_not_called()

    def test_managed_location_uses_one_intent_for_enable_clear_and_final_setup(self):
        self.target.return_value = (self.target.return_value[0], 3)
        with patch.object(service, 'property_value', side_effect=[22, 16]):
            result, proof = self.mutate('gps-managed')
        self.assertEqual(result, 'APPLIED')
        self.assertEqual(self.bus.call_blocking.call_args_list, [
            call(':1.3', MODEM, service.MM + '.Modem', 'Enable', 'b', (True,), timeout=20),
            call(':1.3', MODEM, service.LOCATION, 'Setup', 'ub', (0, False), timeout=20),
            call(':1.3', MODEM, service.LOCATION, 'Setup', 'ub', (6, False), timeout=20)])
        self.assertEqual(len(list(self.state.glob('*.intent'))), 1)
        self.assertEqual(self.operate('outcome:' + self.scope), ('APPLIED', proof))
        with self.assertRaisesRegex(Refused, 'UNPAIRED_MODEM_OPERATION'):
            self.reset()

    def test_unknown_intermediate_location_call_stops_before_final_setup(self):
        self.target.return_value = (self.target.return_value[0], 3)
        self.bus.call_blocking.side_effect = [None, OSError('uncertain clear')]
        with patch.object(service, 'property_value', side_effect=[22, 16]), self.assertRaises(OSError):
            self.mutate('gps-managed')
        self.assertEqual(self.bus.call_blocking.call_count, 2)
        self.assertEqual(self.operate('outcome:' + self.scope), ('UNKNOWN', None))
        with self.assertRaisesRegex(Refused, 'PENDING_MODEM_RESET_OUTCOME'):
            self.operate('ready-gps')
        with self.assertRaisesRegex(Refused, 'PENDING_MODEM_RESET_OUTCOME'):
            self.reset(str(uuid4()))

    def test_disabled_and_unmanaged_modes_keep_the_existing_call_order(self):
        with patch.object(service, 'property_value', side_effect=[22, 6]):
            result, proof = self.mutate('gps-disabled')
        self.assertEqual(result, 'APPLIED')
        self.bus.call_blocking.assert_called_once_with(':1.3', MODEM, service.LOCATION,
                                                       'Setup', 'ub', (0, False), timeout=20)
        self.operate(f'acknowledge:{self.scope}:{proof}')
        self.bus.call_blocking.reset_mock()
        with patch.object(service, 'property_value', side_effect=[22, 6]):
            self.assertEqual(self.mutate('gps-unmanaged', str(uuid4()))[0], 'APPLIED')
        self.assertEqual(self.bus.call_blocking.call_args_list, [
            call(':1.3', MODEM, service.LOCATION, 'Setup', 'ub', (0, False), timeout=20),
            call(':1.3', MODEM, service.LOCATION, 'Setup', 'ub', (16, False), timeout=20)])

    def test_already_configured_or_unsupported_location_has_no_intent(self):
        for capabilities, enabled in ((22, 6), (16, 16)):
            with self.subTest(capabilities=capabilities), patch.object(
                    service, 'property_value', side_effect=[capabilities, enabled]):
                self.assertEqual(self.mutate('gps-managed'), ('UNCHANGED', None))
        self.bus.call_blocking.assert_not_called()
        self.assertEqual({item.name for item in self.state.iterdir()}, {'lock'})


if __name__ == '__main__':
    unittest.main()
