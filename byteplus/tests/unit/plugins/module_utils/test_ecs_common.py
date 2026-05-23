# -*- coding: utf-8 -*-
# Tests for ECSClient logic that doesn't require live API calls:
# - find_instance_by_name disambiguation (raises on ambiguity)
# - describe_all_instances pagination
# - wait_for_state termination conditions
#
# The actual SDK request models are stubbed; only the orchestration logic
# in ECSClient is exercised.

import importlib.util
import pathlib
import sys
import time
import types
from unittest import mock

import pytest


def _stub_sdk():
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
        def __init__(self, status=0, reason=''):
            self.status = status
            self.reason = reason
    rest_mod.ApiException = _ApiException
    sys.modules['byteplussdkcore.rest'] = rest_mod

    # Stub byteplussdkecs.api.ecs_api.ECSApi
    bp_ecs = types.ModuleType('byteplussdkecs')
    bp_ecs_api = types.ModuleType('byteplussdkecs.api')
    ecs_api_mod = types.ModuleType('byteplussdkecs.api.ecs_api')

    class _ECSApi:
        def __init__(self, api_client=None):
            self.api_client = api_client
            self.calls = []
    ecs_api_mod.ECSApi = _ECSApi
    sys.modules['byteplussdkecs'] = bp_ecs
    sys.modules['byteplussdkecs.api'] = bp_ecs_api
    sys.modules['byteplussdkecs.api.ecs_api'] = ecs_api_mod

    # Stub each request model as a trivial dataclass-like object.
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
    ]:
        mod = types.ModuleType('byteplussdkecs.models.' + snake)

        class _Req:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
        _Req.__name__ = cls
        setattr(mod, cls, _Req)
        sys.modules['byteplussdkecs.models.' + snake] = mod


def _load_ecs_common():
    _stub_sdk()
    repo_root = pathlib.Path(__file__).resolve().parents[4]
    module_path = repo_root / 'plugins' / 'module_utils' / 'ecs_common.py'
    spec = importlib.util.spec_from_file_location('ecs_common', module_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ecs = _load_ecs_common()


def _make_client():
    return ecs.ECSClient('AKID', 'SECRET', 'ap-southeast-1')


class TestFindInstanceByName:
    def test_single_match_returns(self):
        client = _make_client()
        client.describe_all_instances = mock.Mock(return_value=[
            {'instance_id': 'i-1', 'instance_name': 'web-01'},
        ])
        result = client.find_instance_by_name('web-01')
        assert result['instance_id'] == 'i-1'

    def test_no_match_returns_none(self):
        client = _make_client()
        client.describe_all_instances = mock.Mock(return_value=[])
        assert client.find_instance_by_name('missing') is None

    def test_multiple_matches_raises(self):
        # Regression: name is not unique in ECS — must not silently pick one.
        client = _make_client()
        client.describe_all_instances = mock.Mock(return_value=[
            {'instance_id': 'i-1', 'instance_name': 'web-01'},
            {'instance_id': 'i-2', 'instance_name': 'web-01'},
        ])
        with pytest.raises(Exception, match='Multiple ECS instances'):
            client.find_instance_by_name('web-01')

    def test_project_name_narrows_search(self):
        # When name collides across projects, project_name routes the
        # filter into the describe call so only one project's matches return.
        client = _make_client()
        client.describe_all_instances = mock.Mock(return_value=[
            {'instance_id': 'i-prod', 'instance_name': 'web-01'},
        ])
        result = client.find_instance_by_name('web-01', project_name='prod')
        assert result['instance_id'] == 'i-prod'
        # The project_name must reach describe_all_instances as a filter.
        kwargs = client.describe_all_instances.call_args.kwargs
        assert kwargs.get('project_name') == 'prod'

    def test_duplicate_error_mentions_project_when_unset(self):
        client = _make_client()
        client.describe_all_instances = mock.Mock(return_value=[
            {'instance_id': 'i-1', 'instance_name': 'web-01'},
            {'instance_id': 'i-2', 'instance_name': 'web-01'},
        ])
        with pytest.raises(Exception, match='project_name'):
            client.find_instance_by_name('web-01')

    def test_prefix_match_excluded(self):
        # The API may return prefix matches; the helper must filter to exact.
        client = _make_client()
        client.describe_all_instances = mock.Mock(return_value=[
            {'instance_id': 'i-1', 'instance_name': 'web-01'},
            {'instance_id': 'i-2', 'instance_name': 'web-01-canary'},
        ])
        result = client.find_instance_by_name('web-01')
        assert result['instance_id'] == 'i-1'


class TestDescribeAllInstancesPagination:
    def test_aggregates_pages(self):
        client = _make_client()
        pages = [
            {'instances': [{'instance_id': 'i-1'}], 'next_token': 'tok2'},
            {'instances': [{'instance_id': 'i-2'}], 'next_token': 'tok3'},
            {'instances': [{'instance_id': 'i-3'}], 'next_token': None},
        ]
        client.describe_instances = mock.Mock(side_effect=pages)
        result = client.describe_all_instances(zone_id='zone-a')
        assert [r['instance_id'] for r in result] == ['i-1', 'i-2', 'i-3']
        assert client.describe_instances.call_count == 3

    def test_handles_capitalized_keys(self):
        # The SDK's response shape isn't strictly normalized; the helper
        # accepts both lowercase and PascalCase keys.
        client = _make_client()
        client.describe_instances = mock.Mock(return_value={
            'Instances': [{'InstanceId': 'i-1'}],
            'NextToken': None,
        })
        result = client.describe_all_instances()
        assert len(result) == 1


class TestBuildRunRequestModels:
    """Regression: raw dicts in `volumes`/`network_interfaces`/`tags`
    serialize with snake_case keys instead of the API's PascalCase. The
    helper must wrap them in SDK model objects so attribute_map kicks in.
    """

    def test_volume_basic(self):
        out = ecs.build_run_request_models(
            volumes=[{'volume_type': 'ESSD_PL0', 'size': 100,
                      'delete_with_instance': True}],
        )
        assert 'volumes' in out
        assert len(out['volumes']) == 1
        v = out['volumes'][0]
        # Stub VolumeForRunInstancesInput just stashes kwargs onto __dict__
        assert v.volume_type == 'ESSD_PL0'
        assert v.size == 100
        assert v.delete_with_instance is True

    def test_volume_requires_volume_type(self):
        with pytest.raises(ValueError, match='volume_type is required'):
            ecs.build_run_request_models(volumes=[{'size': 100}])

    def test_volume_size_must_be_int(self):
        with pytest.raises(ValueError, match='size must be an int'):
            ecs.build_run_request_models(
                volumes=[{'volume_type': 'ESSD_PL0', 'size': '100GB'}])

    def test_volume_rejects_unknown_field(self):
        # Regression: silently dropping unknown fields would mean a user's
        # typo (e.g. sizeGB instead of size) launches with the wrong size.
        with pytest.raises(ValueError, match='unknown field'):
            ecs.build_run_request_models(
                volumes=[{'volume_type': 'ESSD_PL0', 'sizeGB': 100}])

    def test_volume_non_dict_rejected(self):
        with pytest.raises(ValueError, match='must be a dict'):
            ecs.build_run_request_models(volumes=['ESSD_PL0:100'])

    def test_nic_basic(self):
        out = ecs.build_run_request_models(
            network_interfaces=[{'subnet_id': 'sn-1',
                                  'security_group_ids': ['sg-1', 'sg-2']}],
        )
        assert out['network_interfaces'][0].subnet_id == 'sn-1'

    def test_tag_requires_key(self):
        with pytest.raises(ValueError, match='key is required'):
            ecs.build_run_request_models(tags=[{'value': 'prod'}])

    def test_tag_rejects_unknown(self):
        with pytest.raises(ValueError, match='unknown field'):
            ecs.build_run_request_models(
                tags=[{'key': 'env', 'value': 'prod', 'category': 'oops'}])

    def test_all_none_returns_empty_dict(self):
        assert ecs.build_run_request_models() == {}

    def test_multiple_volumes(self):
        out = ecs.build_run_request_models(volumes=[
            {'volume_type': 'ESSD_PL0', 'size': 40},
            {'volume_type': 'ESSD_PL1', 'size': 500},
        ])
        assert len(out['volumes']) == 2


class TestWaitForState:
    def test_returns_when_target_reached(self):
        client = _make_client()
        client.get_instance = mock.Mock(side_effect=[
            {'instance_id': 'i-1', 'status': 'STARTING'},
            {'instance_id': 'i-1', 'status': 'RUNNING'},
        ])
        with mock.patch.object(time, 'sleep'):
            inst = client.wait_for_state('i-1', ecs.INSTANCE_STATE_RUNNING,
                                         timeout=10, interval=0)
        assert inst['status'] == 'RUNNING'

    def test_deleted_target_accepts_missing(self):
        # Once the instance is gone, wait_for_state('DELETED', ...) succeeds.
        client = _make_client()
        client.get_instance = mock.Mock(return_value=None)
        with mock.patch.object(time, 'sleep'):
            assert client.wait_for_state('i-1', 'DELETED', timeout=10, interval=0) is None

    def test_timeout_raises(self):
        client = _make_client()
        client.get_instance = mock.Mock(return_value={'status': 'STARTING'})
        with mock.patch.object(time, 'sleep'):
            with pytest.raises(Exception, match='Timed out'):
                # timeout=0 means "deadline already past" — first poll fires
                # then the loop exits.
                client.wait_for_state('i-1', ecs.INSTANCE_STATE_RUNNING,
                                      timeout=0, interval=0)
