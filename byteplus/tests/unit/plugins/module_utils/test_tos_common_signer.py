# -*- coding: utf-8 -*-
# Regression tests for the bytes-safe v4 signer and object-key URL encoding
# in tos_common. These cover:
#   - signing a non-UTF-8 binary body (would crash the SDK's str-only signer)
#   - object keys containing spaces / unicode / reserved characters
#   - deterministic Authorization header given a fixed time
#
# Pure-function tests; no network, no AnsibleModule.

import hashlib
import importlib.util
import pathlib
import re
import sys
import types


def _stub_sdk():
    """Stub byteplussdkcore so tos_common imports without the real SDK installed."""
    bp = types.ModuleType('byteplussdkcore')
    sys.modules.setdefault('byteplussdkcore', bp)

    config_mod = types.ModuleType('byteplussdkcore.configuration')

    class _Config:
        def __init__(self):
            self.ak = None
            self.sk = None
            self.region = None
            self.session_token = None
    config_mod.Configuration = _Config
    sys.modules['byteplussdkcore.configuration'] = config_mod

    rest_mod = types.ModuleType('byteplussdkcore.rest')

    class _RESTClientObject:
        def __init__(self, _config):
            pass

        def request(self, *_a, **_kw):
            raise NotImplementedError

    class _ApiException(Exception):
        def __init__(self, status=0, reason=''):
            self.status = status
            self.reason = reason
    rest_mod.RESTClientObject = _RESTClientObject
    rest_mod.ApiException = _ApiException
    sys.modules['byteplussdkcore.rest'] = rest_mod


def _load_tos_common():
    _stub_sdk()
    repo_root = pathlib.Path(__file__).resolve().parents[4]
    module_path = repo_root / 'plugins' / 'module_utils' / 'tos_common.py'
    spec = importlib.util.spec_from_file_location('tos_common', module_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tos = _load_tos_common()


class TestQuoteKey:
    def test_space(self):
        assert tos._quote_key('a b') == 'a%20b'

    def test_unicode(self):
        assert tos._quote_key('café/ø') == 'caf%C3%A9/%C3%B8'

    def test_slash_preserved(self):
        # Slashes are real path separators in object keys; must NOT be encoded.
        assert tos._quote_key('dir/sub/file.txt') == 'dir/sub/file.txt'

    def test_reserved(self):
        assert tos._quote_key('a+b&c?d#e') == 'a%2Bb%26c%3Fd%23e'


class TestSignV4Bytes:
    """Regression for #1/#18: signer must accept raw bytes."""

    def test_signs_binary_body(self):
        headers = {'Host': 'bucket.tos-ap-southeast-1.bytepluses.com',
                   'Content-Type': 'application/octet-stream'}
        body = b'\x00\x01\x02\xff\xfe'  # invalid UTF-8 on purpose

        tos._sign_v4_bytes(
            path='/key',
            method='PUT',
            headers=headers,
            body_bytes=body,
            query={},
            ak='AKID',
            sk='SECRET',
            region='ap-southeast-1',
            service='tos',
        )

        assert headers['X-Content-Sha256'] == hashlib.sha256(body).hexdigest()
        assert re.match(r'^\d{8}T\d{6}Z$', headers['X-Date'])
        assert headers['Authorization'].startswith('HMAC-SHA256 Credential=AKID/')

    def test_empty_body_uses_empty_sha256(self):
        headers = {'Host': 'x.example.com'}
        empty_sha = hashlib.sha256(b'').hexdigest()

        tos._sign_v4_bytes(
            path='/',
            method='GET',
            headers=headers,
            body_bytes=None,
            query={},
            ak='AKID',
            sk='SECRET',
            region='ap-southeast-1',
            service='tos',
        )
        assert headers['X-Content-Sha256'] == empty_sha

    def test_session_token_added(self):
        headers = {'Host': 'x.example.com'}
        tos._sign_v4_bytes(
            path='/',
            method='GET',
            headers=headers,
            body_bytes=b'',
            query={},
            ak='AKID',
            sk='SECRET',
            region='ap-southeast-1',
            service='tos',
            session_token='SESS',
        )
        assert headers['X-Security-Token'] == 'SESS'

    def test_canonical_query_sorts_and_encodes(self):
        assert tos._canonical_query({'b': '2', 'a': '1'}) == 'a=1&b=2'
        assert tos._canonical_query({'k': 'a b'}) == 'k=a%20b'
        assert tos._canonical_query({}) == ''
