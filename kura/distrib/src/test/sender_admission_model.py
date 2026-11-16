"""Explicit native-authority model for existing controller-only regression fixtures.

These fixtures do not claim Root admission/UID/transport acceptance. The new
sender-admission suites exercise the production reservation protocol separately.
"""
class SenderModel:
    def has_attempt(self, kind, identity):
        return False

    def submit(self, kind, identity, request, callback):
        return callback()
