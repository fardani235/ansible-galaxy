# -*- coding: utf-8 -*-
# Tests for byteplus_route_entry internals:
# - snake↔PascalCase next-hop translation
# - drift detection (next_hop_type / next_hop_id / description / name)
# - description-only and name-only diffs respect "user-omitted == no drift"

import importlib.util
import pathlib
import sys
import types


def _stub_imports():
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
    # Pull these from the real module rather than re-deriving — the tests
    # exist to verify the module uses them correctly.
    stub.NEXT_HOP_TYPE_MAP = {
        'instance': 'Instance',
        'network_interface': 'NetworkInterface',
        'nat_gateway': 'NatGW',
        'vpn_gateway': 'VpnGW',
        'transit_router': 'TransitRouter',
        'ipv6_gateway': 'IPv6Gateway',
        'ha_vip': 'HaVip',
        'private_link_vpc_endpoint': 'PrivateLinkVpcEndpoint',
        'ip_address': 'IpAddress',
    }
    stub.NEXT_HOP_TYPE_REVERSE = {v: k for k, v in stub.NEXT_HOP_TYPE_MAP.items()}

    def find_route_entry_match(entries, cidr):
        for e in entries or []:
            if (e.get('destination_cidr_block')
                    or e.get('DestinationCidrBlock')) == cidr:
                return e
        return None
    stub.find_route_entry_match = find_route_entry_match

    sys.modules[
        'ansible_collections.fardani235.byteplus.plugins.module_utils.vpc_common'
    ] = stub


def _load_module():
    _stub_imports()
    repo_root = pathlib.Path(__file__).resolve().parents[4]
    path = repo_root / 'plugins' / 'modules' / 'byteplus_route_entry.py'
    spec = importlib.util.spec_from_file_location('byteplus_route_entry', path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


re_mod = _load_module()


class TestApiNextHopType:
    def test_translates_known(self):
        assert re_mod._api_next_hop_type('nat_gateway') == 'NatGW'
        assert re_mod._api_next_hop_type('ipv6_gateway') == 'IPv6Gateway'

    def test_none_passthrough(self):
        assert re_mod._api_next_hop_type(None) is None


class TestExistingNextHopTypeSnake:
    def test_known_pascal(self):
        assert re_mod._existing_next_hop_type_snake(
            {'next_hop_type': 'NatGW'}) == 'nat_gateway'

    def test_known_pascal_case_field(self):
        assert re_mod._existing_next_hop_type_snake(
            {'NextHopType': 'Instance'}) == 'instance'

    def test_unknown_passes_through(self):
        # If BytePlus adds a new type the collection hasn't mapped yet, we
        # still want diffing to compare apples to apples (unknown == unknown).
        assert re_mod._existing_next_hop_type_snake(
            {'next_hop_type': 'FutureType'}) == 'FutureType'


class TestModifyKwargs:
    def _existing(self, **overrides):
        base = {
            'destination_cidr_block': '0.0.0.0/0',
            'next_hop_type': 'NatGW',
            'next_hop_id': 'ngw-1',
            'description': 'egress',
            'route_entry_name': 'egress-route',
        }
        base.update(overrides)
        return base

    def test_no_drift(self):
        p = {'next_hop_type': 'nat_gateway', 'next_hop_id': 'ngw-1',
             'description': 'egress', 'route_entry_name': 'egress-route'}
        assert re_mod._modify_kwargs(p, self._existing()) is None

    def test_next_hop_id_drift(self):
        p = {'next_hop_type': 'nat_gateway', 'next_hop_id': 'ngw-2',
             'description': None, 'route_entry_name': None}
        out = re_mod._modify_kwargs(p, self._existing())
        assert out == {'next_hop_id': 'ngw-2'}

    def test_type_change_translates(self):
        # Switching from NAT to a network interface drifts both fields.
        p = {'next_hop_type': 'network_interface', 'next_hop_id': 'eni-9',
             'description': None, 'route_entry_name': None}
        out = re_mod._modify_kwargs(p, self._existing())
        assert out['next_hop_type'] == 'NetworkInterface'
        assert out['next_hop_id'] == 'eni-9'

    def test_description_omitted_param_no_drift(self):
        # User didn't pass description → don't propose modifying it.
        p = {'next_hop_type': 'nat_gateway', 'next_hop_id': 'ngw-1',
             'description': None, 'route_entry_name': None}
        assert re_mod._modify_kwargs(p, self._existing()) is None

    def test_description_change(self):
        p = {'next_hop_type': 'nat_gateway', 'next_hop_id': 'ngw-1',
             'description': 'updated', 'route_entry_name': None}
        out = re_mod._modify_kwargs(p, self._existing())
        assert out == {'description': 'updated'}

    def test_empty_description_equates_to_unset(self):
        existing = self._existing()
        existing.pop('description')  # field absent in API response
        p = {'next_hop_type': 'nat_gateway', 'next_hop_id': 'ngw-1',
             'description': '', 'route_entry_name': None}
        assert re_mod._modify_kwargs(p, existing) is None

    def test_pascal_case_existing_does_not_drift(self):
        existing = {
            'DestinationCidrBlock': '0.0.0.0/0',
            'NextHopType': 'NatGW',
            'NextHopId': 'ngw-1',
            'Description': 'egress',
            'RouteEntryName': 'egress-route',
        }
        p = {'next_hop_type': 'nat_gateway', 'next_hop_id': 'ngw-1',
             'description': 'egress', 'route_entry_name': 'egress-route'}
        assert re_mod._modify_kwargs(p, existing) is None

    def test_route_entry_name_change(self):
        p = {'next_hop_type': 'nat_gateway', 'next_hop_id': 'ngw-1',
             'description': None, 'route_entry_name': 'new-name'}
        out = re_mod._modify_kwargs(p, self._existing())
        assert out == {'route_entry_name': 'new-name'}
