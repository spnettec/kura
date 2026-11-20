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
        (self.root / 'framework').mkdir()
        (self.root / 'framework/config.ini').write_text('osgi.framework=fixture\n')
        for name in ('start_kura_background.sh', 'start_kura.sh', 'start_kura_debug.sh'):
            source = (SCRIPT.parent / name).read_text()
            # Only isolate the test's PATH and existing global output paths. The
            # shipped credential admission and Java invocation stay verbatim.
            source = source.replace('export PATH=', '# original export PATH=', 1)
            source = source.replace('export MALLOC_ARENA_MAX=1', 'export PATH="' + str(self.fake) + ':/usr/bin:/bin"\nexport MALLOC_ARENA_MAX=1', 1)
            source = source.replace('/tmp/.kura/configuration', str(self.root / 'configuration'))
            source = source.replace('/var/run/kura.pid', str(self.root / 'kura.pid'))
            source = source.replace('/var/log/', str(self.root) + '/')
            for key, value in {'kura.mem.size': '512m', 'kura.os.version': 'linux', 'kura.arch': 'arm64', 'target.device': 'linux', 'org.eclipse.equinox.launcher.version': 'fixture'}.items():
                source = source.replace('@' + key + '@', value)
            (self.bin / name).write_text(source)
        resources = SCRIPT.parents[3] / 'unfiltered/pkg/bin'
        for name in ['kura_key_store.py', 'kura_credential_env.sh']:
            shutil.copyfile(resources / name, self.bin / name)
        # These tests record shell/JVM arguments; the native suite separately exercises
        # the actual Linux Root peer, descriptor and JVM lifetime. Isolate those
        # boundaries here; these tests exercise shipped shell arguments/early refusal.
        actual_policy = self.bin / 'key_policy_actual.py'
        (self.bin / 'kura_key_store.py').rename(actual_policy)
        self.admission = self.root / 'root-admission-called'
        shim = '''import hashlib,os,runpy,sys
from pathlib import Path
module=runpy.run_path(sys.argv[0].replace('kura_key_store.py','key_policy_actual.py'),run_name='launcher_key_policy')
def root_admission(request,expected):
    assert request == dict(schema=1,action='credential-start-admission',keySha256=hashlib.sha256(bytes(range(32))).hexdigest(),ringSha256=None)
    assert expected == dict(schema=1,state='CREDENTIAL_READY',keySha256=request['keySha256'],ringSha256=None)
    Path(os.environ['YOFC_TEST_ADMISSION_RECORD']).write_text('read-only managed request')
    if os.environ.get('YOFC_TEST_ADMISSION_DENY') == '1':
        raise module['Refused']('fixture Root has an unresolved original operation')
module['main'].__globals__['root_start_admission']=root_admission
def exec_java(arguments):
    assert Path(os.environ['YOFC_TEST_ADMISSION_RECORD']).is_file()
    Path(os.environ['YOFC_TEST_LEASE_RECORD']).write_text('managed Java entrypoint invoked')
    os.execvp('java',['java',*arguments])
module['main'].__globals__['exec_java']=exec_java
sys.exit(module['main'](sys.argv[1:]))
'''
        (self.bin / 'kura_key_store.py').write_text(shim)
        self.credentials = self.root / 'credentials'
        self.credentials.mkdir(mode=0o700)
        self.credential = self.credentials / 'kura_encryption_key'
        self.credential.write_bytes(bytes(range(32)))
        self.credential.chmod(0o400)
        (self.bin / 'gen_config_ini.sh').write_text('#!/bin/sh\ntouch "' + str(self.generator) + '"\nprintf "osgi.bundles=\\n"\n')
        (self.fake / 'ps').write_text('#!/bin/sh\nexit 0\n')
        (self.fake / 'pgrep').write_text('#!/bin/sh\nexit 1\n')
        (self.fake / 'nohup').write_text('#!/bin/sh\nexec "$@"\n')
        interpreter = shutil.which('python3')
        (self.fake / 'java').write_text('#!' + interpreter + '\nimport json,os,sys\nfrom pathlib import Path\nPath(os.environ["YOFC_LAUNCH_ARGUMENTS"]).write_text(json.dumps(sys.argv[1:]))\n')
        for path in [self.bin / 'gen_config_ini.sh', *self.fake.iterdir()]:
            path.chmod(0o700)

    def launch(self, argument_file=None, root_denies=False, script='start_kura_background.sh'):
        env = dict(os.environ, YOFC_LAUNCH_ARGUMENTS=str(self.record))
        env.pop('KURA_JVM_ARGS_FILE', None)
        env['CREDENTIALS_DIRECTORY'] = str(self.credentials)
        env['YOFC_TEST_ADMISSION_RECORD'] = str(self.admission)
        env['YOFC_TEST_ADMISSION_DENY'] = '1' if root_denies else '0'
        env['YOFC_TEST_LEASE_RECORD'] = str(self.root / 'lease-entry-called')
        if argument_file is not None:
            env['KURA_JVM_ARGS_FILE'] = str(argument_file)
        interpreter = '/bin/bash' if script == 'start_kura.sh' else '/bin/sh'
        return subprocess.run([interpreter, str(self.bin / script)], env=env, capture_output=True, text=True, timeout=5)

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
        self.assertTrue(self.admission.exists())
        self.assertTrue((self.root / 'lease-entry-called').exists())
        self.assertNotIn('kura-management-agent', SCRIPT.read_text())

    def test_explicit_argument_file_is_one_quoted_argument_before_historical_options(self):
        argument_file = self.root / 'reviewed ordinary.args'
        argument_file.write_text('-Dkura.management.ordinary.profile.id=fixture\n')
        result = self.launch(argument_file)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.args()
        self.assertEqual(args[:2], ['@' + str(argument_file), '-Xms512m'])
        self.assertEqual(sum(arg.startswith('@') for arg in args), 1)
        self.assertTrue(self.admission.exists())
        self.assertTrue((self.root / 'lease-entry-called').exists())

    def test_configuration_output_matches_stdout_and_survives_template_read_failure(self):
        generator = self.bin / 'gen_config_ini.sh'
        shutil.copyfile(SCRIPT.parents[3] / 'unfiltered/pkg/bin/gen_config_ini.sh', generator)
        template = self.root / 'framework/config.ini'
        plugins = self.root / 'plugins'
        (plugins / '4s').mkdir(parents=True)
        (plugins / '4s' / 'example.jar').touch()
        config = self.root / 'configuration/config.ini'
        config.parent.mkdir()
        config.write_bytes(b'earlier configuration')
        before = config.stat()
        expected = subprocess.check_output(['/bin/sh', str(generator), str(template), str(plugins), ''])
        self.assertIn(b'example.jar@4', expected)
        self.assertEqual(self.launch().returncode, 0)
        self.assertEqual(config.read_bytes(), expected)
        self.assertNotEqual(config.stat().st_ino, before.st_ino)
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)

        template.unlink()
        template.mkdir()
        complete = config.stat()
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(config.read_bytes(), expected)
        self.assertEqual(config.stat().st_ino, complete.st_ino)
        self.assertEqual(set(config.parent.iterdir()), {config})

    def test_partial_bundle_list_is_discarded_before_claiming_a_writer_lease(self):
        generator = self.bin / 'gen_config_ini.sh'
        generator.write_text('#!/bin/sh\nprintf "partial bundle list"\nexit 1\n')
        config = self.root / 'configuration/config.ini'
        config.parent.mkdir()
        config.write_bytes(b'previous complete configuration')
        before = config.stat()
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(config.read_bytes(), b'previous complete configuration')
        self.assertEqual(config.stat().st_ino, before.st_ino)
        self.assertEqual(set(config.parent.iterdir()), {config})
        self.assertFalse((self.root / 'lease-entry-called').exists())

    def test_failed_generation_preserves_last_configuration_for_every_launcher(self):
        generator = self.bin / 'gen_config_ini.sh'
        shutil.copyfile(SCRIPT.parents[3] / 'unfiltered/pkg/bin/gen_config_ini.sh', generator)
        # An incomplete package layout may have no framework configuration template.
        (self.root / 'framework/config.ini').unlink()
        (self.root / 'plugins').mkdir()
        directory = self.root / 'configuration'
        directory.mkdir()
        config = directory / 'config.ini'
        config.write_bytes(b'previous complete configuration\n')
        before = config.stat()
        for name in ('start_kura_background.sh', 'start_kura.sh', 'start_kura_debug.sh'):
            with self.subTest(launcher=name):
                result = self.launch(script=name)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('framework/config.ini', result.stderr)
                self.assertEqual(config.read_bytes(), b'previous complete configuration\n')
                self.assertEqual(config.stat().st_ino, before.st_ino)
                self.assertEqual(set(directory.iterdir()), {config})
                self.assertFalse((self.root / 'lease-entry-called').exists())
                self.assertFalse((self.root / 'kura.pid').exists())

    def test_root_unknown_refuses_before_generator_or_java_even_with_a_valid_credential(self):
        before = self.credential.read_bytes()
        for name in ('start_kura_background.sh', 'start_kura.sh', 'start_kura_debug.sh'):
            with self.subTest(launcher=name):
                self.admission.unlink(missing_ok=True)
                result = self.launch(root_denies=True, script=name)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(self.admission.exists())
                self.assertFalse(self.generator.exists())
                self.assertFalse(self.record.exists())
                self.assertFalse((self.root / 'kura.pid').exists())
        self.assertEqual(before, self.credential.read_bytes())

    def test_missing_credential_refuses_before_generator_or_java(self):
        self.credential.unlink()
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.generator.exists())
        self.assertFalse(self.record.exists())
        self.assertFalse((self.root / 'kura.pid').exists())

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
