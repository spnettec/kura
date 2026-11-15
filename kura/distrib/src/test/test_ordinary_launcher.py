"""Run the shipped shell argument path with recording executables, without Java."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'main/resources/filtered/pkg/bin/start_kura_background.sh'


class OrdinaryLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kura-ordinary-shell-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.fake = self.root / 'recording'
        self.fake.mkdir()
        self.record = self.root / 'arguments.json'
        self.generator = self.root / 'generator-called'
        source = SCRIPT.read_text()
        # Only isolate the test's PATH and existing global output paths. The
        # shipped optional argument handling and Java invocation stay verbatim.
        source = source.replace('export PATH=', '# original export PATH=', 1)
        source = source.replace('export MALLOC_ARENA_MAX=1', 'export PATH="' + str(self.fake) + ':/usr/bin:/bin"\nexport MALLOC_ARENA_MAX=1', 1)
        source = source.replace('/tmp/.kura/configuration', str(self.root / 'configuration'))
        source = source.replace('/var/run/kura.pid', str(self.root / 'kura.pid'))
        source = source.replace('/var/log/', str(self.root) + '/')
        for key, value in {'kura.mem.size': '512m', 'kura.os.version': 'linux', 'kura.arch': 'arm64', 'target.device': 'linux', 'org.eclipse.equinox.launcher.version': 'fixture'}.items():
            source = source.replace('@' + key + '@', value)
        (self.bin / 'start_kura_background.sh').write_text(source)
        (self.bin / 'gen_config_ini.sh').write_text('#!/bin/sh\ntouch "' + str(self.generator) + '"\nprintf "osgi.bundles=\\n"\n')
        (self.fake / 'ps').write_text('#!/bin/sh\nexit 0\n')
        (self.fake / 'nohup').write_text('#!/bin/sh\nexec "$@"\n')
        interpreter = shutil.which('python3')
        (self.fake / 'java').write_text('#!' + interpreter + '\nimport json,os,sys\nfrom pathlib import Path\nPath(os.environ["YOFC_LAUNCH_ARGUMENTS"]).write_text(json.dumps(sys.argv[1:]))\n')
        for path in [self.bin / 'gen_config_ini.sh', *self.fake.iterdir()]:
            path.chmod(0o700)

    def launch(self, argument_file=None):
        env = dict(os.environ, YOFC_LAUNCH_ARGUMENTS=str(self.record))
        env.pop('KURA_JVM_ARGS_FILE', None)
        if argument_file is not None:
            env['KURA_JVM_ARGS_FILE'] = str(argument_file)
        return subprocess.run(['/bin/sh', str(self.bin / 'start_kura_background.sh')], env=env, capture_output=True, text=True, timeout=5)

    def args(self):
        for _ in range(100):
            if self.record.exists():
                return json.loads(self.record.read_text())
            time.sleep(.01)
        self.fail('recording Java was not invoked')

    def test_absent_opt_in_keeps_historical_arguments_and_no_agent_dependency(self):
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.args()
        self.assertEqual(args[0], '-Xms512m')
        self.assertFalse(any(arg.startswith('@') for arg in args))
        self.assertIn('-jar', args)
        self.assertTrue(self.generator.exists())
        self.assertNotIn('kura-management-agent', SCRIPT.read_text())

    def test_explicit_argument_file_is_one_quoted_argument_before_historical_options(self):
        argument_file = self.root / 'reviewed ordinary.args'
        argument_file.write_text('-Dkura.management.ordinary.profile.id=fixture\n')
        result = self.launch(argument_file)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.args()
        self.assertEqual(args[:2], ['@' + str(argument_file), '-Xms512m'])
        self.assertEqual(sum(arg.startswith('@') for arg in args), 1)

    def test_invalid_argument_sources_fail_before_generator_or_java(self):
        target = self.root / 'real.args'
        target.write_text('-Xmx512m\n')
        link = self.root / 'link.args'
        link.symlink_to(target)
        for value in ['relative.args', self.root / 'missing.args', self.root, link]:
            with self.subTest(value=str(value)):
                result = self.launch(value)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.generator.exists())
                self.assertFalse(self.record.exists())
                self.assertFalse((self.root / 'kura.pid').exists())


if __name__ == '__main__':
    unittest.main()
