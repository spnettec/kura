"""Embedded in each maintainer script: postrm cannot depend on removed payload files."""
import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ET.register_namespace('esf', 'http://eurotech.com/esf/2.0')
ET.register_namespace('ocd', 'http://www.osgi.org/xmlns/metatype/v1.2.0')


class Lifecycle:
    def __init__(self, root=Path('/'), run=subprocess.run):
        self.root = root
        self.run = run

    def path(self, name):
        return self.root / name.lstrip('/')

    def safe(self, name):
        path = self.path(name)
        for entry in [path, *path.parents]:
            if entry.is_symlink():
                raise RuntimeError(f'Refusing symlink in package state path: {entry}')
            if entry == self.root:
                break
        return path

    def preflight(self):
        home = self.safe('/opt/eclipse/kura')
        state = self.safe('/var/lib/kura-netplan')
        self.safe('/etc/kura-netplan')
        self.safe('/var/log/kura-netplan')
        if home.exists() and any(home.iterdir()) and not (home / 'framework/netplan-profile.json').is_file():
            raise RuntimeError('Existing Kura installation needs an explicit migration; no automatic takeover')
        for name in ['/opt/eclipse/.kura-preserve', '/var/lib/kura-retained', '/etc/systemd/system/kura.service']:
            path = self.path(name)
            if path.exists() or path.is_symlink():
                raise RuntimeError('Legacy Kura state needs an explicit migration: ' + name)
        if state.exists() and any(state.iterdir()):
            marker = self.safe('/var/lib/kura-netplan/.initialized')
            if not marker.is_file() or marker.read_text() != 'kura-core-netplan-v1\n':
                raise RuntimeError('Unknown or interrupted initialization; retain data for explicit recovery')
            key = self.safe('/etc/kura-netplan/crypto.key')
            if not key.is_file() or len(key.read_bytes().rstrip(b'\n')) != 32:
                raise RuntimeError('Retained data requires its original crypto key; refusing to replace it')

    def initialize(self, uid, gid):
        self.preflight()
        state = self.path('/var/lib/kura-netplan')
        if (state / '.initialized').exists():
            return
        config = self.path('/etc/kura-netplan')
        config.mkdir(parents=True, exist_ok=True, mode=0o750)
        os.chown(config, 0 if self.root == Path('/') else os.getuid(), gid)
        os.chmod(config, 0o750)
        # Write an interruption marker before secrets or data. Never silently reseed after failure.
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        (state / '.initializing').write_text('kura-core-netplan-v1\n')
        key = config / 'crypto.key'
        self.exclusive(key, secrets.token_hex(16), 0o640)
        os.chown(key, 0 if self.root == Path('/') else os.getuid(), gid)
        defaults = self.path('/usr/share/kura-netplan/defaults/user')
        shutil.copytree(defaults, state / 'user', symlinks=False)
        password = secrets.token_urlsafe(24)
        keystore_password = secrets.token_urlsafe(24)
        seed = state / 'user/snapshots/snapshot_0.xml'
        document = ET.parse(seed)
        for configuration in document.getroot():
            for prop in configuration.findall('{*}properties/{*}property'):
                if prop.get('name') == 'keystore.password':
                    prop.set('encrypted', 'false')
                    prop.find('{*}value').text = keystore_password
                if prop.get('name') == 'users.config':
                    users = json.loads(prop.find('{*}value').text)
                    users[0]['credentials']['kura.password'] = base64.b64encode(hashlib.sha256(password.encode()).digest()).decode()
                    prop.find('{*}value').text = json.dumps(users)
        document.write(seed, encoding='utf-8', xml_declaration=True)
        env = dict(os.environ, KURA_INITIAL_KEYSTORE_PASSWORD=keystore_password)
        security = state / 'user/security'
        truststore = security / 'cacerts.ks'
        if truststore.exists():
            self.run(['/usr/bin/keytool', '-storepasswd', '-keystore', str(truststore),
                      '-storepass', 'changeit', '-new:env', 'KURA_INITIAL_KEYSTORE_PASSWORD'],
                     check=True, env=env, capture_output=True)
        self.run(['/usr/bin/keytool', '-genkeypair', '-alias', 'kura', '-keyalg', 'RSA', '-keysize', '2048',
                  '-validity', '365', '-dname', 'CN=localhost', '-ext', 'SAN=dns:localhost,ip:127.0.0.1',
                  '-storetype', 'JKS', '-keystore', str(security / 'httpskeystore.ks'),
                  '-storepass:env', 'KURA_INITIAL_KEYSTORE_PASSWORD',
                  '-keypass:env', 'KURA_INITIAL_KEYSTORE_PASSWORD'], check=True, env=env, capture_output=True)
        self.exclusive(config / 'bootstrap-admin', password, 0o600)
        for name in ['data', 'packages', 'tmp', 'load']:
            (state / name).mkdir(mode=0o700)
        (state / 'packages/dpa.properties').touch(mode=0o600)
        for entry in [state, *state.rglob('*')]:
            if entry.is_symlink():
                raise RuntimeError('Unexpected symlink in initial defaults')
            os.chown(entry, uid, gid)
            os.chmod(entry, 0o700 if entry.is_dir() else 0o600)
        self.exclusive(state / '.initialized', 'kura-core-netplan-v1\n', 0o600)
        os.chown(state / '.initialized', uid, gid)
        (state / '.initializing').unlink()

    @staticmethod
    def exclusive(path, content, mode):
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode), 'w') as stream:
            stream.write(content)

    def systemctl(self, *args):
        if self.path('/run/systemd/system').is_dir():
            self.run(['/bin/systemctl', *args], check=True)

    def purge(self):
        # Fixed package-owned data only. Agent identity and OS networking are separate owners.
        paths = [self.safe(name) for name in ['/var/lib/kura-netplan', '/etc/kura-netplan',
                 '/var/log/kura-netplan', '/etc/systemd/system/kura-netplan.service.d']]
        for path in paths:
            if path.exists():
                if not path.is_dir():
                    raise RuntimeError('Unexpected non-directory package state: ' + str(path))
        for path in paths:
            if path.exists():
                shutil.rmtree(path)

    def dispatch(self, script, action):
        if script == 'preinst' and action in ('install', 'upgrade'):
            self.preflight()
        elif script == 'postinst' and action == 'configure':
            self.preflight()
            try:
                account = pwd.getpwnam('kura-netplan')
            except KeyError:
                self.run(['/usr/sbin/useradd', '--system', '--user-group', '--home-dir', '/var/lib/kura-netplan',
                          '--no-create-home', '--shell', '/usr/sbin/nologin', 'kura-netplan'], check=True)
                account = pwd.getpwnam('kura-netplan')
            if account.pw_uid == 0 or account.pw_gid == 0:
                raise RuntimeError('Kura account must be unprivileged')
            self.initialize(account.pw_uid, account.pw_gid)
            logs = self.safe('/var/log/kura-netplan')
            logs.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chown(logs, account.pw_uid, account.pw_gid)
            self.systemctl('daemon-reload')
            print('Installed without starting or enabling Kura. Initial password: /etc/kura-netplan/bootstrap-admin')
        elif script == 'prerm' and action in ('remove', 'upgrade', 'deconfigure'):
            self.systemctl('stop', 'kura-netplan.service')
            if action == 'remove':
                self.systemctl('disable', 'kura-netplan.service')
        elif script == 'postrm':
            if action == 'purge':
                self.purge()
            if action in ('remove', 'purge'):
                self.systemctl('daemon-reload')


if __name__ == '__main__':
    Lifecycle().dispatch(SCRIPT_NAME, sys.argv[1] if len(sys.argv) > 1 else '')
