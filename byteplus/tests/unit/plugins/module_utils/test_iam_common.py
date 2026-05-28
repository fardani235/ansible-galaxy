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
    """Build a do_call return that simulates a BytePlus error envelope
    surfaced INLINE on a 200-OK response.

    Some BytePlus services do this — the HTTP status is 200 but
    ResponseMetadata.Error is populated. iam_common must inspect the
    envelope and raise the right error class.
    """
    return {
        'ResponseMetadata': {
            'RequestId': request_id,
            'Action': action,
            'Error': {'Code': code, 'Message': message},
        },
    }


def _api_exception(code, message='boom', request_id='req-XYZ', status=400):
    """Build the ApiException UniversalApi actually raises on HTTP
    non-2xx — which is the path the BytePlus IAM endpoint takes in
    practice (smoke_iam.yml proved this empirically).

    The body is a JSON string carrying the same ResponseMetadata.Error
    envelope; the structured error code lives there, not in `reason`
    (which is just the HTTP status text, e.g. "Not Found").
    """
    body = json.dumps({
        'ResponseMetadata': {
            'RequestId': request_id,
            'Error': {'Code': code, 'Message': message},
        },
    })
    return iam.ApiException(status=status, reason='boom-reason', body=body)


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


class TestApiExceptionClassification:
    """The IAM endpoint surfaces structured errors via ApiException
    (HTTP non-2xx with a JSON body) — NOT via a 200-OK envelope. This
    was learned empirically from running smoke_iam.yml against a live
    account: GetUser for a nonexistent name was raising IAMClientError
    with code='ApiException' (the HTTP reason "Not Found") instead of
    being recognized as the EntityDoesNotExist.User it actually is.

    These tests pin the contract: _make_request must parse the body
    of ApiException and route to the same error families it routes
    the inline-envelope path through.
    """

    def test_not_found_via_apiexception_returns_none_on_get(self):
        client = _make_client()
        client.api.do_call = mock.Mock(side_effect=_api_exception(
            'EntityDoesNotExist.User', 'user not found', status=404))
        # Critical: this is the exact path smoke_iam.yml hit on a
        # fresh smoke-iam-user-NNN that does not yet exist.
        assert client.get_user('does-not-exist') is None

    def test_not_found_via_apiexception_raises_notfound_on_write(self):
        client = _make_client()
        client.api.do_call = mock.Mock(side_effect=_api_exception(
            'EntityDoesNotExist.User', 'user not found', status=404))
        with pytest.raises(iam.IAMNotFound):
            client.update_user('does-not-exist', display_name='X')

    def test_already_exists_via_apiexception(self):
        client = _make_client()
        client.api.do_call = mock.Mock(side_effect=_api_exception(
            'EntityAlreadyExists.User', 'already there', status=409))
        with pytest.raises(iam.IAMAlreadyExists):
            client.create_user('dup')

    def test_other_error_via_apiexception_preserves_request_id(self):
        client = _make_client()
        client.api.do_call = mock.Mock(side_effect=_api_exception(
            'InvalidParameter.PolicyDocument', 'malformed',
            request_id='req-FROM-BODY', status=400))
        with pytest.raises(iam.IAMClientError) as exc_info:
            client.create_user('whatever')
        msg = str(exc_info.value)
        # request_id must come from the parsed body, not from the
        # ApiException's HTTP-level metadata (where it isn't available).
        assert 'req-FROM-BODY' in msg
        assert 'InvalidParameter.PolicyDocument' in msg
        assert 'malformed' in msg

    def test_apiexception_with_unparseable_body_still_raises_cleanly(self):
        # If the body isn't JSON (transport error, gateway-injected HTML,
        # etc.) we can't extract a structured code — but we still
        # shouldn't crash. Fall back to a generic IAMClientError with
        # the HTTP reason text so the operator gets *something*.
        client = _make_client()
        client.api.do_call = mock.Mock(side_effect=iam.ApiException(
            status=502, reason='Bad Gateway', body='<html>nope</html>'))
        with pytest.raises(iam.IAMClientError) as exc_info:
            client.create_user('whatever')
        msg = str(exc_info.value)
        assert 'Bad Gateway' in msg or '502' in msg

    def test_apiexception_with_no_body(self):
        # Some transport-level failures have body=None.
        client = _make_client()
        client.api.do_call = mock.Mock(side_effect=iam.ApiException(
            status=500, reason='Internal Server Error', body=None))
        with pytest.raises(iam.IAMClientError):
            client.create_user('whatever')

    # The actual BytePlus IAM error codes — learned from running
    # smoke_iam.yml against a live account. They are NOT the AWS-style
    # 'EntityDoesNotExist.User' suffixed form I originally assumed;
    # they are 'UserNotExist' / 'RoleNotExist' / 'PolicyNotExist' /
    # 'AccessKeyNotExist' / 'LoginProfileNotExist'.
    @pytest.mark.parametrize('code,resource', [
        ('UserNotExist', 'user'),
        ('RoleNotExist', 'role'),
        ('PolicyNotExist', 'policy'),
        ('AccessKeyNotExist', 'access key'),
        ('LoginProfileNotExist', 'login profile'),
    ])
    def test_byteplus_notexist_codes_map_to_notfound(self, code, resource):
        client = _make_client()
        client.api.do_call = mock.Mock(side_effect=_api_exception(
            code, '{} does not exist'.format(resource), status=404))
        # get_user is what every idempotency-via-get path uses; the
        # right answer is None, not a raised IAMClientError.
        assert client.get_user('does-not-exist') is None

    @pytest.mark.parametrize('code', [
        'UserAlreadyExists',
        'RoleAlreadyExists',
        'PolicyAlreadyExists',
    ])
    def test_byteplus_alreadyexists_codes_map_to_alreadyexists(self, code):
        client = _make_client()
        client.api.do_call = mock.Mock(side_effect=_api_exception(
            code, 'already there', status=409))
        with pytest.raises(iam.IAMAlreadyExists):
            client.create_user('dup')


class TestWireFormat:
    """The BytePlus IAM endpoint expects parameters in the query string,
    not in a JSON body — even for verbs that look like writes
    (CreateUser, UpdateUser, etc.). UniversalApi only puts params in
    the query string when info.method == 'GET' (see byteplussdkcore /
    universal.py line 80-81: `if info.method.lower() == "get":
    query_params = list(body.items())`). So every IAM verb must use
    GET, regardless of CRUD semantics. POST was sending params in the
    JSON body, and the server was rejecting them with
    `ParameterNotFound: The parameter 'UserName' is required`.
    """

    def test_create_user_uses_get_method(self):
        client = _make_client()
        client.api.do_call = mock.Mock(return_value={'Result': {}})
        client.create_user('alice')
        info, _ = client.api.do_call.call_args.args
        assert info.method == 'GET', (
            "create_user must use GET so params go on the query string")

    def test_update_user_uses_get_method(self):
        client = _make_client()
        client.api.do_call = mock.Mock(return_value={'Result': {}})
        client.update_user('alice', display_name='Alice E.')
        info, _ = client.api.do_call.call_args.args
        assert info.method == 'GET'

    def test_delete_user_uses_get_method(self):
        client = _make_client()
        client.api.do_call = mock.Mock(return_value={'Result': {}})
        client.delete_user('alice')
        info, _ = client.api.do_call.call_args.args
        assert info.method == 'GET'

    def test_create_policy_uses_get_method(self):
        client = _make_client()
        client.api.do_call = mock.Mock(return_value={'Result': {}})
        client.create_policy('p1', '{}', description='x')
        info, _ = client.api.do_call.call_args.args
        assert info.method == 'GET'

    def test_attach_user_policy_uses_get_method(self):
        client = _make_client()
        client.api.do_call = mock.Mock(return_value={'Result': {}})
        client.attach_user_policy('p1', 'alice')
        info, _ = client.api.do_call.call_args.args
        assert info.method == 'GET'

    def test_create_access_key_uses_get_method(self):
        # CreateAccessKey is the most write-y verb — generates a
        # brand new credential — and even it must use GET on this API.
        client = _make_client()
        client.api.do_call = mock.Mock(return_value={'Result': {}})
        client.create_access_key(user_name='alice')
        info, _ = client.api.do_call.call_args.args
        assert info.method == 'GET'


class TestEntityUnwrap:
    """BytePlus IAM's get_* and create_* responses wrap the entity under
    a singular type-named key: GetUser returns {'User': {...}},
    GetPolicy returns {'Policy': {...}}, GetRole returns {'Role': {...}}.
    list_* responses, on the other hand, contain bare entity dicts under
    UserMetadata / PolicyMetadata / RoleMetadata arrays — no per-entity
    wrap.

    That asymmetry is awkward at the call site (modules constantly
    forget which shape they're holding). Unwrap inside IAMClient so
    every caller — info modules included — sees bare entity dicts.
    """

    def test_get_user_unwraps_user_envelope(self):
        client = _make_client()
        # Simulate the real response shape observed live: top-level
        # 'User' key under Result (which _make_request returns).
        client.api.do_call = mock.Mock(return_value={
            'Result': {'User': {'UserName': 'alice', 'DisplayName': 'A'}},
        })
        user = client.get_user('alice')
        assert user == {'UserName': 'alice', 'DisplayName': 'A'}

    def test_get_policy_unwraps_policy_envelope(self):
        client = _make_client()
        client.api.do_call = mock.Mock(return_value={
            'Result': {'Policy': {'PolicyName': 'p1',
                                  'PolicyDocument': '{}'}},
        })
        policy = client.get_policy('p1')
        assert policy == {'PolicyName': 'p1', 'PolicyDocument': '{}'}

    def test_get_role_unwraps_role_envelope(self):
        client = _make_client()
        client.api.do_call = mock.Mock(return_value={
            'Result': {'Role': {'RoleName': 'r1'}},
        })
        role = client.get_role('r1')
        assert role == {'RoleName': 'r1'}

    def test_get_login_profile_unwraps_login_profile_envelope(self):
        client = _make_client()
        client.api.do_call = mock.Mock(return_value={
            'Result': {'LoginProfile': {'UserName': 'alice',
                                        'LoginAllowed': True}},
        })
        prof = client.get_login_profile('alice')
        assert prof == {'UserName': 'alice', 'LoginAllowed': True}

    def test_get_user_bare_response_still_works(self):
        # Defensive: if a future SDK rev or BytePlus change drops the
        # wrapper, the unwrap helper must fall back to the bare dict.
        client = _make_client()
        client.api.do_call = mock.Mock(return_value={
            'Result': {'UserName': 'alice', 'DisplayName': 'A'},
        })
        user = client.get_user('alice')
        assert user == {'UserName': 'alice', 'DisplayName': 'A'}


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
