# -*- coding: utf-8 -*-
# Tests for pure helpers in byteplus_ecs_instance (no AnsibleModule needed).
#
# Currently covers _resolve_volumes: the merge between the positional
# `volumes` form and the `system_volume` + `data_volumes` split form.

import importlib.util
import pathlib
import sys
import types


def _stub_imports():
    """Stub the imports byteplus_ecs_instance needs at load time."""
    # ansible.module_utils.basic.AnsibleModule + env_fallback
    ansible = types.ModuleType('ansible')
    sys.modules.setdefault('ansible', ansible)
    mu = types.ModuleType('ansible.module_utils')
    sys.modules.setdefault('ansible.module_utils', mu)
    basic = types.ModuleType('ansible.module_utils.basic')
    basic.AnsibleModule = object
    basic.env_fallback = lambda *_a, **_kw: None
    sys.modules['ansible.module_utils.basic'] = basic

    # The collection-relative import path must resolve too. Provide
    # `ecs_common`-shaped stubs for the symbols the module imports.
    pkg_chain = [
        'ansible_collections',
        'ansible_collections.byteplus',
        'ansible_collections.fardani235.byteplus',
        'ansible_collections.fardani235.byteplus.plugins',
        'ansible_collections.fardani235.byteplus.plugins.module_utils',
    ]
    for name in pkg_chain:
        sys.modules.setdefault(name, types.ModuleType(name))

    ecs_common_stub = types.ModuleType(
        'ansible_collections.fardani235.byteplus.plugins.module_utils.ecs_common')

    class _Client:
        def __init__(self, *_a, **_kw):
            pass

    ecs_common_stub.ECSClient = _Client
    ecs_common_stub.INSTANCE_STATE_RUNNING = 'RUNNING'
    ecs_common_stub.INSTANCE_STATE_STOPPED = 'STOPPED'
    ecs_common_stub.build_run_request_models = lambda **kw: {}
    ecs_common_stub.resolve_credentials = lambda module: (
        'AK', 'SK', 'ap-southeast-1', None)
    sys.modules[
        'ansible_collections.fardani235.byteplus.plugins.module_utils.ecs_common'
    ] = ecs_common_stub


def _load_module():
    _stub_imports()
    repo_root = pathlib.Path(__file__).resolve().parents[4]
    module_path = repo_root / 'plugins' / 'modules' / 'byteplus_ecs_instance.py'
    spec = importlib.util.spec_from_file_location('byteplus_ecs_instance',
                                                   module_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ecs_module = _load_module()


class TestResolveVolumes:
    def test_none_when_nothing_set(self):
        assert ecs_module._resolve_volumes(None, None, None) is None

    def test_positional_pass_through(self):
        vols = [{'volume_type': 'ESSD_PL0', 'size': 40}]
        assert ecs_module._resolve_volumes(vols, None, None) is vols

    def test_split_form_builds_list(self):
        sys_v = {'volume_type': 'ESSD_PL0', 'size': 40}
        data_v = [
            {'volume_type': 'ESSD_PL1', 'size': 500},
            {'volume_type': 'ESSD_PL1', 'size': 200},
        ]
        out = ecs_module._resolve_volumes(None, sys_v, data_v)
        assert out == [sys_v, data_v[0], data_v[1]]
        # System volume is always first — that's the API contract.
        assert out[0] is sys_v

    def test_system_volume_only(self):
        sys_v = {'volume_type': 'ESSD_PL0', 'size': 40}
        assert ecs_module._resolve_volumes(None, sys_v, None) == [sys_v]

    def test_data_volumes_only(self):
        # No system_volume but data_volumes set — pass them through.
        # The user has to know this means BytePlus will refuse the request
        # (system disk is required); we don't second-guess that here.
        data_v = [{'volume_type': 'ESSD_PL1', 'size': 500}]
        assert ecs_module._resolve_volumes(None, None, data_v) == data_v

    def test_empty_list_treated_as_unset(self):
        # `volumes: []` from a playbook shouldn't suppress the split form.
        sys_v = {'volume_type': 'ESSD_PL0', 'size': 40}
        assert ecs_module._resolve_volumes([], sys_v, None) == [sys_v]
