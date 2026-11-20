# SPDX-License-Identifier: EPL-2.0
"""Read and acknowledge BIND outcomes without dispatching a service job."""
from hmac import compare_digest
import os
import re
import secrets
import stat

from kura_clock_journal import Refused, create, decode, digest, encode, identity, read, require, sync

PROOF = re.compile('[0-9a-f]{64}')
PROTOCOL = 1
READ_ONLY = ('scope', 'outcome')


def request_fields(action):
    verb, separator, proof = action.partition(':')
    if verb not in ('outcome', 'acknowledge', 'settle-publication'):
        return None
    require(separator, 'INVALID_BIND_REQUEST')
    if verb == 'acknowledge':
        scope, match, token = proof.partition(':')
        require(match and PROOF.fullmatch(scope) and PROOF.fullmatch(token), 'INVALID_BIND_REQUEST')
        return dict(action=verb, rootScope=scope, proof=token)
    require(PROOF.fullmatch(proof), 'INVALID_BIND_REQUEST')
    return dict(action=verb, proof=proof)


def binding(state, root, *, required=False):
    path = state / 'root.json'
    if required or os.path.lexists(path):
        require(decode(read(path, 0)) == dict(schema=1, root=root), 'UNPAIRED_BIND_STATE')
    return digest(root)


class UnreadableRecord(Refused):
    """A safely opened journal entry did not contain a complete JSON record."""


def existing_record(path):
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    raw = read(path, 0)
    try:
        return decode(raw)
    except Refused as error:
        raise UnreadableRecord('UNREADABLE_OUTCOME_RECORD') from error


def failed_write_state(state, expected, state_binding):
    """Only confirmed absence on the original Root can release the caller's ID."""
    try:
        root = state_binding()
        if digest(root) != expected['rootScope']:
            return 'UNKNOWN'
        fd = os.open(state, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_RDONLY)
        try:
            directory = os.fstat(fd)
            if ([directory.st_dev, directory.st_ino] != root[1:] or directory.st_uid != 0
                    or directory.st_gid != 0 or stat.S_IMODE(directory.st_mode) != 0o700):
                return 'UNKNOWN'
            binding(state, root)
            # Pin the directory for the lookup. Even a zero-byte intent retains the ID.
            try:
                os.stat(expected['operationId'] + '.intent', dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                return 'REFUSED'
        finally:
            os.close(fd)
    except (Refused, OSError, ValueError, KeyError, TypeError):
        pass
    return 'UNKNOWN'


def intent_at(state, root, operation):
    path = state / (operation + '.intent')
    intent = existing_record(path)
    if intent is None:
        return None
    require(intent['root'] == root and intent['request']['operationId'] == operation, 'UNPAIRED_BIND_STATE')
    if 'deliveryProtocol' in intent:
        require(type(intent['deliveryProtocol']) is int and intent['deliveryProtocol'] == PROTOCOL
                and intent['request']['rootScope'] == digest(root),
                'UNPAIRED_BIND_STATE')
    return intent


def commit(path, intent, *, recovered=False):
    token = secrets.token_hex(32)
    record = dict(intentSha256=digest(intent), state='APPLIED', deliveryToken=token)
    if recovered:
        record['recovery'] = 'paired-file-publication'
    create(path, record)
    return token


def result_at(state, operation, intent):
    path = state / (operation + '.result')
    receipt = existing_record(path)
    if receipt is None:
        return None
    original = dict(intentSha256=digest(intent), state='APPLIED')
    if 'deliveryProtocol' in intent:
        token = receipt.get('deliveryToken')
        require(isinstance(token, str) and PROOF.fullmatch(token), 'UNPAIRED_BIND_STATE')
        original['deliveryToken'] = token
    if 'recovery' in receipt:
        require('stagedPublication' in intent and intent['request']['action'] == 'configure'
                and intent['request']['configuration']['mode'] == 'keep', 'UNPAIRED_BIND_STATE')
        original['recovery'] = 'paired-file-publication'
    require(receipt == original, 'UNPAIRED_BIND_STATE')
    return receipt


def finish_delivery(path, record):
    """The caller holds the ledger lock and has checked the original delivery token."""
    before = identity(path.lstat())
    raw = read(path, 0)
    expected = encode(record)
    if expected.startswith(raw):
        # Keep the existing inode and all bytes written before the interruption.
        rest = memoryview(expected)[len(raw):]
    else:
        require(decode(raw) == record, 'UNPAIRED_BIND_DELIVERY')
        rest = b''
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        require(before == identity(os.fstat(fd)) == identity(path.lstat()), 'UNPAIRED_BIND_DELIVERY')
        while rest:
            count = os.write(fd, rest)
            require(count > 0, 'IO_ERROR')
            rest = rest[count:]
        os.fsync(fd)
        require(identity(os.fstat(fd)) == identity(path.lstat()), 'UNPAIRED_BIND_DELIVERY')
        sync(path.parent)
    finally:
        os.close(fd)


def delivered_at(state, operation, intent, result, *, acknowledge=False):
    if 'deliveryProtocol' not in intent:
        return True
    path = state / (operation + '.delivered')
    record = dict(schema=1, root=intent['root'], operationId=operation, resultSha256=digest(result))
    if os.path.lexists(path):
        if acknowledge:
            finish_delivery(path, record)
        else:
            require(decode(read(path, 0)) == record, 'UNPAIRED_BIND_DELIVERY')
        return True
    if acknowledge:
        create(path, record)
        return True
    return False


def query(state, root, expected):
    scope = binding(state, root)
    if expected['action'] == 'scope':
        return ('APPLIED', scope)
    require(compare_digest(scope, expected['proof']), 'UNPAIRED_BIND_QUERY')
    binding(state, root, required=True)
    operation = expected['operationId']
    try:
        intent = intent_at(state, root, operation)
        if intent is None:
            return ('NOT_FOUND', None)
        result = result_at(state, operation, intent)
    except UnreadableRecord:
        return ('UNKNOWN', None)
    return ('APPLIED', result.get('deliveryToken')) if result is not None else ('UNKNOWN', None)


def acknowledge(state, root, expected):
    require(compare_digest(binding(state, root, required=True), expected['rootScope']), 'UNPAIRED_BIND_DELIVERY')
    operation = expected['operationId']
    intent = intent_at(state, root, operation)
    require(intent is not None and 'deliveryProtocol' in intent, 'UNPAIRED_BIND_DELIVERY')
    receipt = result_at(state, operation, intent)
    require(receipt is not None and compare_digest(expected['proof'], receipt['deliveryToken']),
            'UNPAIRED_BIND_DELIVERY')
    delivered_at(state, operation, intent, receipt, acknowledge=True)
    return ('APPLIED', None)
