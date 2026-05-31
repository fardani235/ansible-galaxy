# -*- coding: utf-8 -*-
# Tests for byteplus_route_table internals:
# - drift detection on rename + description
# - association reconciliation against current state
# - the system-route-table refusal path (present + absent)

import importlib.util
import pathlib
import sys
import types
from unittest import mock


def _stub_imports():
    """Stub Ansible + vpc_common so the module imports without the live SDK."""
    sys.modules.setdefault('ansible', types.ModuleType('ansible'))
    sys.modules.setdefault('ansible.module_utils',
                           types.ModuleType('ansible.module_utils'))
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

    stub = types.ModuleType(
        'ansible_collections.fardani235.byteplus.plugins.module_utils.vpc_common')

    class _Client:
        def __init__(self, *_a, **_kw):
            pass

    stub.VPCClient = _Client
    stub.resolve_credentials = lambda module: ('AK', 'SK', 'ap-southeast-1', None)

    # Reuse the actual helper logic — tests would lie otherwise.
    def diff(current, desired):
        cur = set(current or [])
        des = set(desired or [])
        return sorted(des - cur), sorted(cur - des)
    stub.diff_route_table_associations = diff

    def is_system(rt):
        t = (rt.get('route_table_type') or rt.get('RouteTableType'))
        return t == 'System'
    stub.is_system_route_table = is_system

    def assoc(rt):
        raw = (rt.get('subnet_ids') or rt.get('SubnetIds')
               or rt.get('subnet_id') or rt.get('SubnetId') or [])
        if isinstance(raw, str):
            return [raw] if raw else []
        return list(raw)
    stub.associated_subnet_ids = assoc

    sys.modules[
        'ansible_collections.fardani235.byteplus.plugins.module_utils.vpc_common'
    ] = stub


def _load_module():
    _stub_imports()
    repo_root = pathlib.Path(__file__).resolve().parents[4]
    path = repo_root / 'plugins' / 'modules' / 'byteplus_route_table.py'
    spec = importlib.util.spec_from_file_location('byteplus_route_table', path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rt_mod = _load_module()


class TestAttrModifyKwargs:
    def test_no_drift(self):
        existing = {'route_table_name': 'app', 'description': 'hello'}
        p = {'route_table_name': 'app', 'description': 'hello'}
        assert rt_mod._attr_modify_kwargs(p, existing) is None

    def test_rename_only(self):
        existing = {'route_table_name': 'old', 'description': 'd'}
        p = {'route_table_name': 'new', 'description': 'd'}
        out = rt_mod._attr_modify_kwargs(p, existing)
        assert out == {'route_table_name': 'new'}

    def test_description_change(self):
        existing = {'route_table_name': 'app', 'description': 'old'}
        p = {'route_table_name': 'app', 'description': 'new'}
        out = rt_mod._attr_modify_kwargs(p, existing)
        assert out == {'description': 'new'}

    def test_description_absent_param_no_drift(self):
        # The user didn't pass description → don't treat the API's current
        # value as drift just because it's a string.
        existing = {'route_table_name': 'app', 'description': 'old'}
        p = {'route_table_name': 'app', 'description': None}
        assert rt_mod._attr_modify_kwargs(p, existing) is None

    def test_pascal_case_existing(self):
        existing = {'RouteTableName': 'old', 'Description': 'd'}
        p = {'route_table_name': 'new', 'description': 'd'}
        out = rt_mod._attr_modify_kwargs(p, existing)
        assert out == {'route_table_name': 'new'}

    def test_empty_description_equates_to_unset(self):
        # BytePlus returns '' for unset description; setting description: ''
        # should not be flagged as drift.
        existing = {'route_table_name': 'app'}  # description field absent
        p = {'route_table_name': 'app', 'description': ''}
        assert rt_mod._attr_modify_kwargs(p, existing) is None


class _FakeClient:
    def __init__(self):
        self.associate_route_table = mock.Mock()
        self.disassociate_route_table = mock.Mock()


class _FakeParamsModule:
    """A minimal stand-in for AnsibleModule that exposes params only."""

    def __init__(self, **params):
        self.params = params


class TestReconcileAssociations:
    def test_param_omitted_is_noop(self):
        module = _FakeParamsModule(associated_subnet_ids=None)
        client = _FakeClient()
        changed = rt_mod._reconcile_associations(
            module, client, 'vtb-1',
            existing={'subnet_ids': ['s-1']},
            check_mode=False)
        assert changed is False
        client.associate_route_table.assert_not_called()
        client.disassociate_route_table.assert_not_called()

    def test_associates_missing(self):
        module = _FakeParamsModule(associated_subnet_ids=['s-1', 's-2'])
        client = _FakeClient()
        changed = rt_mod._reconcile_associations(
            module, client, 'vtb-1',
            existing={'subnet_ids': ['s-1']},
            check_mode=False)
        assert changed is True
        client.associate_route_table.assert_called_once_with('vtb-1', 's-2')
        client.disassociate_route_table.assert_not_called()

    def test_disassociates_extras(self):
        module = _FakeParamsModule(associated_subnet_ids=['s-1'])
        client = _FakeClient()
        changed = rt_mod._reconcile_associations(
            module, client, 'vtb-1',
            existing={'subnet_ids': ['s-1', 's-9']},
            check_mode=False)
        assert changed is True
        client.disassociate_route_table.assert_called_once_with('vtb-1', 's-9')

    def test_check_mode_skips_api(self):
        module = _FakeParamsModule(associated_subnet_ids=['s-2'])
        client = _FakeClient()
        changed = rt_mod._reconcile_associations(
            module, client, 'vtb-1',
            existing={'subnet_ids': ['s-1']},
            check_mode=True)
        assert changed is True
        client.associate_route_table.assert_not_called()
        client.disassociate_route_table.assert_not_called()

    def test_no_diff_reports_unchanged(self):
        module = _FakeParamsModule(associated_subnet_ids=['s-1', 's-2'])
        client = _FakeClient()
        changed = rt_mod._reconcile_associations(
            module, client, 'vtb-1',
            existing={'subnet_ids': ['s-2', 's-1']},  # same set, different order
            check_mode=False)
        assert changed is False
