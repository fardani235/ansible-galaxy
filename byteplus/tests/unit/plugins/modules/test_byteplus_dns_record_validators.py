# -*- coding: utf-8 -*-
# Regression tests for the validator helpers in byteplus_dns_record.
#
# These tests target pure functions and do NOT import AnsibleModule, so they
# run under plain pytest without the ansible-test harness.

import importlib.util
import pathlib
import sys

import pytest


def _load_module():
    repo_root = pathlib.Path(__file__).resolve().parents[4]
    module_path = repo_root / 'plugins' / 'modules' / 'byteplus_dns_record.py'
    spec = importlib.util.spec_from_file_location('byteplus_dns_record', module_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # The module imports AnsibleModule at top level; stub it just enough to
    # let the file execute. We only need the validators.
    sys.modules.setdefault('ansible', type(sys)('ansible'))
    sys.modules.setdefault('ansible.module_utils', type(sys)('ansible.module_utils'))
    basic = type(sys)('ansible.module_utils.basic')
    basic.AnsibleModule = object
    basic.env_fallback = lambda *_a, **_kw: None
    sys.modules['ansible.module_utils.basic'] = basic
    sys.modules.setdefault(
        'ansible_collections', type(sys)('ansible_collections'))
    sys.modules.setdefault(
        'ansible_collections.byteplus',
        type(sys)('ansible_collections.byteplus'))
    sys.modules.setdefault(
        'ansible_collections.byteplus.cloud',
        type(sys)('ansible_collections.byteplus.cloud'))
    sys.modules.setdefault(
        'ansible_collections.byteplus.cloud.plugins',
        type(sys)('ansible_collections.byteplus.cloud.plugins'))
    sys.modules.setdefault(
        'ansible_collections.byteplus.cloud.plugins.module_utils',
        type(sys)('ansible_collections.byteplus.cloud.plugins.module_utils'))
    bp_common = type(sys)(
        'ansible_collections.byteplus.cloud.plugins.module_utils.byteplus_common')
    bp_common.BytePlusClient = object
    sys.modules[
        'ansible_collections.byteplus.cloud.plugins.module_utils.byteplus_common'
    ] = bp_common
    spec.loader.exec_module(mod)
    return mod


dns = _load_module()


class TestCNAMEValidator:
    """Regression for the silent-pass bug: CNAME -> IP must raise."""

    def test_cname_rejects_ipv4(self):
        with pytest.raises(ValueError, match='must be a domain name'):
            dns._validate_record_value('CNAME', '203.0.113.5')

    def test_cname_rejects_ipv6(self):
        with pytest.raises(ValueError, match='must be a domain name'):
            dns._validate_record_value('CNAME', '2001:db8::1')

    def test_cname_accepts_domain(self):
        dns._validate_record_value('CNAME', 'target.example.com')

    def test_cname_rejects_garbage(self):
        with pytest.raises(ValueError):
            dns._validate_record_value('CNAME', 'not a domain')


class TestARecordValidator:
    def test_a_accepts_ipv4(self):
        dns._validate_record_value('A', '203.0.113.1')

    def test_a_rejects_ipv6(self):
        with pytest.raises(ValueError):
            dns._validate_record_value('A', '2001:db8::1')

    def test_aaaa_accepts_ipv6(self):
        dns._validate_record_value('AAAA', '2001:db8::1')

    def test_aaaa_rejects_ipv4(self):
        with pytest.raises(ValueError):
            dns._validate_record_value('AAAA', '203.0.113.1')


class TestHostValidator:
    def test_root_at_ok(self):
        dns._validate_host('@')

    def test_simple_label_ok(self):
        dns._validate_host('www')

    def test_dotted_subdomain_ok(self):
        dns._validate_host('api.staging')

    def test_empty_fails(self):
        with pytest.raises(ValueError):
            dns._validate_host('')

    def test_underscore_fails(self):
        with pytest.raises(ValueError):
            dns._validate_host('foo_bar')


class TestIsIPLiteral:
    def test_ipv4(self):
        assert dns._is_ip_literal('203.0.113.1') is True

    def test_ipv6(self):
        assert dns._is_ip_literal('2001:db8::1') is True

    def test_domain(self):
        assert dns._is_ip_literal('example.com') is False
