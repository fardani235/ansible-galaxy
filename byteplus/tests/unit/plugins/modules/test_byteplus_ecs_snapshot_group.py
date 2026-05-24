# -*- coding: utf-8 -*-
# Tests for byteplus_ecs_snapshot_group helpers — specifically the strict
# rollback gate: the module MUST refuse to call RollbackSnapshotGroup
# unless the target instance is already STOPPED. Auto-stopping a running
# instance from a rollback is exactly the kind of surprise we don't want.

import importlib.util
import pathlib
import sys
import types
from unittest import mock

import pytest


def _stub_imports():
    """Stub the imports byteplus_ecs_snapshot_group needs at load time.

    Both module_utils dependencies (snapshot_common, ecs_common) are
    replaced with thin stubs so we can drive the unit under test in
    isolation.
    """
    ansible = types.ModuleType('ansible')
    sys.modules.setdefault('ansible', ansible)
    mu = types.ModuleType('ansible.module_utils')
    sys.modules.setdefault('ansible.module_utils', mu)
    basic = types.ModuleType('ansible.module_utils.basic')

    class _FailJsonExit(SystemExit):
        """Raised in place of AnsibleModule.fail_json. The module would
        normally SystemExit here; tests can catch the exception and
        inspect msg/kwargs."""
        def __init__(self, **kwargs):
            super().__init__(1)
            self.kwargs = kwargs

    basic._FailJsonExit = _FailJsonExit
    basic.AnsibleModule = object
    basic.env_fallback = lambda *_a, **_kw: None
    sys.modules['ansible.module_utils.basic'] = basic

    pkg_chain = [
        'ansible_collections',
        'ansible_collections.fardani235',
        'ansible_collections.fardani235.byteplus',
        'ansible_collections.fardani235.byteplus.plugins',
        'ansible_collections.fardani235.byteplus.plugins.module_utils',
    ]
    for name in pkg_chain:
        sys.modules.setdefault(name, types.ModuleType(name))

    sc_stub = types.ModuleType(
        'ansible_collections.fardani235.byteplus.plugins.module_utils.snapshot_common')

    class _SnapClient:
        def __init__(self, *_a, **_kw):
            self.calls = []

        def rollback_snapshot_group(self, **kw):
            self.calls.append(('rollback', kw))
            return {}

    sc_stub.SnapshotClient = _SnapClient
    sc_stub.SNAPSHOT_STATE_AVAILABLE = 'available'
    sc_stub.resolve_credentials = lambda module: ('AK', 'SK', 'r', None)
    sys.modules[
        'ansible_collections.fardani235.byteplus.plugins.module_utils.snapshot_common'
    ] = sc_stub

    ec_stub = types.ModuleType(
        'ansible_collections.fardani235.byteplus.plugins.module_utils.ecs_common')

    class _ECSClient:
        # Mutated by tests to control the instance state seen by the unit
        # under test.
        instance_state = 'STOPPED'

        def __init__(self, *_a, **_kw):
            pass

        def get_instance(self, _id):
            if _ECSClient.instance_state is None:
                return None
            return {'instance_id': _id, 'status': _ECSClient.instance_state}

    ec_stub.ECSClient = _ECSClient
    ec_stub.INSTANCE_STATE_STOPPED = 'STOPPED'
    sys.modules[
        'ansible_collections.fardani235.byteplus.plugins.module_utils.ecs_common'
    ] = ec_stub

    return basic, sc_stub, ec_stub


def _load_module():
    basic, sc_stub, ec_stub = _stub_imports()
    repo_root = pathlib.Path(__file__).resolve().parents[4]
    module_path = (repo_root / 'plugins' / 'modules'
                   / 'byteplus_ecs_snapshot_group.py')
    spec = importlib.util.spec_from_file_location(
        'byteplus_ecs_snapshot_group', module_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, basic, sc_stub, ec_stub


snap_group_mod, basic_stub, sc_stub, ec_stub = _load_module()


class _FakeModule:
    """Minimal AnsibleModule stand-in for unit-testing _do_rollback."""

    def __init__(self, params, check_mode=False):
        self.params = params
        self.check_mode = check_mode
        self.exit_kwargs = None

    def fail_json(self, **kwargs):
        raise basic_stub._FailJsonExit(**kwargs)

    def exit_json(self, **kwargs):
        self.exit_kwargs = kwargs
        raise basic_stub._FailJsonExit(**kwargs)


class TestDoRollbackStrictness:
    """The module is intentionally strict: instance MUST be STOPPED."""

    def _params(self, **overrides):
        base = {
            'instance_id': 'i-abc',
            'snapshot_ids': None,
            'volume_ids': None,
            'client_token': None,
        }
        base.update(overrides)
        return base

    def test_fails_when_instance_running(self):
        ec_stub.ECSClient.instance_state = 'RUNNING'
        m = _FakeModule(self._params())
        snap_client = sc_stub.SnapshotClient()
        ecs_client = ec_stub.ECSClient()
        with pytest.raises(basic_stub._FailJsonExit) as ei:
            snap_group_mod._do_rollback(
                m, snap_client, ecs_client,
                {'snapshot_group_id': 'g1'}, 'g1')
        # Error must clearly explain the required state and how to fix.
        msg = ei.value.kwargs['msg']
        assert 'STOPPED' in msg
        assert 'RUNNING' in msg
        # And we must NOT have called rollback.
        assert snap_client.calls == []

    def test_fails_when_instance_starting(self):
        # Any non-STOPPED state is rejected, including transitional ones.
        ec_stub.ECSClient.instance_state = 'STARTING'
        m = _FakeModule(self._params())
        with pytest.raises(basic_stub._FailJsonExit):
            snap_group_mod._do_rollback(
                m, sc_stub.SnapshotClient(), ec_stub.ECSClient(),
                {'snapshot_group_id': 'g1'}, 'g1')

    def test_fails_when_instance_missing(self):
        ec_stub.ECSClient.instance_state = None  # get_instance → None
        m = _FakeModule(self._params())
        with pytest.raises(basic_stub._FailJsonExit) as ei:
            snap_group_mod._do_rollback(
                m, sc_stub.SnapshotClient(), ec_stub.ECSClient(),
                {'snapshot_group_id': 'g1'}, 'g1')
        assert 'not found' in ei.value.kwargs['msg']

    def test_proceeds_when_instance_stopped(self):
        ec_stub.ECSClient.instance_state = 'STOPPED'
        m = _FakeModule(self._params())
        snap_client = sc_stub.SnapshotClient()
        with pytest.raises(basic_stub._FailJsonExit):
            # exit_json raises in our fake — that's the "success" signal.
            snap_group_mod._do_rollback(
                m, snap_client, ec_stub.ECSClient(),
                {'snapshot_group_id': 'g1'}, 'g1')
        # Rollback WAS called.
        assert len(snap_client.calls) == 1
        kind, kw = snap_client.calls[0]
        assert kind == 'rollback'
        assert kw['snapshot_group_id'] == 'g1'
        assert kw['instance_id'] == 'i-abc'

    def test_check_mode_does_not_call_rollback(self):
        ec_stub.ECSClient.instance_state = 'STOPPED'
        m = _FakeModule(self._params(), check_mode=True)
        snap_client = sc_stub.SnapshotClient()
        with pytest.raises(basic_stub._FailJsonExit):
            snap_group_mod._do_rollback(
                m, snap_client, ec_stub.ECSClient(),
                {'snapshot_group_id': 'g1'}, 'g1')
        assert snap_client.calls == []

    def test_missing_instance_id_falls_back_to_group_metadata(self):
        # When the user doesn't pass instance_id but the group itself
        # records it, we use that — still subject to the STOPPED check.
        ec_stub.ECSClient.instance_state = 'STOPPED'
        m = _FakeModule(self._params(instance_id=None))
        snap_client = sc_stub.SnapshotClient()
        with pytest.raises(basic_stub._FailJsonExit):
            snap_group_mod._do_rollback(
                m, snap_client, ec_stub.ECSClient(),
                {'snapshot_group_id': 'g1', 'instance_id': 'i-fallback'}, 'g1')
        kind, kw = snap_client.calls[0]
        assert kw['instance_id'] == 'i-fallback'

    def test_missing_instance_id_with_no_fallback_fails(self):
        m = _FakeModule(self._params(instance_id=None))
        with pytest.raises(basic_stub._FailJsonExit) as ei:
            snap_group_mod._do_rollback(
                m, sc_stub.SnapshotClient(), ec_stub.ECSClient(),
                {'snapshot_group_id': 'g1'}, 'g1')
        assert 'instance_id is required' in ei.value.kwargs['msg']


class TestDiscoverInstanceVolumeIds:
    """Regression: BytePlus CreateSnapshotGroup rejects requests with no
    VolumeIds despite the SDK contract marking it optional. We must
    discover the instance's volumes when the caller omits volume_ids."""

    def _ecs_client(self, instance_payload):
        class _C:
            def get_instance(self_inner, _id):
                return instance_payload
        return _C()

    def test_returns_volume_ids_from_volumes_field(self):
        client = self._ecs_client({
            'instance_id': 'i-1',
            'volumes': [
                {'volume_id': 'vol-1'},
                {'volume_id': 'vol-2'},
            ],
        })
        assert snap_group_mod._discover_instance_volume_ids(
            client, 'i-1') == ['vol-1', 'vol-2']

    def test_accepts_pascal_case_keys(self):
        # Some DescribeInstances responses come back with PascalCase keys
        # depending on which serialization path the SDK took.
        client = self._ecs_client({
            'InstanceId': 'i-1',
            'Volumes': [{'VolumeId': 'vol-1'}],
        })
        assert snap_group_mod._discover_instance_volume_ids(
            client, 'i-1') == ['vol-1']

    def test_returns_empty_when_instance_has_no_volumes(self):
        client = self._ecs_client(
            {'instance_id': 'i-1', 'volumes': []})
        assert snap_group_mod._discover_instance_volume_ids(
            client, 'i-1') == []

    def test_returns_none_when_instance_missing(self):
        client = self._ecs_client(None)
        assert snap_group_mod._discover_instance_volume_ids(
            client, 'i-1') is None
