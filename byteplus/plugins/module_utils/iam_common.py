# Copyright fardani235
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Helpers for the BytePlus IAM modules.

`IAMClient` wraps `byteplussdkcore.UniversalApi` for the BytePlus IAM
HTTP API (`iam.byteplusapi.com`, service `iam`, version `2018-01-01`).

The installed BytePlus Python SDK ships only the Projects slice of IAM
(`byteplussdkiam20210801`) — no User/Policy/Role/AK verbs — so we hit
the public HTTP API directly through `UniversalApi`. Same pattern as
`byteplus_common.BytePlusClient` does for DNS.

DO NOT add request-body debug logging (e.g. `module.debug(params)`) in
this file — `password`, `policy_document`, and `trust_policy_document`
flow through here, and Ansible logs are typically world-readable.
Surface request_id in errors instead.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import json

from byteplussdkcore.configuration import Configuration
from byteplussdkcore.universal import UniversalApi, UniversalInfo
from byteplussdkcore.rest import ApiException


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class IAMError(Exception):
    """Base for all IAMClient-raised errors."""


class IAMNotFound(IAMError):
    """Raised when a write verb (Update/Delete/Attach/etc.) targets an
    entity that doesn't exist. `get_*` returns None in this case instead."""


class IAMAlreadyExists(IAMError):
    """Raised when Create hits an existing entity with the same primary
    key. Modules re-`get_*` to converge."""


class IAMClientError(IAMError):
    """Catch-all for non-Found/AlreadyExists API errors. Carries the
    action, error code, message, and request_id so an operator can hand
    request_id to BytePlus support."""

    def __init__(self, action, code, message, request_id):
        self.action = action
        self.code = code
        self.message = message
        self.request_id = request_id
        super(IAMClientError, self).__init__(
            "BytePlus IAM {} failed [{}]: {} (request_id={})".format(
                action, code, message, request_id))


# Error-code prefixes used to dispatch to the right exception class. The
# BytePlus IAM API uses suffixed codes like `EntityDoesNotExist.User`,
# `EntityAlreadyExists.Policy`, so we match by prefix.
_NOT_FOUND_PREFIX = 'EntityDoesNotExist'
_ALREADY_EXISTS_PREFIX = 'EntityAlreadyExists'


# ---------------------------------------------------------------------------
# Pure helpers (no I/O — unit-tested without the SDK)
# ---------------------------------------------------------------------------


def canonicalize_policy_document(doc):
    """Return a canonical string form of a policy / trust-policy document.

    BytePlus reformats documents on the round trip (key order, whitespace),
    so the only safe way to detect drift is to parse both sides and
    re-serialize with sorted keys. Comparing raw strings yields false
    "changed" results on every run.

    Accepts either a dict (Ansible YAML-decoded) or a string (raw JSON
    pasted by the caller). Returns a string.
    """
    if isinstance(doc, str):
        try:
            parsed = json.loads(doc)
        except ValueError as e:
            raise ValueError(
                "policy_document is not valid JSON: {}".format(e))
    elif isinstance(doc, dict):
        parsed = doc
    else:
        raise TypeError(
            "policy_document must be a dict or JSON string, "
            "got {}".format(type(doc).__name__))
    return json.dumps(parsed, sort_keys=True, separators=(',', ':'))


# ---------------------------------------------------------------------------
# IAMClient
# ---------------------------------------------------------------------------


class IAMClient(object):
    """Thin per-verb wrapper over UniversalApi for service=iam.

    One method per BytePlus IAM action — no generic do(action, params)
    pass-through. The surface is small enough that explicit verbs are
    reviewable and mockable, and the call sites in modules read like
    intent rather than RPC."""

    SERVICE = 'iam'
    VERSION = '2018-01-01'

    def __init__(self, access_key, secret_key, region):
        config = Configuration()
        config.ak = access_key
        config.sk = secret_key
        config.region = region
        Configuration.set_default(config)
        self.api = UniversalApi()

    # ----- transport -----

    def _make_request(self, action, params=None, method='POST'):
        """Dispatch one BytePlus IAM action and classify the response.

        The BytePlus IAM endpoint surfaces structured errors via
        ApiException (HTTP non-2xx + JSON body) — NOT via a 200-OK
        inline envelope. We support both shapes for defense-in-depth:
        some IAM verbs (and other services this client may someday be
        retargeted at) can return inline error envelopes too.

        We never log `params` here — see the file-level docstring.
        """
        content_type = (
            'application/json' if method == 'POST' else 'text/plain')
        info = UniversalInfo(
            method=method,
            service=self.SERVICE,
            version=self.VERSION,
            action=action,
            content_type=content_type,
        )
        try:
            resp = self.api.do_call(info, params or {})
        except ApiException as e:
            # The structured error is in e.body, NOT e.reason. e.reason
            # is just the HTTP status text ("Not Found", "Bad Gateway"),
            # which loses every distinction we need to classify into
            # NotFound / AlreadyExists / other.
            self._raise_classified(action, e)

        meta = (resp or {}).get('ResponseMetadata') or {}
        err = meta.get('Error') or {}
        if err:
            self._raise_from_envelope(action, err, meta)

        # Successful responses use `Result` for the payload; callers
        # that need the raw envelope can read `resp` themselves, but
        # the verbs below return the unwrapped Result for convenience.
        return resp.get('Result', resp) if resp else {}

    def _raise_classified(self, action, api_exc):
        """Classify an ApiException raised by UniversalApi into the right
        IAMError subclass. Parses the JSON body for ResponseMetadata.Error;
        falls back to a generic IAMClientError if the body is missing or
        unparseable."""
        body = getattr(api_exc, 'body', None)
        parsed = None
        if body:
            try:
                # Body is usually a string; some SDK paths pre-parse it.
                parsed = (body if isinstance(body, dict)
                          else json.loads(body))
            except (ValueError, TypeError):
                parsed = None

        meta = (parsed or {}).get('ResponseMetadata') or {}
        err = meta.get('Error') or {}
        if err:
            self._raise_from_envelope(action, err, meta)

        # No structured envelope — fall back to whatever we can show.
        reason = getattr(api_exc, 'reason', None) or str(api_exc)
        status = getattr(api_exc, 'status', None)
        message = ("{}: {}".format(status, reason)
                   if status else reason)
        raise IAMClientError(
            action=action, code='ApiException',
            message=message, request_id='(none)')

    @staticmethod
    def _raise_from_envelope(action, err, meta):
        """Common dispatch: NotFound / AlreadyExists / other, from a
        decoded ResponseMetadata.Error dict."""
        code = err.get('Code') or 'Unknown'
        message = err.get('Message') or ''
        request_id = meta.get('RequestId') or '(none)'
        if code.startswith(_NOT_FOUND_PREFIX):
            raise IAMNotFound(
                "{} not found [{}]: {} (request_id={})".format(
                    action, code, message, request_id))
        if code.startswith(_ALREADY_EXISTS_PREFIX):
            raise IAMAlreadyExists(
                "{} already exists [{}]: {} (request_id={})".format(
                    action, code, message, request_id))
        raise IAMClientError(
            action=action, code=code,
            message=message, request_id=request_id)

    # ----- pagination -----

    # BytePlus IAM list endpoints use Limit/Offset cursoring. The server
    # returns IsTruncated=true and a `Marker` (the next Offset) when more
    # pages follow. Keep the page size moderately large — 100 is the
    # documented per-call ceiling for IAM list verbs.
    _PAGE_SIZE = 100

    def _paginate(self, action, result_key, params=None, method='GET'):
        """Walk Limit/Offset pagination for a list action.

        Yields one entity dict at a time. The caller chooses the
        `result_key` (e.g. 'UserMetadata', 'PolicyMetadata') because the
        server uses a different array name per object type.
        """
        base = dict(params or {})
        base.setdefault('Limit', self._PAGE_SIZE)
        offset = None
        while True:
            # Send a fresh dict each call. Mutating `base` in place would
            # have us retroactively change what the previous call "saw"
            # from the mock's / API client's perspective, and makes
            # paginator tests harder to reason about.
            page_params = dict(base)
            if offset is not None:
                page_params['Offset'] = offset
            resp = self._make_request(action, page_params, method=method) or {}
            for entity in resp.get(result_key) or []:
                yield entity
            if not resp.get('IsTruncated'):
                return
            # The server's `Marker` value is the next Offset to send.
            # We default to incrementing by Limit if it's missing —
            # better to risk re-reading a page than to silently stop
            # halfway through a paginated list.
            marker = resp.get('Marker')
            if marker is None:
                marker = (offset or 0) + base['Limit']
            offset = marker

    # ----- users -----

    def create_user(self, user_name, display_name=None, description=None,
                    email=None, mobile_phone=None):
        params = {'UserName': user_name}
        if display_name is not None:
            params['DisplayName'] = display_name
        if description is not None:
            params['Description'] = description
        if email is not None:
            params['Email'] = email
        if mobile_phone is not None:
            params['MobilePhone'] = mobile_phone
        return self._make_request('CreateUser', params)

    def get_user(self, user_name):
        """Return the user dict, or None if it doesn't exist."""
        try:
            return self._make_request(
                'GetUser', {'UserName': user_name}, method='GET')
        except IAMNotFound:
            return None

    def update_user(self, user_name, new_user_name=None, display_name=None,
                    description=None, email=None, mobile_phone=None):
        params = {'UserName': user_name}
        if new_user_name is not None:
            params['NewUserName'] = new_user_name
        if display_name is not None:
            params['NewDisplayName'] = display_name
        if description is not None:
            params['NewDescription'] = description
        if email is not None:
            params['NewEmail'] = email
        if mobile_phone is not None:
            params['NewMobilePhone'] = mobile_phone
        return self._make_request('UpdateUser', params)

    def delete_user(self, user_name):
        return self._make_request('DeleteUser', {'UserName': user_name})

    def list_users(self):
        """Yield every user in the account, handling pagination."""
        return self._paginate('ListUsers', 'UserMetadata')

    # ----- login profiles -----

    def get_login_profile(self, user_name):
        try:
            return self._make_request(
                'GetLoginProfile', {'UserName': user_name}, method='GET')
        except IAMNotFound:
            return None

    def create_login_profile(self, user_name, password,
                             password_reset_required=True,
                             login_allowed=True):
        params = {
            'UserName': user_name,
            'Password': password,
            'LoginAllowed': login_allowed,
            'PasswordResetRequired': password_reset_required,
        }
        return self._make_request('CreateLoginProfile', params)

    def update_login_profile(self, user_name, password=None,
                             password_reset_required=None, login_allowed=None):
        params = {'UserName': user_name}
        if password is not None:
            params['Password'] = password
        if password_reset_required is not None:
            params['PasswordResetRequired'] = password_reset_required
        if login_allowed is not None:
            params['LoginAllowed'] = login_allowed
        return self._make_request('UpdateLoginProfile', params)

    def delete_login_profile(self, user_name):
        return self._make_request(
            'DeleteLoginProfile', {'UserName': user_name})

    # ----- access keys -----

    def create_access_key(self, user_name=None):
        params = {}
        if user_name is not None:
            params['UserName'] = user_name
        return self._make_request('CreateAccessKey', params)

    def update_access_key(self, access_key_id, status, user_name=None):
        # `status` is the BytePlus wire value: 'active' or 'inactive'.
        params = {'AccessKeyId': access_key_id, 'Status': status}
        if user_name is not None:
            params['UserName'] = user_name
        return self._make_request('UpdateAccessKey', params)

    def delete_access_key(self, access_key_id, user_name=None):
        params = {'AccessKeyId': access_key_id}
        if user_name is not None:
            params['UserName'] = user_name
        return self._make_request('DeleteAccessKey', params)

    def list_access_keys(self, user_name=None):
        params = {}
        if user_name is not None:
            params['UserName'] = user_name
        # ListAccessKeys does NOT paginate in the same Limit/Offset style
        # because a user is capped at 2 keys server-side — just unwrap
        # the single-shot response.
        resp = self._make_request(
            'ListAccessKeys', params, method='GET') or {}
        return resp.get('AccessKeyMetadata') or []

    # ----- policies -----

    def create_policy(self, policy_name, policy_document, description=None):
        params = {
            'PolicyName': policy_name,
            'PolicyDocument': policy_document,
        }
        if description is not None:
            params['Description'] = description
        return self._make_request('CreatePolicy', params)

    def get_policy(self, policy_name, policy_type='Custom'):
        try:
            return self._make_request(
                'GetPolicy',
                {'PolicyName': policy_name, 'PolicyType': policy_type},
                method='GET')
        except IAMNotFound:
            return None

    def update_policy(self, policy_name, policy_document=None,
                      description=None):
        params = {'PolicyName': policy_name}
        if policy_document is not None:
            params['NewPolicyDocument'] = policy_document
        if description is not None:
            params['NewDescription'] = description
        return self._make_request('UpdatePolicy', params)

    def delete_policy(self, policy_name):
        return self._make_request(
            'DeletePolicy', {'PolicyName': policy_name})

    def list_policies(self, scope=None):
        params = {}
        if scope is not None:
            # 'Custom' / 'System' / 'All'
            params['Scope'] = scope
        return self._paginate(
            'ListPolicies', 'PolicyMetadata', params=params)

    # ----- attachments -----

    def attach_user_policy(self, policy_name, user_name,
                           policy_type='Custom'):
        return self._make_request('AttachUserPolicy', {
            'PolicyName': policy_name,
            'PolicyType': policy_type,
            'UserName': user_name,
        })

    def detach_user_policy(self, policy_name, user_name,
                           policy_type='Custom'):
        return self._make_request('DetachUserPolicy', {
            'PolicyName': policy_name,
            'PolicyType': policy_type,
            'UserName': user_name,
        })

    def list_attached_user_policies(self, user_name):
        resp = self._make_request(
            'ListAttachedUserPolicies',
            {'UserName': user_name}, method='GET') or {}
        return resp.get('AttachedPolicyMetadata') or []

    def attach_role_policy(self, policy_name, role_name,
                           policy_type='Custom'):
        return self._make_request('AttachRolePolicy', {
            'PolicyName': policy_name,
            'PolicyType': policy_type,
            'RoleName': role_name,
        })

    def detach_role_policy(self, policy_name, role_name,
                           policy_type='Custom'):
        return self._make_request('DetachRolePolicy', {
            'PolicyName': policy_name,
            'PolicyType': policy_type,
            'RoleName': role_name,
        })

    def list_attached_role_policies(self, role_name):
        resp = self._make_request(
            'ListAttachedRolePolicies',
            {'RoleName': role_name}, method='GET') or {}
        return resp.get('AttachedPolicyMetadata') or []

    def list_entities_for_policy(self, policy_name, policy_type='Custom'):
        """Return (attached_users, attached_roles) name lists for a
        policy. Used by byteplus_iam_policy_info include_entities."""
        resp = self._make_request(
            'ListEntitiesForPolicy',
            {'PolicyName': policy_name, 'PolicyType': policy_type},
            method='GET') or {}
        users = [u.get('UserName')
                 for u in (resp.get('PolicyUsers') or [])
                 if u.get('UserName')]
        roles = [r.get('RoleName')
                 for r in (resp.get('PolicyRoles') or [])
                 if r.get('RoleName')]
        return users, roles

    # ----- roles -----

    def create_role(self, role_name, trust_policy_document,
                    description=None, max_session_duration=None):
        params = {
            'RoleName': role_name,
            'TrustPolicyDocument': trust_policy_document,
        }
        if description is not None:
            params['Description'] = description
        if max_session_duration is not None:
            params['MaxSessionDuration'] = max_session_duration
        return self._make_request('CreateRole', params)

    def get_role(self, role_name):
        try:
            return self._make_request(
                'GetRole', {'RoleName': role_name}, method='GET')
        except IAMNotFound:
            return None

    def update_role(self, role_name, trust_policy_document=None,
                    description=None, max_session_duration=None):
        params = {'RoleName': role_name}
        if trust_policy_document is not None:
            params['NewTrustPolicyDocument'] = trust_policy_document
        if description is not None:
            params['NewDescription'] = description
        if max_session_duration is not None:
            params['NewMaxSessionDuration'] = max_session_duration
        return self._make_request('UpdateRole', params)

    def delete_role(self, role_name):
        return self._make_request('DeleteRole', {'RoleName': role_name})

    def list_roles(self):
        return self._paginate('ListRoles', 'RoleMetadata')
