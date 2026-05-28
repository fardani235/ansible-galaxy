# -*- coding: utf-8 -*-
# Tests for byteplus_iam_policy_attachment's target_type dispatch:
# is_attached must consult the right List* verb, _attach / _detach must
# dispatch to the right Attach*/Detach* verb. The dispatch is the whole
# point of the module (one module covering 4 BytePlus IAM verbs), so it
# gets a dedicated test even though every other IAM module skips them.

import importlib.util
import pathlib
import sys
import types
from unittest import mock


def _stub_imports():
    """Stub ansible.module_utils.basic and the ansible_collections
    package chain so we can load byteplus_iam_policy_attachment in
    isolation. Mirrors the pattern from
    test_byteplus_ecs_snapshot_group."""
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

    # Provide a fake iam_common just deep enough for the module's import
    # — the dispatch tests don't go through IAMClient itself.
    iam_common = types.ModuleType(
        'ansible_collections.fardani235.byteplus.plugins.'
        'module_utils.iam_common')

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
    path = repo_root / 'plugins' / 'modules' / 'byteplus_iam_policy_attachment.py'
    spec = importlib.util.spec_from_file_location(
        'byteplus_iam_policy_attachment', path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pa = _load_module()


class TestIsAttached:
    def test_user_target_uses_list_attached_user_policies(self):
        client = mock.Mock()
        client.list_attached_user_policies.return_value = [
            {'PolicyName': 'p1', 'PolicyType': 'Custom'},
        ]
        assert pa.is_attached(
            client, 'p1', 'Custom', 'user', 'alice') is True
        client.list_attached_user_policies.assert_called_once_with('alice')
        client.list_attached_role_policies.assert_not_called()

    def test_role_target_uses_list_attached_role_policies(self):
        client = mock.Mock()
        client.list_attached_role_policies.return_value = [
            {'PolicyName': 'p1', 'PolicyType': 'Custom'},
        ]
        assert pa.is_attached(
            client, 'p1', 'Custom', 'role', 'deploy') is True
        client.list_attached_role_policies.assert_called_once_with('deploy')
        client.list_attached_user_policies.assert_not_called()

    def test_policy_type_distinguishes_same_name(self):
        # The same policy_name can exist as both Custom and System.
        # Matching must include PolicyType — otherwise attaching the
        # Custom flavor when the System flavor is attached would
        # silently no-op.
        client = mock.Mock()
        client.list_attached_user_policies.return_value = [
            {'PolicyName': 'AdminAccess', 'PolicyType': 'System'},
        ]
        assert pa.is_attached(
            client, 'AdminAccess', 'Custom', 'user', 'alice') is False
        assert pa.is_attached(
            client, 'AdminAccess', 'System', 'user', 'alice') is True

    def test_empty_attached_list(self):
        client = mock.Mock()
        client.list_attached_user_policies.return_value = []
        assert pa.is_attached(
            client, 'p1', 'Custom', 'user', 'alice') is False

    def test_none_attached_list(self):
        # The IAMClient helper returns [] but defensive code shouldn't
        # crash on None either — ListAttached* under no attachments
        # has historically returned a missing key, which the helper
        # turns into None in some versions of byteplussdkcore.
        client = mock.Mock()
        client.list_attached_user_policies.return_value = None
        assert pa.is_attached(
            client, 'p1', 'Custom', 'user', 'alice') is False


class TestAttachDispatch:
    def test_attach_user(self):
        client = mock.Mock()
        pa._attach(client, 'p1', 'Custom', 'user', 'alice')
        client.attach_user_policy.assert_called_once_with(
            policy_name='p1', policy_type='Custom', user_name='alice')
        client.attach_role_policy.assert_not_called()

    def test_attach_role(self):
        client = mock.Mock()
        pa._attach(client, 'p1', 'System', 'role', 'deploy')
        client.attach_role_policy.assert_called_once_with(
            policy_name='p1', policy_type='System', role_name='deploy')
        client.attach_user_policy.assert_not_called()


class TestDetachDispatch:
    def test_detach_user(self):
        client = mock.Mock()
        pa._detach(client, 'p1', 'Custom', 'user', 'alice')
        client.detach_user_policy.assert_called_once_with(
            policy_name='p1', policy_type='Custom', user_name='alice')
        client.detach_role_policy.assert_not_called()

    def test_detach_role(self):
        client = mock.Mock()
        pa._detach(client, 'p1', 'Custom', 'role', 'deploy')
        client.detach_role_policy.assert_called_once_with(
            policy_name='p1', policy_type='Custom', role_name='deploy')
        client.detach_user_policy.assert_not_called()
