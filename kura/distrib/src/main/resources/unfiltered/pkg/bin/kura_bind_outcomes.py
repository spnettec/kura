# SPDX-License-Identifier: EPL-2.0
"""Read and acknowledge BIND outcomes without dispatching a service job."""
from hmac import compare_digest
import os
import re
import secrets

from kura_clock_journal import create, decode, digest, read, require

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


def intent_at(state, root, operation):
    path = state / (operation + '.intent')
    if not os.path.lexists(path):
        return None
    intent = decode(read(path, 0))
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
    if not os.path.lexists(path):
        return None
    receipt = decode(read(path, 0))
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


def delivered_at(state, operation, intent, result, *, acknowledge=False):
    if 'deliveryProtocol' not in intent:
        return True
    path = state / (operation + '.delivered')
    record = dict(schema=1, root=intent['root'], operationId=operation, resultSha256=digest(result))
    if os.path.lexists(path):
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
    intent = intent_at(state, root, operation)
    if intent is None:
        return ('NOT_FOUND', None)
    result = result_at(state, operation, intent)
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
