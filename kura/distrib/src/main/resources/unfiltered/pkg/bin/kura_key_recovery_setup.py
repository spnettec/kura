#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Installer-only independent recovery identity and TLS. Never read a data key."""
import contextlib
import ctypes
import errno
import fcntl
import grp
import importlib.util
import os
from pathlib import Path
import pwd
import secrets
import ssl
import stat
import subprocess
import sys


class Refused(RuntimeError):
    pass


def require(ok):
    if not ok:
        raise Refused('Unsafe or incomplete recovery setup; preserve existing identities and TLS material')


class Setup:
    def __init__(self, root=Path('/'), owner=0, runner=None):
        self.root = Path(root).resolve()
        self.owner = owner
        self.run = subprocess.run if runner is None else runner
        self.base = self.root/'etc/kura'
        self.tls = self.base/'recovery-tls'

    def directory(self, path, private=False, create=False):
        current = self.root
        for part in ('', *path.relative_to(self.root).parts):
            current = current/part
            if create and not os.path.lexists(current):
                current.mkdir(mode=0o700 if current == self.tls else 0o755)
                current.chmod(0o700 if current == self.tls else 0o755)
            st = current.lstat()
            require(stat.S_ISDIR(st.st_mode) and st.st_uid == self.owner and not st.st_mode & 0o022)
        if private:
            require(stat.S_IMODE(st.st_mode) == 0o700)

    def read(self, path, limit=32768, mode=None):
        self.directory(path.parent, private=True)
        fd = os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
        try:
            st = os.fstat(fd)
            require(stat.S_ISREG(st.st_mode) and st.st_uid == self.owner and st.st_nlink == 1
                    and not st.st_mode & 0o7077 and st.st_size <= limit
                    and (mode is None or stat.S_IMODE(st.st_mode) == mode))
            data = os.read(fd, limit+1)
            require(len(data) == st.st_size and len(data) <= limit)
            now = path.lstat(); after = os.fstat(fd)
            require((st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
                    == (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
                    and (st.st_dev,st.st_ino) == (now.st_dev,now.st_ino))
            return data
        finally:
            os.close(fd)

    @staticmethod
    def sync(directory):
        fd = os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)

    @contextlib.contextmanager
    def lock(self):
        self.directory(self.base, create=True)
        path = self.base/'.recovery-setup.lock'
        try:
            fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            os.fsync(fd);os.close(fd);self.sync(self.base)
        except FileExistsError:
            pass
        fd = os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
        try:
            st = os.fstat(fd)
            require(stat.S_ISREG(st.st_mode) and st.st_uid == self.owner and st.st_nlink == 1
                    and st.st_size == 0 and stat.S_IMODE(st.st_mode) == 0o600)
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise Refused('Recovery setup is busy') from None
            yield
        finally:os.close(fd)

    def command(self, arguments):
        done = self.run(arguments,capture_output=True,text=True,timeout=40,check=False,
                        env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C'},cwd='/')
        require(done.returncode == 0)
        return done.stdout

    def accounts(self):
        require(self.root == Path('/') and os.geteuid() == 0)
        daemon = pwd.getpwnam('kurad');require(daemon.pw_uid != 0)
        try:account = pwd.getpwnam('kura-key-recovery')
        except KeyError:
            self.command(['/usr/sbin/useradd','--system','--no-create-home','--home-dir','/nonexistent',
                          '--shell','/usr/sbin/nologin','--user-group','kura-key-recovery'])
            account = pwd.getpwnam('kura-key-recovery')
        require(account.pw_uid not in (0,daemon.pw_uid) and account.pw_dir == '/nonexistent'
                and account.pw_shell in ('/usr/sbin/nologin','/sbin/nologin'))
        private_group = grp.getgrnam('kura-key-recovery')
        require(private_group.gr_gid == account.pw_gid and private_group.gr_gid != 0
                and not private_group.gr_mem
                and not any(p.pw_name != account.pw_name and
                            (p.pw_uid == account.pw_uid or p.pw_gid == account.pw_gid) for p in pwd.getpwall())
                and all(g.gr_name == 'kura-key-control' for g in grp.getgrall() if account.pw_name in g.gr_mem))
        status = self.command(['/usr/bin/passwd','--status','kura-key-recovery']).split()
        require(len(status) >= 2 and status[0] == 'kura-key-recovery' and status[1] in ('L','LK'))
        try:control = grp.getgrnam('kura-key-control')
        except KeyError:
            self.command(['/usr/sbin/groupadd','--system','kura-key-control'])
            control = grp.getgrnam('kura-key-control')
        members = {'kurad','kura-key-recovery'}
        require(control.gr_gid not in (0,daemon.pw_gid,account.pw_gid)
                and set(control.gr_mem) <= members
                and not any(p.pw_gid == control.gr_gid for p in pwd.getpwall()))
        for name in sorted(members - set(control.gr_mem)):
            self.command(['/usr/bin/gpasswd','--add',name,'kura-key-control'])
        require(set(grp.getgrnam('kura-key-control').gr_mem) == members)
        return account

    @staticmethod
    def handoff_ledger():
        # postinst uses python -I: do not depend on cwd, PYTHONPATH or a writable sys.path.
        anchor=Path(__file__).resolve(strict=True)
        path=anchor.with_name('kura_key_service_lifecycle.py')
        owner=anchor.lstat().st_uid
        for entry,regular in ((anchor.parent,False),(anchor,True),(path,True)):
            value=entry.lstat()
            require((stat.S_ISREG(value.st_mode) if regular else stat.S_ISDIR(value.st_mode))
                    and value.st_uid==owner and not value.st_mode & 0o022 and (not regular or value.st_nlink==1))
        spec=importlib.util.spec_from_file_location('_kura_installer_handoff_ledger',path)
        require(spec is not None and spec.loader is not None)
        ledger=importlib.util.module_from_spec(spec)
        # Execute only the checked source: neither trust an old .pyc nor create a cache in installed code.
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
        try:
            before=os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_uid==owner and before.st_nlink==1
                    and not before.st_mode & 0o022 and 0<before.st_size<=512*1024)
            source=os.read(fd,512*1024+1);after=os.fstat(fd);current=path.lstat()
            identity=lambda value:(value.st_dev,value.st_ino,value.st_uid,value.st_gid,value.st_mode,value.st_nlink,
                                    value.st_size,value.st_mtime_ns,value.st_ctime_ns)
            require(len(source)==before.st_size and identity(before)==identity(after)==identity(current))
        finally:os.close(fd)
        exec(compile(source,str(path),'exec',dont_inherit=True),ledger.__dict__)
        require(hasattr(ledger,'Lifecycle') and hasattr(ledger.Lifecycle,'recovery_locked') and hasattr(ledger,'Refused'))
        return ledger

    def state(self, account):
        path = self.root/'var/lib/kura-key-recovery'
        self.directory(path.parent,create=True)
        if not os.path.lexists(path):
            path.mkdir(mode=0o700);path.chmod(0o700);os.chown(path,account.pw_uid,account.pw_gid)
            self.sync(path.parent)
        st = path.lstat()
        # Never let systemd recursively adopt another owner's old journal.
        require(stat.S_ISDIR(st.st_mode) and st.st_uid == account.pw_uid
                and st.st_gid == account.pw_gid and stat.S_IMODE(st.st_mode) == 0o700)
        names={p.name for p in path.iterdir()}
        require(names <= {'operations','admission.lock','starts','pending.json','handoffs','admissions','archives'})
        if {'handoffs','admissions','archives'} & names:
            # Reuse the installer's original-result checks. Merely allowing the new directory
            # would let a local completion marker conceal a missing/UNKNOWN Root request.
            ledger=self.handoff_ledger()
            try:
                with ledger.Lifecycle(self.root,owner=self.owner).recovery_locked():
                    pass
            except (ledger.Refused,OSError,KeyError,ValueError,TypeError):
                raise Refused('Unresolved or unsafe receiver history; retain original sender and Root records') from None
        operations = path/'operations'
        if not os.path.lexists(operations):
            operations.mkdir(mode=0o700);operations.chmod(0o700);os.chown(operations,account.pw_uid,account.pw_gid)
        st = operations.lstat()
        require(stat.S_ISDIR(st.st_mode) and st.st_uid == account.pw_uid and st.st_gid == account.pw_gid
                and stat.S_IMODE(st.st_mode) == 0o700)
        lock = path/'admission.lock'
        if not os.path.lexists(lock):
            require(not list(operations.iterdir()))
            fd = os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:os.fchown(fd,account.pw_uid,account.pw_gid);os.fchmod(fd,0o600);os.fsync(fd)
            finally:os.close(fd)
            self.sync(path)
        st = lock.lstat()
        require(stat.S_ISREG(st.st_mode) and st.st_uid == account.pw_uid and st.st_gid == account.pw_gid
                and st.st_nlink == 1 and st.st_size == 0 and stat.S_IMODE(st.st_mode) == 0o600)

    def resume_marker(self, account):
        # Post-unpack migration only: an old protected restore receipt is authority.
        # Key presence by itself never settles a restore or creates a start receipt.
        sys.path.insert(0,str(Path(__file__).resolve().parent))
        from kura_key_service import Manager
        path=self.root/'var/lib/kura-key-recovery'
        starts=path/'starts'
        if not os.path.lexists(starts):
            starts.mkdir(mode=0o700);starts.chmod(0o700);os.chown(starts,account.pw_uid,account.pw_gid)
            self.sync(path)
        st=starts.lstat()
        require(stat.S_ISDIR(st.st_mode) and st.st_uid==account.pw_uid and st.st_gid==account.pw_gid
                and stat.S_IMODE(st.st_mode)==0o700)
        marker=path/'pending.json'
        if os.path.lexists(marker):return  # Preserve the immutable original intent.
        manager=Manager(self.root,self.owner)
        # A fresh install has no receipt until its provisioner runs.
        if not os.path.lexists(manager.store.path('/etc/kura/credentials/provisioned.json')):return
        with manager.lock(manager.state/'admission.lock',False):
            if any(os.path.lexists(path/name) for name in ('archives','admissions','handoffs')):
                ledger=self.handoff_ledger()
                try:
                    with ledger.Lifecycle(self.root,owner=self.owner).recovery_locked() as history:
                        self.resume_marker_locked(account,manager,history)
                except (ledger.Refused,OSError,KeyError,ValueError,TypeError):
                    raise Refused('Unsafe recovery history; preserve original receiver and Root state') from None
            else:self.resume_marker_locked(account,manager,dict(archived=set(),closedRestores={}))

    def resume_marker_locked(self,account,manager,history):
        from kura_key_service import decode, encode
        from kura_key_service_lifecycle import (validate_start, validate_receiver_restore, receiver_restore_matches,
                                                receiver_restore_marker, restored_key_digest)
        path=self.root/'var/lib/kura-key-recovery';marker=path/'pending.json'
        with manager.lock(manager.store.path('/etc/kura/credentials/.provision.lock'),False):
            keys,_,_,_,_,current=manager.generation_source(allow_missing=True)
        if keys==[None]:return  # Cold single-key recovery; never reconstruct missing generation credentials.
        completed=set()
        root_starts=manager.state/'startups'
        if os.path.lexists(root_starts):
            manager.directory(root_starts,private=True)
            files=list(root_starts.iterdir())
            require(manager.active_records('startups',[p.name[:-5] for p in files])<=32)
            for entry in files:
                require(entry.name.endswith('.json'))
                record=validate_start(decode(manager.read(entry)),entry.name[:-5])
                if record['state']=='SUCCEEDED':completed.add(record['restoreOperationId'])
        candidates=[]
        files=list((path/'operations').iterdir())
        require(sum(('RESTORE',p.name[:-5],None) not in history['archived'] for p in files)<=32)
        for entry in files:
            require(entry.name.endswith('.json'))
            fd=os.open(entry,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            try:
                st=os.fstat(fd)
                require(stat.S_ISREG(st.st_mode) and st.st_uid==account.pw_uid and st.st_gid==account.pw_gid
                        and st.st_nlink==1 and stat.S_IMODE(st.st_mode)==0o600 and st.st_size<=4096)
                local=decode(os.read(fd,4097))
            finally:os.close(fd)
            validate_receiver_restore(local, entry.name[:-5])
            if local['operationId'] in history['closedRestores']:
                require(local==history['closedRestores'][local['operationId']]);continue
            original=manager.record(local['operationId'])
            require(original is not None and original['state']=='SUCCEEDED')
            response=original['response']
            require(receiver_restore_matches(local,response))
            if (restored_key_digest(response)==current['keySha256']
                and local.get('expectedRingSha256')==current['ringSha256'] and local['operationId'] not in completed):
                candidates.append(receiver_restore_marker(local))
        require(len(candidates)<=1)
        if candidates:
            fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:
                os.fchown(fd,account.pw_uid,account.pw_gid);os.fchmod(fd,0o600)
                with os.fdopen(fd,'wb',closefd=False) as stream:
                    stream.write(encode(candidates[0]));stream.flush();os.fsync(fd)
            finally:os.close(fd)
            self.sync(path)

    def validate_tls(self, directory):
        self.directory(directory,private=True)
        require({p.name for p in directory.iterdir()} == {'server.key','server.crt'})
        key = self.read(directory/'server.key',mode=0o400)
        certificate = self.read(directory/'server.crt',mode=0o600)
        require(key.startswith(b'-----BEGIN PRIVATE KEY-----') and certificate.startswith(b'-----BEGIN CERTIFICATE-----'))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        def no_password():
            raise Refused('Encrypted recovery TLS keys need reviewed migration')
        context.load_cert_chain(directory/'server.crt',directory/'server.key',password=no_password)

    def tls_material(self):
        self.directory(self.base,create=True)
        if os.path.lexists(self.tls):
            self.validate_tls(self.tls)
            return
        require(not list(self.base.glob('.recovery-tls-*')))
        stage = self.base/('.recovery-tls-'+secrets.token_hex(16))
        stage.mkdir(mode=0o700);stage.chmod(0o700)
        # A failed or interrupted generation is retained; never replace its key.
        self.command(['/usr/bin/openssl','req','-x509','-newkey','rsa:3072','-nodes','-sha256','-days','3650',
                      '-subj','/CN=Kura Recovery','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1',
                      '-keyout',str(stage/'server.key'),'-out',str(stage/'server.crt')])
        (stage/'server.key').chmod(0o400);(stage/'server.crt').chmod(0o600)
        self.validate_tls(stage)
        for name in ('server.key','server.crt'):
            fd = os.open(stage/name,os.O_RDONLY|os.O_NOFOLLOW)
            try:os.fsync(fd)
            finally:os.close(fd)
        self.sync(stage)
        require(sys.platform == 'linux')
        library = ctypes.CDLL(None,use_errno=True);rename = getattr(library,'renameat2',None)
        require(rename is not None)
        rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
        rename.restype=ctypes.c_int
        if rename(-100,os.fsencode(stage),-100,os.fsencode(self.tls),1) != 0:
            raise Refused('Recovery TLS publication refused; preserve the staging directory')
        self.sync(self.base)

    def install(self):
        with self.lock():
            account = self.accounts()
            self.state(account)
            self.resume_marker(account)
            self.tls_material()


if __name__ == '__main__':
    try:
        require(sys.argv == [sys.argv[0],'--install'] and os.geteuid() == 0 and sys.platform == 'linux')
        Setup().install()
    except (Refused,OSError,KeyError,ValueError,subprocess.SubprocessError):
        sys.stderr.write('Kura recovery setup refused; preserve original accounts, journals and TLS keys\n')
        sys.exit(2)
