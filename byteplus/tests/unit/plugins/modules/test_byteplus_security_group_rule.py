# -*- coding: utf-8 -*-
# Tests for pure helpers in byteplus_security_group_rule.
# Covers target/port validation, description-only diff, priority drift,
# and the rule-dict builder that filters None-valued kwargs.

import importlib.util
import pathlib
import sys
import types


def _stub_imports():
    """Stub Ansible + vpc_common imports the module loads at top level."""
    ansible = types.ModuleType('ansible')
    sys.modules.setdefault('ansible', ansible)
    sys.modules.setdefault('ansible.module_utils',
                           types.ModuleType('ansible.module_utils'))
    basic = types.ModuleType('ansible.module_utils.basic')
    basic.AnsibleModule = object
    basic.env_fallback = lambda *_a, **_kw: None
    sys.modules['ansible.module_utils.basic'] = basic

    for name in [
        'ansible_collections',
        'ansible_collections.byteplus',
        'ansible_collections.fardani235.byteplus',
        'ansible_collections.fardani235.byteplus.plugins',
        'ansible_collections.fardani235.byteplus.plugins.module_utils',
    ]:
        sys.modules.setdefault(name, types.ModuleType(name))

    vpc_common_stub = types.ModuleType(
        'ansible_collections.fardani235.byteplus.plugins.module_utils.vpc_common')

    class _Client:
        def __init__(self, *_a, **_kw):
            pass

    vpc_common_stub.VPCClient = _Client
    vpc_common_stub.rule_matches = lambda existing, cand: False
    vpc_common_stub.resolve_credentials = lambda module: (
        'AK', 'SK', 'ap-southeast-1', None)
    sys.modules[
        'ansible_collections.fardani235.byteplus.plugins.module_utils.vpc_common'
    ] = vpc_common_stub


def _load_module():
    _stub_imports()
    repo_root = pathlib.Path(__file__).resolve().parents[4]
    module_path = repo_root / 'plugins' / 'modules' / 'byteplus_security_group_rule.py'
    spec = importlib.util.spec_from_file_location(
        'byteplus_security_group_rule', module_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sgr = _load_module()


class _FakeModule:
    """Stand-in for AnsibleModule that records fail_json calls instead of exiting."""

    def __init__(self):
        self.failures = []

    def fail_json(self, msg, **kwargs):
        self.failures.append(msg)
        # IMPORTANT: don't raise here. Real AnsibleModule.fail_json calls
        # sys.exit; the module under test treats fail_json as terminal but
        # we want validation tests to inspect the failure list directly.


class TestValidateTarget:
    def test_exactly_one_required(self):
        m = _FakeModule()
        sgr._validate_target({}, m)
        assert any('Exactly one' in f for f in m.failures)

    def test_cidr_ok(self):
        m = _FakeModule()
        sgr._validate_target({'cidr_ip': '0.0.0.0/0'}, m)
        assert m.failures == []

    def test_source_group_ok(self):
        m = _FakeModule()
        sgr._validate_target({'source_group_id': 'sg-1'}, m)
        assert m.failures == []

    def test_mutually_exclusive(self):
        m = _FakeModule()
        sgr._validate_target(
            {'cidr_ip': '0.0.0.0/0', 'source_group_id': 'sg-1'}, m)
        assert any('mutually exclusive' in f for f in m.failures)


class TestValidatePorts:
    def test_tcp_requires_ports(self):
        m = _FakeModule()
        sgr._validate_ports({'protocol': 'tcp'}, m)
        assert any('port_start and port_end are required' in f for f in m.failures)

    def test_tcp_with_ports_ok(self):
        m = _FakeModule()
        sgr._validate_ports(
            {'protocol': 'tcp', 'port_start': 80, 'port_end': 80}, m)
        assert m.failures == []

    def test_inverted_range_rejected(self):
        m = _FakeModule()
        sgr._validate_ports(
            {'protocol': 'tcp', 'port_start': 100, 'port_end': 50}, m)
        assert any('cannot exceed' in f for f in m.failures)

    def test_icmp_does_not_require_ports(self):
        m = _FakeModule()
        sgr._validate_ports({'protocol': 'icmp'}, m)
        assert m.failures == []

    def test_all_does_not_require_ports(self):
        m = _FakeModule()
        sgr._validate_ports({'protocol': 'all'}, m)
        assert m.failures == []


class TestBuildRuleDict:
    def test_drops_none(self):
        p = {'protocol': 'tcp', 'port_start': 22, 'port_end': 22,
             'cidr_ip': '0.0.0.0/0', 'policy': 'accept',
             'source_group_id': None, 'prefix_list_id': None,
             'priority': None, 'description': None}
        out = sgr._build_rule_dict(p)
        assert 'source_group_id' not in out
        assert 'priority' not in out
        assert out['port_start'] == 22

    def test_include_description_toggle(self):
        p = {'protocol': 'tcp', 'description': 'hi', 'port_start': 22, 'port_end': 22}
        with_desc = sgr._build_rule_dict(p, include_description=True)
        without = sgr._build_rule_dict(p, include_description=False)
        assert with_desc.get('description') == 'hi'
        assert 'description' not in without


class TestDescriptionOnlyDiff:
    def test_no_diff_when_description_omitted(self):
        # description is None on the candidate (user didn't set it) — must
        # not be treated as a change just because the API returns a string.
        assert sgr._description_only_diff(
            {'description': 'existing'}, {}) is False

    def test_diff_detected(self):
        assert sgr._description_only_diff(
            {'description': 'old'}, {'description': 'new'}) is True

    def test_no_diff_when_equal(self):
        assert sgr._description_only_diff(
            {'description': 'same'}, {'description': 'same'}) is False

    def test_handles_missing_existing_as_empty(self):
        # Existing rule has no description field → treat as empty.
        assert sgr._description_only_diff({}, {'description': 'new'}) is True
        assert sgr._description_only_diff({}, {'description': ''}) is False


class TestPriorityDrifted:
    def test_unset_candidate_no_drift(self):
        assert sgr._priority_drifted({'priority': 5}, {}) is False

    def test_drift_detected(self):
        assert sgr._priority_drifted(
            {'priority': 5}, {'priority': 1}) is True

    def test_same_no_drift(self):
        assert sgr._priority_drifted(
            {'priority': 5}, {'priority': 5}) is False
