#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Fresh disposable Linux container only; no Core/agent or historical acceptance scene."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time

assert sys.platform == "linux" and os.geteuid() == 0
source = Path("/source")
credential = Path("/etc/kura/credentials")
state = Path("/var/lib/kura-key-service")
assert not credential.exists() and not credential.is_symlink(), "Fresh credential namespace required"
assert not state.exists() and not state.is_symlink(), "Fresh journal namespace required"
assert Path("/proc/self/status").read_text().split("CapEff:\t")[1].splitlines()[0] == "0000000000000000"
assert Path("/proc/self/status").read_text().split("NoNewPrivs:\t")[1].splitlines()[0] == "1"
try:
    daemon = pwd.getpwnam("kurad").pw_uid
except KeyError:
    daemon = 997
    with Path("/etc/passwd").open("a") as stream:
        stream.write("kurad:x:997:997:Kura fixture:/nonexistent:/usr/sbin/nologin\n")
assert daemon not in (0, 65534)
for directory in (credential, state, state / "operations"):
    directory.mkdir(parents=True, mode=0o700)
def private(path, value, mode):
    path.write_bytes(value)
    path.chmod(mode)
key = secrets.token_bytes(32)
proof = dict(schema=1, keySha256=hashlib.sha256(key).hexdigest(), origin="fresh",
             legacyKey=False, unitDigests=[])
private(credential / "kura_encryption_key", key, 0o400)
private(credential / "provisioned.json", json.dumps(proof).encode(), 0o600)
private(credential / ".provision.lock", b"", 0o600)
private(state / "admission.lock", b"", 0o600)
private(state / "journal.key", secrets.token_bytes(32), 0o600)
destination = Path("/opt/eclipse/kura/bin")
destination.mkdir(parents=True, exist_ok=True)
for name in ("kura_key_service.py", "kura_key_store.py", "kura_key_service_lifecycle.py"):
    shutil.copyfile(source / "src/main/resources/unfiltered/pkg/bin" / name, destination / name)
    (destination / name).chmod(0o644)
cipher = Path("/opt/eclipse/kura/libexec/key-backup")
cipher.mkdir(parents=True)
shutil.copyfile(source / "kura-key-crypto/target/kura-key-crypto-6.0.0-SNAPSHOT.jar",
                cipher / "kura-key-crypto.jar")
shutil.copytree(source / "kura-key-crypto/target/lib", cipher / "lib")
# The private package manifest is mandatory even for fixture socket activation.
unit_root = Path("/lib/systemd/system")
unit_root.mkdir(parents=True, exist_ok=True)
units = ("kura-key-service.socket", "kura-key-service.service")
for name in units:
    shutil.copyfile(source / "src/main/resources/unfiltered/pkg/install" / name, unit_root / name)
    (unit_root / name).chmod(0o644)
assets = ("bin/kura_key_store.py", "bin/kura_key_service.py", "bin/kura_key_service_lifecycle.py",
          "libexec/key-backup/kura-key-crypto.jar", "libexec/key-backup/lib/bcprov-jdk18on-1.86.jar")
physical = Path("/opt/eclipse/kura")
manifest = dict(schema=1, protocol=1,
                files={name: hashlib.sha256((physical / name).read_bytes()).hexdigest() for name in assets},
                units={name: hashlib.sha256((unit_root / name).read_bytes()).hexdigest() for name in units})
(cipher / "manifest.json").write_text(json.dumps(manifest))
runtime = Path("/run/kura-key-service")
runtime.mkdir(mode=0o755)
listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
assert listener.fileno() == 3
listener.bind(str(runtime / "control.sock"))
# Deliberately admit other UIDs to the fixture socket to test SO_PEERCRED rejection.
# Production installation must restrict this to root:kurad 0660.
(runtime / "control.sock").chmod(0o666)
listener.listen(8)
launcher = ("import os; os.environ['LISTEN_PID']=str(os.getpid()); "
            "os.execv('/usr/bin/python3',['/usr/bin/python3','-I',"
            "'/opt/eclipse/kura/bin/kura_key_service.py','--serve'])")
server = subprocess.Popen(["/usr/bin/python3", "-I", "-c", launcher], pass_fds=(3,),
                          env={"PATH": "/usr/bin:/bin", "LISTEN_FDS": "1", "LANG": "C.UTF-8"})
listener.close()
def terminate(_signum, _frame):
    if server.poll() is None:
        server.terminate()
signal.signal(signal.SIGTERM, terminate)
signal.signal(signal.SIGINT, terminate)
ready = dict(serverPid=server.pid, daemonUid=daemon, rootUid=os.geteuid(),
             capEff="0000000000000000", noNewPrivileges=1, socketFixtureMode="0666",
             coreStarted=False, agentStarted=False, oldSceneReplayed=False)
Path("/socket-fixture-ready.json").write_text(json.dumps(ready))
print(json.dumps(ready), flush=True)
exit_code = server.wait()
print(json.dumps(dict(serverTerminal=True, serverExitCode=exit_code)), flush=True)
