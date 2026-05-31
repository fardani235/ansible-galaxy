# -*- coding: utf-8 -*-
# Tests for VPCClient orchestration logic:
# - tag validation
# - pagination across describe_* calls
# - name + project_name disambiguation for vpc / subnet / security_group

import importlib.util
import pathlib
import sys
import types
from unittest import mock

import pytest


def _stub_sdk():
    """Stub the byteplussdkcore + byteplussdkvpc surfaces vpc_common imports."""
    # Core
    sys.modules.setdefault('byteplussdkcore', types.ModuleType('byteplussdkcore'))

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

    # VPC package
    sys.modules.setdefault('byteplussdkvpc', types.ModuleType('byteplussdkvpc'))
    sys.modules.setdefault('byteplussdkvpc.api', types.ModuleType('byteplussdkvpc.api'))
    sys.modules.setdefault('byteplussdkvpc.models',
                           types.ModuleType('byteplussdkvpc.models'))

    api_mod = types.ModuleType('byteplussdkvpc.api.vpc_api')

    class _VPCApi:
        def __init__(self, api_client=None):
            self.api_client = api_client
    api_mod.VPCApi = _VPCApi
    sys.modules['byteplussdkvpc.api.vpc_api'] = api_mod

    request_models = [
        ('create_vpc_request', 'CreateVpcRequest'),
        ('delete_vpc_request', 'DeleteVpcRequest'),
        ('describe_vpcs_request', 'DescribeVpcsRequest'),
        ('modify_vpc_attributes_request', 'ModifyVpcAttributesRequest'),
        ('create_subnet_request', 'CreateSubnetRequest'),
        ('delete_subnet_request', 'DeleteSubnetRequest'),
        ('describe_subnets_request', 'DescribeSubnetsRequest'),
        ('modify_subnet_attributes_request', 'ModifySubnetAttributesRequest'),
        ('create_security_group_request', 'CreateSecurityGroupRequest'),
        ('delete_security_group_request', 'DeleteSecurityGroupRequest'),
        ('describe_security_groups_request', 'DescribeSecurityGroupsRequest'),
        ('modify_security_group_attributes_request',
         'ModifySecurityGroupAttributesRequest'),
        ('tag_for_create_vpc_input', 'TagForCreateVpcInput'),
        ('tag_for_create_subnet_input', 'TagForCreateSubnetInput'),
        ('tag_for_create_security_group_input', 'TagForCreateSecurityGroupInput'),
        ('authorize_security_group_ingress_request',
         'AuthorizeSecurityGroupIngressRequest'),
        ('authorize_security_group_egress_request',
         'AuthorizeSecurityGroupEgressRequest'),
        ('revoke_security_group_ingress_request',
         'RevokeSecurityGroupIngressRequest'),
        ('revoke_security_group_egress_request',
         'RevokeSecurityGroupEgressRequest'),
        ('describe_security_group_attributes_request',
         'DescribeSecurityGroupAttributesRequest'),
        ('modify_security_group_rule_descriptions_ingress_request',
         'ModifySecurityGroupRuleDescriptionsIngressRequest'),
        ('modify_security_group_rule_descriptions_egress_request',
         'ModifySecurityGroupRuleDescriptionsEgressRequest'),
        ('create_prefix_list_request', 'CreatePrefixListRequest'),
        ('delete_prefix_list_request', 'DeletePrefixListRequest'),
        ('describe_prefix_lists_request', 'DescribePrefixListsRequest'),
        ('describe_prefix_list_entries_request',
         'DescribePrefixListEntriesRequest'),
        ('modify_prefix_list_request', 'ModifyPrefixListRequest'),
        ('prefix_list_entry_for_create_prefix_list_input',
         'PrefixListEntryForCreatePrefixListInput'),
        ('add_prefix_list_entry_for_modify_prefix_list_input',
         'AddPrefixListEntryForModifyPrefixListInput'),
        ('remove_prefix_list_entry_for_modify_prefix_list_input',
         'RemovePrefixListEntryForModifyPrefixListInput'),
        ('tag_for_create_prefix_list_input', 'TagForCreatePrefixListInput'),
        ('create_route_table_request', 'CreateRouteTableRequest'),
        ('delete_route_table_request', 'DeleteRouteTableRequest'),
        ('describe_route_table_list_request', 'DescribeRouteTableListRequest'),
        ('modify_route_table_attributes_request',
         'ModifyRouteTableAttributesRequest'),
        ('associate_route_table_request', 'AssociateRouteTableRequest'),
        ('disassociate_route_table_request', 'DisassociateRouteTableRequest'),
        ('tag_for_create_route_table_input', 'TagForCreateRouteTableInput'),
        ('create_route_entry_request', 'CreateRouteEntryRequest'),
        ('delete_route_entry_request', 'DeleteRouteEntryRequest'),
        ('describe_route_entry_list_request', 'DescribeRouteEntryListRequest'),
        ('modify_route_entry_request', 'ModifyRouteEntryRequest'),
    ]
    for snake, cls in request_models:
        mod = types.ModuleType('byteplussdkvpc.models.' + snake)

        class _Req:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
        _Req.__name__ = cls
        setattr(mod, cls, _Req)
        sys.modules['byteplussdkvpc.models.' + snake] = mod


def _load_vpc_common():
    _stub_sdk()
    repo_root = pathlib.Path(__file__).resolve().parents[4]
    module_path = repo_root / 'plugins' / 'module_utils' / 'vpc_common.py'
    spec = importlib.util.spec_from_file_location('vpc_common', module_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vpc = _load_vpc_common()


def _make_client():
    return vpc.VPCClient('AKID', 'SECRET', 'ap-southeast-1')


class TestBuildTags:
    def test_empty(self):
        assert vpc._build_tags(None, vpc.TagForCreateVpcInput) is None
        assert vpc._build_tags([], vpc.TagForCreateVpcInput) is None

    def test_basic(self):
        out = vpc._build_tags(
            [{'key': 'env', 'value': 'prod'}], vpc.TagForCreateVpcInput)
        assert out[0].key == 'env' and out[0].value == 'prod'

    def test_missing_key_rejected(self):
        with pytest.raises(ValueError, match='key is required'):
            vpc._build_tags([{'value': 'prod'}], vpc.TagForCreateVpcInput)

    def test_unknown_field_rejected(self):
        with pytest.raises(ValueError, match='unknown field'):
            vpc._build_tags(
                [{'key': 'env', 'value': 'prod', 'extra': 'x'}],
                vpc.TagForCreateVpcInput)

    def test_non_dict_rejected(self):
        with pytest.raises(ValueError, match='must be a dict'):
            vpc._build_tags(['env=prod'], vpc.TagForCreateVpcInput)


class TestPagination:
    def test_aggregates_vpc_pages(self):
        client = _make_client()
        client.api.describe_vpcs = mock.Mock(side_effect=[
            {'vpcs': [{'vpc_id': 'v-1'}], 'next_token': 'tok'},
            {'vpcs': [{'vpc_id': 'v-2'}], 'next_token': None},
        ])
        result = client.describe_vpcs()
        assert [r['vpc_id'] for r in result] == ['v-1', 'v-2']
        assert client.api.describe_vpcs.call_count == 2

    def test_handles_pascal_case(self):
        client = _make_client()
        client.api.describe_subnets = mock.Mock(return_value={
            'Subnets': [{'SubnetId': 's-1'}],
            'NextToken': None,
        })
        result = client.describe_subnets()
        assert len(result) == 1


class TestFindVpcByName:
    def test_single(self):
        client = _make_client()
        client.describe_vpcs = mock.Mock(
            return_value=[{'vpc_id': 'v-1', 'vpc_name': 'prod-vpc'}])
        assert client.find_vpc_by_name('prod-vpc')['vpc_id'] == 'v-1'

    def test_none(self):
        client = _make_client()
        client.describe_vpcs = mock.Mock(return_value=[])
        assert client.find_vpc_by_name('missing') is None

    def test_multiple_raises_with_project_hint(self):
        client = _make_client()
        client.describe_vpcs = mock.Mock(return_value=[
            {'vpc_id': 'v-1', 'vpc_name': 'prod-vpc'},
            {'vpc_id': 'v-2', 'vpc_name': 'prod-vpc'},
        ])
        with pytest.raises(Exception, match='project_name'):
            client.find_vpc_by_name('prod-vpc')

    def test_project_name_threaded_into_filter(self):
        client = _make_client()
        client.describe_vpcs = mock.Mock(return_value=[
            {'vpc_id': 'v-1', 'vpc_name': 'prod-vpc'},
        ])
        client.find_vpc_by_name('prod-vpc', project_name='prod')
        kwargs = client.describe_vpcs.call_args.kwargs
        assert kwargs.get('project_name') == 'prod'

    def test_prefix_match_excluded(self):
        client = _make_client()
        client.describe_vpcs = mock.Mock(return_value=[
            {'vpc_id': 'v-1', 'vpc_name': 'prod-vpc'},
            {'vpc_id': 'v-2', 'vpc_name': 'prod-vpc-staging'},
        ])
        assert client.find_vpc_by_name('prod-vpc')['vpc_id'] == 'v-1'


class TestFindSubnetByName:
    def test_requires_vpc_id(self):
        client = _make_client()
        with pytest.raises(ValueError, match='vpc_id is required'):
            client.find_subnet_by_name('web-tier', vpc_id=None)

    def test_multi_raises_in_vpc_scope(self):
        client = _make_client()
        client.describe_subnets = mock.Mock(return_value=[
            {'subnet_id': 's-1', 'subnet_name': 'web-tier'},
            {'subnet_id': 's-2', 'subnet_name': 'web-tier'},
        ])
        with pytest.raises(Exception, match='Multiple subnets'):
            client.find_subnet_by_name('web-tier', vpc_id='v-1')


class TestRuleMatches:
    """Regression: rules have no server-side ID, so identity is a tuple."""

    BASE_EXISTING = {
        'direction': 'ingress',
        'protocol': 'tcp',
        'port_start': 443,
        'port_end': 443,
        'cidr_ip': '0.0.0.0/0',
        'source_group_id': '',
        'prefix_list_id': '',
        'policy': 'accept',
        'description': 'Public HTTPS',
        'priority': 1,
    }

    def _candidate(self, **overrides):
        c = {k: v for k, v in self.BASE_EXISTING.items()
             if k != 'direction'}  # candidate doesn't carry direction
        c.update(overrides)
        return c

    def test_exact_identity_match(self):
        assert vpc.rule_matches(self.BASE_EXISTING, self._candidate()) is True

    def test_description_difference_still_matches(self):
        # Description is not part of identity — changing it should still match.
        assert vpc.rule_matches(
            self.BASE_EXISTING, self._candidate(description='Different')) is True

    def test_priority_difference_still_matches(self):
        # Priority is also not part of identity in this matcher; the module
        # detects priority drift separately and triggers revoke+authorize.
        assert vpc.rule_matches(
            self.BASE_EXISTING, self._candidate(priority=99)) is True

    def test_port_change_breaks_match(self):
        assert vpc.rule_matches(
            self.BASE_EXISTING, self._candidate(port_start=8443, port_end=8443)) is False

    def test_protocol_change_breaks_match(self):
        assert vpc.rule_matches(
            self.BASE_EXISTING, self._candidate(protocol='udp')) is False

    def test_cidr_change_breaks_match(self):
        assert vpc.rule_matches(
            self.BASE_EXISTING, self._candidate(cidr_ip='10.0.0.0/16')) is False

    def test_policy_change_breaks_match(self):
        assert vpc.rule_matches(
            self.BASE_EXISTING, self._candidate(policy='drop')) is False

    def test_source_group_target_match(self):
        existing = {
            'protocol': 'tcp', 'port_start': 22, 'port_end': 22,
            'cidr_ip': '', 'source_group_id': 'sg-bastion',
            'prefix_list_id': '', 'policy': 'accept',
        }
        cand = {
            'protocol': 'tcp', 'port_start': 22, 'port_end': 22,
            'source_group_id': 'sg-bastion', 'policy': 'accept',
        }
        assert vpc.rule_matches(existing, cand) is True

    def test_none_vs_empty_string_normalized(self):
        # BytePlus returns "" for unset rule targets in some regions and
        # None in others; both must compare equal to a candidate that omits
        # the field.
        existing = dict(self.BASE_EXISTING)
        existing['source_group_id'] = ''      # API shape A
        assert vpc.rule_matches(existing, self._candidate()) is True
        existing['source_group_id'] = None    # API shape B
        assert vpc.rule_matches(existing, self._candidate()) is True

    def test_pascal_case_keys_supported(self):
        existing_pascal = {
            'Protocol': 'tcp', 'PortStart': 443, 'PortEnd': 443,
            'CidrIp': '0.0.0.0/0', 'Policy': 'accept',
        }
        assert vpc.rule_matches(existing_pascal, self._candidate()) is True


class TestRuleClientMethods:
    def test_authorize_ingress_dispatches(self):
        client = _make_client()
        client.api.authorize_security_group_ingress = mock.Mock(return_value={})
        client.authorize_rule('ingress', 'sg-1', protocol='tcp',
                              port_start=22, port_end=22, cidr_ip='0.0.0.0/0',
                              policy='accept')
        assert client.api.authorize_security_group_ingress.called

    def test_authorize_egress_dispatches(self):
        client = _make_client()
        client.api.authorize_security_group_egress = mock.Mock(return_value={})
        client.authorize_rule('egress', 'sg-1', protocol='all',
                              cidr_ip='0.0.0.0/0', policy='accept')
        assert client.api.authorize_security_group_egress.called

    def test_revoke_strips_client_token(self):
        # Revoke requests don't accept client_token in the SDK; passing it
        # would raise. Helper must strip it silently.
        client = _make_client()
        called = {}

        def capture(req):
            called['fields'] = req.__dict__
            return {}
        client.api.revoke_security_group_ingress = mock.Mock(side_effect=capture)
        client.revoke_rule('ingress', 'sg-1', protocol='tcp',
                           port_start=22, port_end=22, cidr_ip='0.0.0.0/0',
                           policy='accept', client_token='abc')
        assert 'client_token' not in called['fields']

    def test_describe_rules_returns_permissions_list(self):
        client = _make_client()
        client.api.describe_security_group_attributes = mock.Mock(return_value={
            'permissions': [
                {'direction': 'ingress', 'protocol': 'tcp', 'port_start': 22},
            ],
        })
        rules = client.describe_security_group_rules('sg-1')
        assert len(rules) == 1
        assert rules[0]['port_start'] == 22

    def test_invalid_direction_raises(self):
        client = _make_client()
        with pytest.raises(ValueError, match="direction must be"):
            client.authorize_rule('inbound', 'sg-1')
        with pytest.raises(ValueError, match="direction must be"):
            client.revoke_rule('inbound', 'sg-1')
        with pytest.raises(ValueError, match="direction must be"):
            client.modify_rule_description('inbound', 'sg-1')


class TestFindSGByName:
    def test_requires_vpc_id(self):
        client = _make_client()
        with pytest.raises(ValueError, match='vpc_id is required'):
            client.find_security_group_by_name('web', vpc_id=None)

    def test_threads_project_and_filter_keys(self):
        client = _make_client()
        client.describe_security_groups = mock.Mock(return_value=[
            {'security_group_id': 'sg-1', 'security_group_name': 'web'},
        ])
        client.find_security_group_by_name('web', vpc_id='v-1', project_name='prod')
        kwargs = client.describe_security_groups.call_args.kwargs
        assert kwargs['security_group_names'] == ['web']
        assert kwargs['vpc_id'] == 'v-1'
        assert kwargs['project_name'] == 'prod'


class TestBuildEntries:
    def test_basic(self):
        out = vpc._build_entries(
            [{'cidr': '10.0.0.0/16', 'description': 'office'}],
            vpc.PrefixListEntryForCreatePrefixListInput)
        assert out[0].cidr == '10.0.0.0/16'
        assert out[0].description == 'office'

    def test_empty_returns_none(self):
        assert vpc._build_entries(None,
                                  vpc.PrefixListEntryForCreatePrefixListInput) is None
        assert vpc._build_entries([],
                                  vpc.PrefixListEntryForCreatePrefixListInput) is None

    def test_missing_cidr_rejected(self):
        with pytest.raises(ValueError, match='cidr is required'):
            vpc._build_entries(
                [{'description': 'oops'}],
                vpc.PrefixListEntryForCreatePrefixListInput)

    def test_unknown_field_rejected(self):
        # Regression: typos like 'cidr_ip' instead of 'cidr' would silently
        # produce an empty entry. Reject up front.
        with pytest.raises(ValueError, match='unknown field'):
            vpc._build_entries(
                [{'cidr': '10.0.0.0/16', 'cidr_ip': '10.0.0.0/16'}],
                vpc.PrefixListEntryForCreatePrefixListInput)

    def test_non_dict_rejected(self):
        with pytest.raises(ValueError, match='must be a dict'):
            vpc._build_entries(['10.0.0.0/16'],
                               vpc.PrefixListEntryForCreatePrefixListInput)


class TestDiffPrefixListEntries:
    def test_pure_add(self):
        to_add, to_remove, to_update = vpc.diff_prefix_list_entries(
            existing=[],
            desired=[{'cidr': '10.0.0.0/16', 'description': 'office'}],
        )
        assert to_add == [{'cidr': '10.0.0.0/16', 'description': 'office'}]
        assert to_remove == []
        assert to_update == []

    def test_pure_remove_when_purge(self):
        to_add, to_remove, _ = vpc.diff_prefix_list_entries(
            existing=[{'cidr': '10.0.0.0/16'}],
            desired=[],
            purge=True,
        )
        assert to_add == []
        assert to_remove == [{'cidr': '10.0.0.0/16'}]

    def test_no_remove_when_not_purging(self):
        # Default is to not purge — items only present server-side stay.
        _, to_remove, _ = vpc.diff_prefix_list_entries(
            existing=[{'cidr': '10.0.0.0/16'}],
            desired=[],
            purge=False,
        )
        assert to_remove == []

    def test_description_only_change_routes_to_update(self):
        # CIDR matches but description differs: belongs in description-update
        # bucket, not in add or remove. The module bundles it with adds when
        # calling ModifyPrefixList because the API treats re-add as update.
        _, _, to_update = vpc.diff_prefix_list_entries(
            existing=[{'cidr': '10.0.0.0/16', 'description': 'old'}],
            desired=[{'cidr': '10.0.0.0/16', 'description': 'new'}],
        )
        assert to_update == [{'cidr': '10.0.0.0/16', 'description': 'new'}]

    def test_identical_yields_empty(self):
        to_add, to_remove, to_update = vpc.diff_prefix_list_entries(
            existing=[{'cidr': '10.0.0.0/16', 'description': 'x'}],
            desired=[{'cidr': '10.0.0.0/16', 'description': 'x'}],
        )
        assert to_add == [] and to_remove == [] and to_update == []

    def test_mixed_add_remove_update(self):
        existing = [
            {'cidr': '10.0.0.0/16', 'description': 'keep'},          # untouched
            {'cidr': '10.1.0.0/16', 'description': 'old-desc'},       # update
            {'cidr': '10.2.0.0/16'},                                  # purge
        ]
        desired = [
            {'cidr': '10.0.0.0/16', 'description': 'keep'},
            {'cidr': '10.1.0.0/16', 'description': 'new-desc'},
            {'cidr': '10.3.0.0/16', 'description': 'office'},         # new
        ]
        to_add, to_remove, to_update = vpc.diff_prefix_list_entries(
            existing, desired, purge=True)
        assert to_add == [{'cidr': '10.3.0.0/16', 'description': 'office'}]
        assert to_remove == [{'cidr': '10.2.0.0/16'}]
        assert to_update == [{'cidr': '10.1.0.0/16', 'description': 'new-desc'}]

    def test_handles_pascal_case_keys(self):
        # DescribePrefixListEntries may return PascalCase; differ must accept it.
        to_add, _, _ = vpc.diff_prefix_list_entries(
            existing=[{'Cidr': '10.0.0.0/16', 'Description': 'x'}],
            desired=[{'cidr': '10.0.0.0/16', 'description': 'x'},
                     {'cidr': '10.1.0.0/16'}],
        )
        # Only the second entry is new.
        assert to_add == [{'cidr': '10.1.0.0/16'}]


class TestPrefixListLookup:
    def test_single_match_returns(self):
        client = _make_client()
        client.describe_prefix_lists = mock.Mock(return_value=[
            {'prefix_list_id': 'pl-1', 'prefix_list_name': 'office-egress'},
        ])
        assert client.find_prefix_list_by_name(
            'office-egress')['prefix_list_id'] == 'pl-1'

    def test_multi_raises(self):
        client = _make_client()
        client.describe_prefix_lists = mock.Mock(return_value=[
            {'prefix_list_id': 'pl-1', 'prefix_list_name': 'office-egress'},
            {'prefix_list_id': 'pl-2', 'prefix_list_name': 'office-egress'},
        ])
        with pytest.raises(Exception, match='Multiple prefix lists'):
            client.find_prefix_list_by_name('office-egress')

    def test_project_threaded(self):
        client = _make_client()
        client.describe_prefix_lists = mock.Mock(return_value=[
            {'prefix_list_id': 'pl-1', 'prefix_list_name': 'office-egress'},
        ])
        client.find_prefix_list_by_name('office-egress', project_name='prod')
        kwargs = client.describe_prefix_lists.call_args.kwargs
        assert kwargs.get('project_name') == 'prod'

    def test_prefix_match_excluded(self):
        # Server may match prefix; helper must filter to exact name match only.
        client = _make_client()
        client.describe_prefix_lists = mock.Mock(return_value=[
            {'prefix_list_id': 'pl-1', 'prefix_list_name': 'office-egress'},
            {'prefix_list_id': 'pl-2', 'prefix_list_name': 'office-egress-v2'},
        ])
        assert client.find_prefix_list_by_name(
            'office-egress')['prefix_list_id'] == 'pl-1'


class TestModifyPrefixList:
    def test_remove_entries_strips_description(self):
        # The Remove input model only accepts `cidr` — descriptions sneaked
        # in must be filtered, otherwise SDK construction would fail.
        client = _make_client()
        captured = {}

        def capture(req):
            captured['fields'] = req.__dict__
            return {}
        client.api.modify_prefix_list = mock.Mock(side_effect=capture)
        client.modify_prefix_list(
            'pl-1',
            remove_entries=[{'cidr': '10.0.0.0/16', 'description': 'leak'}])
        removes = captured['fields']['remove_prefix_list_entries']
        assert len(removes) == 1
        # The stubbed model just stashes kwargs on __dict__; verify cidr is
        # set and description didn't make it through.
        assert removes[0].__dict__ == {'cidr': '10.0.0.0/16'}

    def test_no_diff_skips_api_call(self):
        # modify_prefix_list with no add/remove/attrs is a no-op API call —
        # but the wrapper always invokes the SDK (the API itself decides what
        # to do). This test documents that behavior so future readers know
        # the contract.
        client = _make_client()
        client.api.modify_prefix_list = mock.Mock(return_value={})
        client.modify_prefix_list('pl-1')
        assert client.api.modify_prefix_list.called


class TestDiffRouteTableAssociations:
    def test_empty_inputs(self):
        assert vpc.diff_route_table_associations([], []) == ([], [])

    def test_only_add(self):
        add, remove = vpc.diff_route_table_associations([], ['s-1', 's-2'])
        assert add == ['s-1', 's-2']
        assert remove == []

    def test_only_remove(self):
        add, remove = vpc.diff_route_table_associations(['s-1', 's-2'], [])
        assert add == []
        assert remove == ['s-1', 's-2']

    def test_overlap(self):
        add, remove = vpc.diff_route_table_associations(
            ['s-1', 's-2'], ['s-2', 's-3'])
        assert add == ['s-3']
        assert remove == ['s-1']

    def test_set_semantics_no_order_dependence(self):
        # The function should treat inputs as sets, not ordered sequences.
        add_a, rem_a = vpc.diff_route_table_associations(
            ['s-1', 's-2'], ['s-1', 's-2'])
        add_b, rem_b = vpc.diff_route_table_associations(
            ['s-2', 's-1'], ['s-1', 's-2'])
        assert (add_a, rem_a) == (add_b, rem_b) == ([], [])

    def test_none_inputs_treated_as_empty(self):
        # Callers may pass None when the field is absent from the API response.
        assert vpc.diff_route_table_associations(None, None) == ([], [])
        assert vpc.diff_route_table_associations(None, ['s-1']) == (['s-1'], [])


class TestIsSystemRouteTable:
    def test_system_snake_case(self):
        assert vpc.is_system_route_table({'route_table_type': 'System'}) is True

    def test_system_pascal_case(self):
        assert vpc.is_system_route_table({'RouteTableType': 'System'}) is True

    def test_custom(self):
        assert vpc.is_system_route_table({'route_table_type': 'Custom'}) is False

    def test_missing_field(self):
        # Defensive: a record without the type field shouldn't be treated as
        # System (failing open would refuse to manage legitimate custom tables).
        assert vpc.is_system_route_table({}) is False


class TestFindRouteEntryMatch:
    def test_match_snake_case(self):
        entries = [
            {'destination_cidr_block': '10.0.0.0/16', 'route_entry_id': 're-1'},
            {'destination_cidr_block': '0.0.0.0/0', 'route_entry_id': 're-2'},
        ]
        assert vpc.find_route_entry_match(
            entries, '0.0.0.0/0')['route_entry_id'] == 're-2'

    def test_match_pascal_case(self):
        entries = [{'DestinationCidrBlock': '10.0.0.0/16', 'RouteEntryId': 're-1'}]
        assert vpc.find_route_entry_match(
            entries, '10.0.0.0/16')['RouteEntryId'] == 're-1'

    def test_no_match(self):
        assert vpc.find_route_entry_match([{'destination_cidr_block': '10/8'}],
                                          '0.0.0.0/0') is None

    def test_empty_or_none(self):
        assert vpc.find_route_entry_match([], '0.0.0.0/0') is None
        assert vpc.find_route_entry_match(None, '0.0.0.0/0') is None


class TestNextHopTypeMap:
    def test_round_trip(self):
        for snake, pascal in vpc.NEXT_HOP_TYPE_MAP.items():
            assert vpc.NEXT_HOP_TYPE_REVERSE[pascal] == snake

    def test_all_lowercase_snake(self):
        # Keys are user-facing — guarantee they're snake_case so playbook
        # authors don't have to remember mixed-case keys.
        for k in vpc.NEXT_HOP_TYPE_MAP:
            assert k == k.lower()
            assert ' ' not in k


class TestFindRouteTableByName:
    def test_requires_vpc_id(self):
        client = _make_client()
        with pytest.raises(ValueError, match='vpc_id is required'):
            client.find_route_table_by_name('app', vpc_id=None)

    def test_single_match(self):
        client = _make_client()
        client.describe_route_tables = mock.Mock(return_value=[
            {'route_table_id': 'vtb-1', 'route_table_name': 'app'},
        ])
        r = client.find_route_table_by_name('app', vpc_id='v-1')
        assert r['route_table_id'] == 'vtb-1'

    def test_multiple_raises(self):
        client = _make_client()
        client.describe_route_tables = mock.Mock(return_value=[
            {'route_table_id': 'vtb-1', 'route_table_name': 'app'},
            {'route_table_id': 'vtb-2', 'route_table_name': 'app'},
        ])
        with pytest.raises(Exception, match='Multiple route tables'):
            client.find_route_table_by_name('app', vpc_id='v-1')

    def test_prefix_excluded(self):
        # describe_route_tables filters by prefix in some regions; final pass
        # must enforce exact match.
        client = _make_client()
        client.describe_route_tables = mock.Mock(return_value=[
            {'route_table_id': 'vtb-1', 'route_table_name': 'app'},
            {'route_table_id': 'vtb-2', 'route_table_name': 'app-staging'},
        ])
        assert client.find_route_table_by_name(
            'app', vpc_id='v-1')['route_table_id'] == 'vtb-1'


class TestRouteTableApiPassthrough:
    def test_create_threads_tags(self):
        client = _make_client()
        captured = {}

        def capture(req):
            captured['fields'] = req.__dict__
            return {'route_table_id': 'vtb-1'}
        client.api.create_route_table = mock.Mock(side_effect=capture)
        client.create_route_table(
            vpc_id='v-1', route_table_name='app',
            tags=[{'key': 'env', 'value': 'prod'}])
        # Tags should have been wrapped into TagForCreateRouteTableInput.
        assert len(captured['fields']['tags']) == 1
        assert captured['fields']['tags'][0].key == 'env'

    def test_associate_threads_subnet(self):
        client = _make_client()
        captured = {}

        def capture(req):
            captured['fields'] = req.__dict__
            return {}
        client.api.associate_route_table = mock.Mock(side_effect=capture)
        client.associate_route_table('vtb-1', 's-1')
        assert captured['fields']['route_table_id'] == 'vtb-1'
        assert captured['fields']['subnet_id'] == 's-1'


class TestRouteEntryApiPassthrough:
    def test_modify_includes_route_entry_id(self):
        client = _make_client()
        captured = {}

        def capture(req):
            captured['fields'] = req.__dict__
            return {}
        client.api.modify_route_entry = mock.Mock(side_effect=capture)
        client.modify_route_entry('re-1', next_hop_type='NatGW',
                                  next_hop_id='ngw-1')
        assert captured['fields']['route_entry_id'] == 're-1'
        assert captured['fields']['next_hop_type'] == 'NatGW'


class TestAssociatedSubnetIds:
    def test_snake_list(self):
        assert vpc.associated_subnet_ids(
            {'subnet_ids': ['s-1', 's-2']}) == ['s-1', 's-2']

    def test_pascal_list(self):
        assert vpc.associated_subnet_ids({'SubnetIds': ['s-1']}) == ['s-1']

    def test_string_fallback(self):
        # Some regions report a single bound subnet as a scalar — accept it.
        assert vpc.associated_subnet_ids({'subnet_id': 's-1'}) == ['s-1']

    def test_empty_string_means_empty(self):
        assert vpc.associated_subnet_ids({'subnet_id': ''}) == []

    def test_missing(self):
        assert vpc.associated_subnet_ids({}) == []
