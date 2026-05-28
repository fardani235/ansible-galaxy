# -*- coding: utf-8 -*-
# Tests for IAMClient orchestration logic in iam_common.py:
# - canonicalize_policy_document (parse-then-key-sort, used by
#   byteplus_iam_policy and byteplus_iam_role for drift detection)
# - error-family classification (NotFound vs AlreadyExists vs other)
# - paginator (Limit/Offset walk until IsTruncated=False)
# - get_*-returns-None-on-NotFound contract
#
# The SDK is fully stubbed; only the wrapper logic is exercised. Mirrors
# the test_snapshot_common.py pattern.

import importlib.util
import json
import pathlib
import sys
import types
from unittest import mock

import pytest


def _stub_core_sdk():
    """Stub byteplussdkcore.* so iam_common can import UniversalApi
    without the real SDK installed."""
    bp_core = types.ModuleType('byteplussdkcore')
    sys.modules.setdefault('byteplussdkcore', bp_core)

    config_mod = types.ModuleType('byteplussdkcore.configuration')

    class _Config:
        _default = None

        def __init__(self):
            self.ak = self.sk = self.region = None
            self.session_token = None
            self.host = None

        @classmethod
        def set_default(cls, cfg):
            cls._default = cfg
    config_mod.Configuration = _Config
    sys.modules['byteplussdkcore.configuration'] = config_mod

    universal_mod = types.ModuleType('byteplussdkcore.universal')

    class _UniversalApi:
        def __init__(self):
            self.calls = []

        def do_call(self, info, params):
            # Default stub — tests override on the instance.
            self.calls.append((info, params))
            return {}

    class _UniversalInfo:
        def __init__(self, method=None, service=None, version=None,
                     action=None, content_type=None):
            self.method = method
            self.service = service
            self.version = version
            self.action = action
            self.content_type = content_type
    universal_mod.UniversalApi = _UniversalApi
    universal_mod.UniversalInfo = _UniversalInfo
    sys.modules['byteplussdkcore.universal'] = universal_mod

    rest_mod = types.ModuleType('byteplussdkcore.rest')

    class _ApiException(Exception):
        def __init__(self, status=0, reason='', body=None):
            self.status = status
            self.reason = reason
            self.body = body
    rest_mod.ApiException = _ApiException
    sys.modules['byteplussdkcore.rest'] = rest_mod


def _load_iam_common():
    _stub_core_sdk()
    repo_root = pathlib.Path(__file__).resolve().parents[4]
    path = repo_root / 'plugins' / 'module_utils' / 'iam_common.py'
    spec = importlib.util.spec_from_file_location('iam_common', path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


iam = _load_iam_common()


# ---------- canonicalize_policy_document ----------


class TestCanonicalizePolicyDocument:
    def test_dict_input_is_serialized_with_sorted_keys(self):
        # Out-of-order keys must serialize identically to in-order keys —
        # this is the whole point of canonicalization.
        a = iam.canonicalize_policy_document(
            {'Version': '1', 'Statement': [{'Effect': 'Allow'}]})
        b = iam.canonicalize_policy_document(
            {'Statement': [{'Effect': 'Allow'}], 'Version': '1'})
        assert a == b

    def test_string_input_is_parsed_then_canonicalized(self):
        # The module accepts either a dict (Ansible YAML round-tripped)
        # or a string (caller passed raw JSON). Both must produce the
        # same canonical form.
        as_dict = {'Version': '1', 'Statement': [{'Effect': 'Allow'}]}
        as_str = json.dumps(as_dict)
        assert (iam.canonicalize_policy_document(as_dict)
                == iam.canonicalize_policy_document(as_str))

    def test_nested_keys_are_sorted(self):
        # Sorting must recurse — server may reorder nested object keys
        # on the round trip too.
        a = iam.canonicalize_policy_document(
            {'Statement': [{'Effect': 'Allow', 'Action': 'iam:*'}]})
        b = iam.canonicalize_policy_document(
            {'Statement': [{'Action': 'iam:*', 'Effect': 'Allow'}]})
        assert a == b

    def test_invalid_json_string_raises_valueerror(self):
        # Modules surface this as fail_json — must be a clean ValueError
        # so we don't leak json.decoder.JSONDecodeError internals.
        with pytest.raises(ValueError, match='not valid JSON'):
            iam.canonicalize_policy_document('not-json{{{')

    def test_non_dict_non_string_raises_typeerror(self):
        with pytest.raises(TypeError, match='dict or JSON string'):
            iam.canonicalize_policy_document(['not', 'a', 'dict'])

    def test_returns_string(self):
        # We compare canonical forms with ==, so a string return is the
        # cleanest contract. (A dict would also work but a string is
        # also what callers can log/diff.)
        out = iam.canonicalize_policy_document({'a': 1})
        assert isinstance(out, str)


# ---------- error classification ----------


def _make_client(**overrides):
    """Build an IAMClient with stubbed credentials. Tests override
    .api.do_call to control responses."""
    return iam.IAMClient(
        access_key=overrides.get('access_key', 'AKID'),
        secret_key=overrides.get('secret_key', 'SECRET'),
        region=overrides.get('region', 'ap-southeast-1'),
    )


def _api_error(action, code, message='boom', request_id='req-XYZ'):
    """Build a do_call return that simulates a BytePlus error envelope.

    The real envelope is {'ResponseMetadata': {'Error': {...},
    'RequestId': '...'}}. UniversalApi returns this verbatim as a dict
    on error — it does NOT raise. iam_common must inspect the envelope
    and raise the right error class.
    """
    return {
        'ResponseMetadata': {
            'RequestId': request_id,
            'Action': action,
            'Error': {'Code': code, 'Message': message},
        },
    }


class TestErrorClassification:
    def test_entity_does_not_exist_get_returns_none(self):
        # `get_*` family must convert NotFound to None — every module's
        # idempotency check starts "does this exist?" and a None-vs-dict
        # call site is cleaner than wrapping every get in try/except.
        client = _make_client()
        client.api.do_call = mock.Mock(
            return_value=_api_error('GetUser', 'EntityDoesNotExist.User'))
        assert client.get_user('alice') is None

    def test_entity_does_not_exist_non_get_raises_notfound(self):
        # On a write verb (e.g. UpdateUser), NotFound is a real error
        # condition, not "no result" — raise so the module can surface it.
        client = _make_client()
        client.api.do_call = mock.Mock(
            return_value=_api_error('UpdateUser', 'EntityDoesNotExist.User'))
        with pytest.raises(iam.IAMNotFound):
            client.update_user('alice', display_name='Alice')

    def test_entity_already_exists_raises_alreadyexists(self):
        client = _make_client()
        client.api.do_call = mock.Mock(
            return_value=_api_error('CreateUser', 'EntityAlreadyExists.User'))
        with pytest.raises(iam.IAMAlreadyExists):
            client.create_user('alice')

    def test_other_error_raises_iamclienterror(self):
        client = _make_client()
        client.api.do_call = mock.Mock(
            return_value=_api_error(
                'CreateUser', 'InvalidParameter.UserName', 'bad name'))
        with pytest.raises(iam.IAMClientError) as exc_info:
            client.create_user('!!bad!!')
        # Request ID must be in the message so an operator can hand it
        # to BytePlus support without re-running with -vvv.
        assert 'req-XYZ' in str(exc_info.value)
        assert 'bad name' in str(exc_info.value)
        assert 'CreateUser' in str(exc_info.value)


# ---------- paginator ----------


def _success(action, payload, request_id='req-OK'):
    """Build a do_call return that simulates a successful BytePlus
    response envelope. Result is the unwrapped payload."""
    return {
        'ResponseMetadata': {'RequestId': request_id, 'Action': action},
        'Result': payload,
    }


class TestPaginator:
    def test_single_page_returns_results(self):
        # IsTruncated=false on the first call → one page, done.
        client = _make_client()
        client.api.do_call = mock.Mock(return_value=_success(
            'ListUsers',
            {'UserMetadata': [{'UserName': 'alice'}, {'UserName': 'bob'}],
             'IsTruncated': False}))
        result = list(client.list_users())
        assert [u['UserName'] for u in result] == ['alice', 'bob']
        assert client.api.do_call.call_count == 1

    def test_pagination_walks_offset_until_not_truncated(self):
        # IsTruncated=true → bump Offset, walk again.
        client = _make_client()
        client.api.do_call = mock.Mock(side_effect=[
            _success('ListUsers',
                     {'UserMetadata': [{'UserName': 'alice'}],
                      'IsTruncated': True, 'Marker': 1}),
            _success('ListUsers',
                     {'UserMetadata': [{'UserName': 'bob'}],
                      'IsTruncated': False}),
        ])
        result = list(client.list_users())
        assert [u['UserName'] for u in result] == ['alice', 'bob']
        assert client.api.do_call.call_count == 2
        # First call: no Offset. Second call: Offset=1 (the Marker
        # returned from the previous page).
        first_params = client.api.do_call.call_args_list[0].args[1]
        second_params = client.api.do_call.call_args_list[1].args[1]
        assert 'Offset' not in first_params
        assert second_params.get('Offset') == 1

    def test_empty_response_terminates(self):
        # No UserMetadata key at all — must terminate, not crash.
        client = _make_client()
        client.api.do_call = mock.Mock(
            return_value=_success('ListUsers', {'IsTruncated': False}))
        assert list(client.list_users()) == []
