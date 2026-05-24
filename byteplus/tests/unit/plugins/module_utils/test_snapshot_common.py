# -*- coding: utf-8 -*-
# Tests for SnapshotClient orchestration logic in snapshot_common.py:
# - paginated describe_all_snapshots (next_token cursoring)
# - paginated describe_all_snapshot_groups (page_number cursoring)
# - find_*_by_name disambiguation (raises on ambiguity)
# - wait_for_snapshot_state terminal-state handling
# - tag validation in _build_tags
#
# The SDK is fully stubbed; only the wrapper logic is exercised.

import importlib.util
import pathlib
import sys
import time
import types
from unittest import mock

import pytest


def _stub_core_sdk():
    """Shared core / api_client / rest stubs (same shape as test_ecs_common)."""
    bp_core = types.ModuleType('byteplussdkcore')
    sys.modules.setdefault('byteplussdkcore', bp_core)

    config_mod = types.ModuleType('byteplussdkcore.configuration')

    class _Config:
        def __init__(self):
            self.ak = self.sk = self.region = None
            self.session_token = None
            self.host = None
    config_mod.Configuration = _Config
    sys.modules['byteplussdkcore.configuration'] = config_mod

    apiclient_mod = types.ModuleType('byteplussdkcore.api_client')

    class _ApiClient:
        def __init__(self, configuration=None):
            self.configuration = configuration
    apiclient_mod.ApiClient = _ApiClient
    sys.modules['byteplussdkcore.api_client'] = apiclient_mod

    rest_mod = types.ModuleType('byteplussdkcore.rest')

    class _ApiException(Exception):
        def __init__(self, status=0, reason='', body=None):
            self.status = status
            self.reason = reason
            self.body = body
    rest_mod.ApiException = _ApiException
    sys.modules['byteplussdkcore.rest'] = rest_mod


def _stub_ecs_sdk():
    """Stubs for the ecs SDK — needed because snapshot_common imports
    _format_api_error from ecs_common, which transitively pulls in the
    ecs SDK."""
    bp_ecs = types.ModuleType('byteplussdkecs')
    bp_ecs_api = types.ModuleType('byteplussdkecs.api')
    ecs_api_mod = types.ModuleType('byteplussdkecs.api.ecs_api')

    class _ECSApi:
        def __init__(self, api_client=None):
            self.api_client = api_client
    ecs_api_mod.ECSApi = _ECSApi
    sys.modules['byteplussdkecs'] = bp_ecs
    sys.modules['byteplussdkecs.api'] = bp_ecs_api
    sys.modules['byteplussdkecs.api.ecs_api'] = ecs_api_mod

    models_mod = types.ModuleType('byteplussdkecs.models')
    sys.modules['byteplussdkecs.models'] = models_mod
    for snake, cls in [
        ('run_instances_request', 'RunInstancesRequest'),
        ('describe_instances_request', 'DescribeInstancesRequest'),
        ('start_instances_request', 'StartInstancesRequest'),
        ('stop_instances_request', 'StopInstancesRequest'),
        ('reboot_instances_request', 'RebootInstancesRequest'),
        ('delete_instances_request', 'DeleteInstancesRequest'),
        ('volume_for_run_instances_input', 'VolumeForRunInstancesInput'),
        ('network_interface_for_run_instances_input',
         'NetworkInterfaceForRunInstancesInput'),
        ('tag_for_run_instances_input', 'TagForRunInstancesInput'),
        ('eip_address_for_run_instances_input',
         'EipAddressForRunInstancesInput'),
    ]:
        mod = types.ModuleType('byteplussdkecs.models.' + snake)

        class _Req:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
        _Req.__name__ = cls
        setattr(mod, cls, _Req)
        sys.modules['byteplussdkecs.models.' + snake] = mod


def _stub_ebs_sdk():
    """Stubs for byteplussdkstorageebs.* — request models and the API class."""
    bp_ebs = types.ModuleType('byteplussdkstorageebs')
    bp_ebs_api = types.ModuleType('byteplussdkstorageebs.api')
    ebs_api_mod = types.ModuleType('byteplussdkstorageebs.api.storage_ebs_api')

    class _EBSApi:
        def __init__(self, api_client=None):
            self.api_client = api_client
            # Tests override these in-place with mocks.
            self.calls = []
    ebs_api_mod.STORAGEEBSApi = _EBSApi
    sys.modules['byteplussdkstorageebs'] = bp_ebs
    sys.modules['byteplussdkstorageebs.api'] = bp_ebs_api
    sys.modules['byteplussdkstorageebs.api.storage_ebs_api'] = ebs_api_mod

    models_mod = types.ModuleType('byteplussdkstorageebs.models')
    sys.modules['byteplussdkstorageebs.models'] = models_mod

    for snake, cls in [
        ('create_snapshot_request', 'CreateSnapshotRequest'),
        ('create_snapshot_group_request', 'CreateSnapshotGroupRequest'),
        ('delete_snapshot_request', 'DeleteSnapshotRequest'),
        ('delete_snapshot_group_request', 'DeleteSnapshotGroupRequest'),
        ('describe_snapshots_request', 'DescribeSnapshotsRequest'),
        ('describe_snapshot_groups_request', 'DescribeSnapshotGroupsRequest'),
        ('rollback_snapshot_group_request', 'RollbackSnapshotGroupRequest'),
        ('tag_for_create_snapshot_input', 'TagForCreateSnapshotInput'),
        ('tag_for_create_snapshot_group_input',
         'TagForCreateSnapshotGroupInput'),
    ]:
        mod = types.ModuleType('byteplussdkstorageebs.models.' + snake)

        class _Req:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
        _Req.__name__ = cls
        setattr(mod, cls, _Req)
        sys.modules['byteplussdkstorageebs.models.' + snake] = mod


def _load_snapshot_common():
    _stub_core_sdk()
    _stub_ecs_sdk()
    _stub_ebs_sdk()

    repo_root = pathlib.Path(__file__).resolve().parents[4]

    # Register the ansible_collections.* package chain so the
    # `from ansible_collections...ecs_common import _format_api_error`
    # at the top of snapshot_common can resolve to a real module.
    for pkg in [
        'ansible_collections',
        'ansible_collections.fardani235',
        'ansible_collections.fardani235.byteplus',
        'ansible_collections.fardani235.byteplus.plugins',
        'ansible_collections.fardani235.byteplus.plugins.module_utils',
    ]:
        sys.modules.setdefault(pkg, types.ModuleType(pkg))

    ec_path = repo_root / 'plugins' / 'module_utils' / 'ecs_common.py'
    ec_spec = importlib.util.spec_from_file_location(
        'ansible_collections.fardani235.byteplus.plugins.module_utils.ecs_common',
        ec_path)
    assert ec_spec is not None and ec_spec.loader is not None
    ec_mod = importlib.util.module_from_spec(ec_spec)
    ec_spec.loader.exec_module(ec_mod)
    sys.modules[
        'ansible_collections.fardani235.byteplus.plugins.module_utils.ecs_common'
    ] = ec_mod

    sc_path = repo_root / 'plugins' / 'module_utils' / 'snapshot_common.py'
    sc_spec = importlib.util.spec_from_file_location('snapshot_common', sc_path)
    assert sc_spec is not None and sc_spec.loader is not None
    sc_mod = importlib.util.module_from_spec(sc_spec)
    sc_spec.loader.exec_module(sc_mod)
    return sc_mod


snap = _load_snapshot_common()


def _make_client():
    return snap.SnapshotClient('AKID', 'SECRET', 'ap-southeast-1')


class TestBuildTags:
    def test_none_returns_none(self):
        assert snap._build_tags(None, lambda **kw: kw) is None

    def test_empty_list_returns_none(self):
        assert snap._build_tags([], lambda **kw: kw) is None

    def test_valid_tags_wrapped(self):
        out = snap._build_tags(
            [{'key': 'env', 'value': 'prod'}], lambda **kw: kw)
        assert out == [{'key': 'env', 'value': 'prod'}]

    def test_unknown_field_rejected(self):
        with pytest.raises(ValueError, match='unknown field'):
            snap._build_tags(
                [{'key': 'env', 'value': 'prod', 'extra': 'nope'}],
                lambda **kw: kw)

    def test_missing_key_rejected(self):
        with pytest.raises(ValueError, match='key is required'):
            snap._build_tags([{'value': 'prod'}], lambda **kw: kw)

    def test_non_dict_rejected(self):
        with pytest.raises(ValueError, match='must be a dict'):
            snap._build_tags(['env=prod'], lambda **kw: kw)


class TestDescribeAllSnapshots:
    def test_single_page_returns_results(self):
        client = _make_client()
        client.describe_snapshots = mock.Mock(return_value={
            'snapshots': [{'snapshot_id': 'snap-1'}, {'snapshot_id': 'snap-2'}],
            'next_token': None,
        })
        result = client.describe_all_snapshots(volume_id='vol-1')
        assert [s['snapshot_id'] for s in result] == ['snap-1', 'snap-2']

    def test_pagination_follows_next_token(self):
        # Two pages — must collect both and stop when next_token vanishes.
        client = _make_client()
        responses = [
            {'snapshots': [{'snapshot_id': 'snap-1'}],
             'next_token': 'cursor-2'},
            {'snapshots': [{'snapshot_id': 'snap-2'}],
             'next_token': None},
        ]
        client.describe_snapshots = mock.Mock(side_effect=responses)
        result = client.describe_all_snapshots()
        assert [s['snapshot_id'] for s in result] == ['snap-1', 'snap-2']
        # First call has no next_token; second carries the cursor through.
        first = client.describe_snapshots.call_args_list[0].kwargs
        second = client.describe_snapshots.call_args_list[1].kwargs
        assert 'next_token' not in first
        assert second['next_token'] == 'cursor-2'

    def test_empty_response_terminates(self):
        client = _make_client()
        client.describe_snapshots = mock.Mock(return_value={})
        assert client.describe_all_snapshots() == []


class TestDescribeAllSnapshotGroups:
    def test_pagination_uses_page_number(self):
        # Snapshot groups use page_number cursoring, NOT next_token —
        # they're a different endpoint shape.
        client = _make_client()
        responses = [
            # Full page → keep going.
            {'snapshot_groups':
                [{'snapshot_group_id': 'g{}'.format(i)} for i in range(100)]},
            # Short page → stop.
            {'snapshot_groups': [{'snapshot_group_id': 'g100'}]},
        ]
        client.describe_snapshot_groups = mock.Mock(side_effect=responses)
        result = client.describe_all_snapshot_groups()
        assert len(result) == 101
        # Verify the helper actually incremented page_number.
        first = client.describe_snapshot_groups.call_args_list[0].kwargs
        second = client.describe_snapshot_groups.call_args_list[1].kwargs
        assert first['page_number'] == 1
        assert second['page_number'] == 2

    def test_short_first_page_terminates(self):
        client = _make_client()
        client.describe_snapshot_groups = mock.Mock(return_value={
            'snapshot_groups': [{'snapshot_group_id': 'g1'}],
        })
        result = client.describe_all_snapshot_groups()
        assert len(result) == 1
        assert client.describe_snapshot_groups.call_count == 1


class TestFindSnapshotByName:
    def test_single_match_returns(self):
        client = _make_client()
        client.describe_all_snapshots = mock.Mock(return_value=[
            {'snapshot_id': 'snap-1', 'snapshot_name': 'backup-1'},
        ])
        assert client.find_snapshot_by_name(
            'backup-1')['snapshot_id'] == 'snap-1'

    def test_no_match_returns_none(self):
        client = _make_client()
        client.describe_all_snapshots = mock.Mock(return_value=[])
        assert client.find_snapshot_by_name('missing') is None

    def test_multiple_matches_raises(self):
        client = _make_client()
        client.describe_all_snapshots = mock.Mock(return_value=[
            {'snapshot_id': 'snap-1', 'snapshot_name': 'backup-1'},
            {'snapshot_id': 'snap-2', 'snapshot_name': 'backup-1'},
        ])
        with pytest.raises(Exception, match='Multiple EBS snapshots'):
            client.find_snapshot_by_name('backup-1')

    def test_prefix_match_excluded(self):
        # The API may filter by prefix; we must enforce exact.
        client = _make_client()
        client.describe_all_snapshots = mock.Mock(return_value=[
            {'snapshot_id': 'snap-1', 'snapshot_name': 'backup-1'},
            {'snapshot_id': 'snap-2', 'snapshot_name': 'backup-10'},
        ])
        result = client.find_snapshot_by_name('backup-1')
        assert result['snapshot_id'] == 'snap-1'


class TestFindSnapshotGroupByName:
    def test_multiple_matches_raises(self):
        client = _make_client()
        client.describe_all_snapshot_groups = mock.Mock(return_value=[
            {'snapshot_group_id': 'g1', 'name': 'pre-deploy'},
            {'snapshot_group_id': 'g2', 'name': 'pre-deploy'},
        ])
        with pytest.raises(Exception, match='Multiple snapshot groups'):
            client.find_snapshot_group_by_name('pre-deploy')

    def test_single_match_returns(self):
        client = _make_client()
        client.describe_all_snapshot_groups = mock.Mock(return_value=[
            {'snapshot_group_id': 'g1', 'name': 'pre-deploy'},
        ])
        result = client.find_snapshot_group_by_name('pre-deploy')
        assert result['snapshot_group_id'] == 'g1'


class TestWaitForSnapshotState:
    def test_returns_when_state_reached(self, monkeypatch):
        client = _make_client()
        client.get_snapshot = mock.Mock(return_value={
            'snapshot_id': 'snap-1', 'status': 'available'})
        monkeypatch.setattr(time, 'sleep', lambda *_: None)
        result = client.wait_for_snapshot_state('snap-1', interval=0)
        assert result['snapshot_id'] == 'snap-1'

    def test_polls_until_state_reached(self, monkeypatch):
        client = _make_client()
        responses = [
            {'snapshot_id': 'snap-1', 'status': 'creating'},
            {'snapshot_id': 'snap-1', 'status': 'creating'},
            {'snapshot_id': 'snap-1', 'status': 'available'},
        ]
        client.get_snapshot = mock.Mock(side_effect=responses)
        monkeypatch.setattr(time, 'sleep', lambda *_: None)
        result = client.wait_for_snapshot_state('snap-1', interval=0)
        assert result['status'] == 'available'
        assert client.get_snapshot.call_count == 3

    def test_failed_state_raises_immediately(self, monkeypatch):
        # Don't keep polling a doomed snapshot — surface 'failed' loudly.
        client = _make_client()
        client.get_snapshot = mock.Mock(return_value={
            'snapshot_id': 'snap-1', 'status': 'failed'})
        monkeypatch.setattr(time, 'sleep', lambda *_: None)
        with pytest.raises(Exception, match="terminal state 'failed'"):
            client.wait_for_snapshot_state('snap-1', interval=0)

    def test_deleted_target_succeeds_on_missing(self, monkeypatch):
        client = _make_client()
        client.get_snapshot = mock.Mock(return_value=None)
        monkeypatch.setattr(time, 'sleep', lambda *_: None)
        # Returns None for a successful delete wait — must not raise.
        assert client.wait_for_snapshot_state(
            'snap-1', target_state='DELETED', interval=0) is None

    def test_timeout_raises(self, monkeypatch):
        client = _make_client()
        client.get_snapshot = mock.Mock(return_value={
            'snapshot_id': 'snap-1', 'status': 'creating'})
        monkeypatch.setattr(time, 'sleep', lambda *_: None)
        with pytest.raises(Exception, match='Timed out'):
            client.wait_for_snapshot_state(
                'snap-1', timeout=-1, interval=0)


class TestStatusOf:
    def test_handles_multiple_casings(self):
        # The API returns the status field under different keys depending
        # on which endpoint produced the dict — _status_of must paper over.
        assert snap._status_of({'status': 'available'}) == 'available'
        assert snap._status_of({'Status': 'available'}) == 'available'
        assert snap._status_of({'snapshot_status': 'available'}) == 'available'
        assert snap._status_of({'SnapshotStatus': 'available'}) == 'available'
        assert snap._status_of(None) is None
        assert snap._status_of({}) is None
