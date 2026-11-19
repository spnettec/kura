# SPDX-License-Identifier: EPL-2.0
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_modem_driver as broker


class ModemProtocolTest(unittest.TestCase):
    def test_supported_module_usb_mapping_and_no_extra_arguments(self):
        operation = str(uuid.uuid4())
        self.assertEqual(broker.request('load','option','1bc7:1011',operation)['operationId'], operation)
        for action, module, device in [('load','usbnet','1bc7:1011'),('load','option','1bc7:0021'),
                                       ('load','--force','1bc7:1011'),('probe','sierra','1199:0025')]:
            with self.subTest(action=action,module=module,device=device), self.assertRaises(broker.Refused):
                broker.request(action,module,device,operation)

    def test_kmod_arguments_contain_only_the_selected_driver(self):
        with patch.object(broker,'protected'), patch.object(broker.subprocess,'run') as run:
            broker.run_kmod('load','option')
            self.assertEqual(run.call_args.args[0], ['modprobe','--config','/dev/null',
                                                    '--ignore-install','--first-time','--','option'])
            self.assertEqual(run.call_args.kwargs['executable'], '/usr/bin/kmod')
            broker.run_kmod('unload','option')
            self.assertEqual(run.call_args.args[0], ['rmmod','--','option'])
            self.assertEqual(run.call_args.kwargs['executable'], '/usr/bin/kmod')


@unittest.skipUnless(os.geteuid() == 0, 'exercise real immutable Root journal only as root')
class ModemJournalTest(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary)
        self.enterContext(patch.object(broker,'STATE',self.root))
        self.context = dict(root=['00000000000000000000000000000001',1,2],boot=str(uuid.uuid4()))
        self.enterContext(patch.object(broker,'state_binding',return_value=self.context))
        self.enterContext(patch.object(broker,'protected'))
        self.attached = self.enterContext(patch.object(broker,'current_usb',return_value=True))
        self.module = None
        self.enterContext(patch.object(broker,'module_stamp',side_effect=lambda _name: self.module))
        self.kmod = self.enterContext(patch.object(broker,'run_kmod',side_effect=self.kernel))
        self.registration = self.enterContext(patch.object(broker,'registration'))

    def kernel(self, action, _name):
        self.module = [1,9,123] if action == 'load' else None

    @staticmethod
    def intent(action='load',module='option',device='1bc7:1010'):
        return broker.request(action,module,device,str(uuid.uuid4()))

    def operate(self, intent, capability=True):
        return broker.operate(intent, lambda: True, capability)

    def test_admission_refusal_does_not_create_a_dispatch_intent(self):
        self.attached.return_value = False
        with self.assertRaisesRegex(broker.Refused,'USB_NOT_ATTACHED'):
            self.operate(self.intent())
        self.attached.return_value = True
        with self.assertRaisesRegex(broker.Refused,'MODEM_CAPABILITY_UNAVAILABLE'):
            self.operate(self.intent(),capability=False)
        self.kmod.assert_not_called()
        self.assertEqual(list(self.root.glob('*.intent')), [])

    def test_successful_load_register_unload_and_saved_terminal_decision(self):
        source = self.intent()
        self.assertEqual(self.operate(source),'APPLIED')
        self.registration.assert_called_once_with('1bc7:1010')
        self.assertEqual(self.operate(self.intent('unload')),'APPLIED')
        self.assertEqual(self.operate(source),'APPLIED')
        self.assertEqual([item.args for item in self.kmod.call_args_list],[('load','option'),('unload','option')])

    def test_no_unload_for_trusted_but_preexisting_module(self):
        self.module = [1,9,123]
        with self.assertRaisesRegex(broker.Refused,'MODULE_NOT_OWNED'):
            self.operate(self.intent('unload'))
        self.kmod.assert_not_called()

    def test_unknown_fences_original_and_new_id_for_same_module(self):
        self.kmod.side_effect = subprocess.TimeoutExpired('fixed command',15)
        original = self.intent()
        with self.assertRaises(subprocess.TimeoutExpired):
            self.operate(original)
        self.assertEqual(self.operate(original),'UNKNOWN')
        self.assertEqual(self.operate(self.intent()),'UNKNOWN')
        self.assertEqual(self.operate(self.intent('unload',module='sierra',device='1199:0025')),'APPLIED')
        self.kmod.assert_called_once()
        self.context['root'][2] = 3
        with self.assertRaisesRegex(broker.Refused,'UNPAIRED_MODEM_STATE'):
            self.operate(original)


if __name__ == '__main__':
    unittest.main()
