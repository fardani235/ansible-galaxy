# -*- coding: utf-8 -*-
# Tests for the rotate-flag dance and secret-stripping in
# byteplus_iam_access_key. The module's CRUD branches go to live API
# in the smoke test; here we cover the pure-logic helpers:
# - find_oldest_active picks the right key to deactivate
# - _strip_secrets refuses to leak the secret through `keys`
# - _normalize_status papers over PascalCase/lowercase casing drift

import importlib.util
import pathlib
import sys
import types


def _stub_imports():
    ansible = types.ModuleType('ansible')
    sys.modules.setdefault('ansible', ansible)
    mu = types.ModuleType('ansible.module_utils')
    sys.modules.setdefault('ansible.module_utils', mu)
    basic = types.ModuleType('ansible.module_utils.basic')
    basic.AnsibleModule = object
    basic.env_fallback = lambda *_a, **_kw: None
    sys.modules['ansible.module_utils.basic'] = basic

    for name in [
        'ansible_collections',
        'ansible_collections.fardani235',
        'ansible_collections.fardani235.byteplus',
        'ansible_collections.fardani235.byteplus.plugins',
        'ansible_collections.fardani235.byteplus.plugins.module_utils',
    ]:
        sys.modules.setdefault(name, types.ModuleType(name))

    iam_common = types.ModuleType(
        'ansible_collections.fardani235.byteplus.plugins.module_utils.'
        'iam_common')

    class _IAMClient:
        def __init__(self, **kwargs):
            pass

    class _IAMError(Exception):
        pass

    iam_common.IAMClient = _IAMClient
    iam_common.IAMError = _IAMError
    sys.modules[
        'ansible_collections.fardani235.byteplus.plugins.module_utils.'
        'iam_common'
    ] = iam_common


def _load_module():
    _stub_imports()
    repo_root = pathlib.Path(__file__).resolve().parents[4]
    path = repo_root / 'plugins' / 'modules' / 'byteplus_iam_access_key.py'
    spec = importlib.util.spec_from_file_location(
        'byteplus_iam_access_key', path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ak = _load_module()


class TestFindOldestActive:
    def test_single_active_returned(self):
        keys = [{'AccessKeyId': 'A1', 'Status': 'active',
                 'CreateDate': '2026-01-01T00:00:00Z'}]
        assert ak.find_oldest_active(keys) == 'A1'

    def test_picks_oldest_by_create_date(self):
        keys = [
            {'AccessKeyId': 'NEW', 'Status': 'active',
             'CreateDate': '2026-05-01T00:00:00Z'},
            {'AccessKeyId': 'OLD', 'Status': 'active',
             'CreateDate': '2025-12-01T00:00:00Z'},
        ]
        # Sort is lexicographic on ISO-8601, which matches chronological.
        assert ak.find_oldest_active(keys) == 'OLD'

    def test_ignores_inactive_keys(self):
        # An inactive key that predates the active one must NOT be
        # picked — rotate's intent is "deactivate the OLDEST ACTIVE",
        # not "the oldest of any status".
        keys = [
            {'AccessKeyId': 'NEW', 'Status': 'active',
             'CreateDate': '2026-05-01T00:00:00Z'},
            {'AccessKeyId': 'OLD-INACTIVE', 'Status': 'inactive',
             'CreateDate': '2024-01-01T00:00:00Z'},
        ]
        assert ak.find_oldest_active(keys) == 'NEW'

    def test_returns_none_when_no_active_keys(self):
        keys = [
            {'AccessKeyId': 'A1', 'Status': 'inactive',
             'CreateDate': '2025-12-01T00:00:00Z'},
        ]
        assert ak.find_oldest_active(keys) is None

    def test_handles_empty_and_none(self):
        assert ak.find_oldest_active([]) is None
        assert ak.find_oldest_active(None) is None

    def test_handles_pascalcase_status(self):
        # Older SDK versions may surface 'Active' instead of 'active' —
        # _normalize_status flattens both to the same wire form.
        keys = [{'AccessKeyId': 'A1', 'Status': 'Active',
                 'CreateDate': '2026-01-01T00:00:00Z'}]
        assert ak.find_oldest_active(keys) == 'A1'


class TestStripSecrets:
    def test_secret_access_key_removed(self):
        # _strip_secrets is what protects `keys` (the always-returned
        # listing) from accidentally carrying the secret that
        # `access_key` returns at create time.
        keys = [{
            'AccessKeyId': 'A1', 'Status': 'active',
            'SecretAccessKey': 'NEVER-SEE-THIS',
        }]
        out = ak._strip_secrets(keys)
        assert out == [{'AccessKeyId': 'A1', 'Status': 'active'}]

    def test_secret_access_key_snake_case_removed(self):
        # snake_case appears in older SDK rev's to_dict() output.
        keys = [{
            'AccessKeyId': 'A1',
            'secret_access_key': 'NEVER-SEE-THIS',
        }]
        out = ak._strip_secrets(keys)
        assert 'secret_access_key' not in out[0]
        assert 'SecretAccessKey' not in out[0]

    def test_handles_none_and_empty(self):
        assert ak._strip_secrets(None) == []
        assert ak._strip_secrets([]) == []

    def test_non_secret_fields_preserved(self):
        keys = [{'AccessKeyId': 'A1', 'Status': 'active',
                 'CreateDate': '2026-01-01T00:00:00Z'}]
        out = ak._strip_secrets(keys)
        assert out[0] == keys[0]


class TestNormalizeStatus:
    def test_lower(self):
        assert ak._normalize_status('Active') == 'active'

    def test_passthrough_lowercase(self):
        assert ak._normalize_status('active') == 'active'

    def test_none(self):
        assert ak._normalize_status(None) is None
