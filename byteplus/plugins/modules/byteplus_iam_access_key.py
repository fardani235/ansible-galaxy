#!/usr/bin/python
# -*- coding: utf-8 -*-
#
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

from __future__ import absolute_import, division, print_function

__metaclass__ = type


DOCUMENTATION = r'''
---
module: byteplus_iam_access_key
version_added: "1.2.0"
short_description: Manage BytePlus IAM access keys
description:
  - Create, deactivate / reactivate, delete, or rotate IAM access keys
    for a user. C(secret_access_key) is only ever returned at create
    time, only once — the BytePlus API has no GetAccessKey endpoint.
    The module wraps the return in C(no_log_values) so the secret does
    not leak into Ansible logs.
  - Without O(access_key_id) and without O(rotate), C(state=present)
    guarantees the user has at least one C(Active) key; if they have
    none, a new one is created.
  - O(rotate=true) creates a new key and deactivates the oldest existing
    key. If the user already has two keys (BytePlus's documented
    maximum), the module fails before calling CreateAccessKey rather
    than silently overwriting a key the operator may still rely on.
author: BytePlus
options:
  access_key:
    description: BytePlus access key (or C(BYTEPLUS_ACCESS_KEY)).
    type: str
    required: false
  secret_key:
    description: BytePlus secret key (or C(BYTEPLUS_SECRET_KEY)).
    type: str
    required: false
    no_log: true
  region:
    description: BytePlus region.
    type: str
    default: ap-southeast-1
  user_name:
    description:
      - The IAM user whose access keys to manage. Omit to manage the
        calling account's own root keys (rarely correct for automation).
    type: str
    required: false
  access_key_id:
    description:
      - Address a specific existing key. Required for explicit
        deactivate / reactivate or for C(state=absent) targeting one key.
      - Mutually exclusive with O(rotate).
    type: str
    required: false
  status:
    description:
      - Desired status of an existing key. Only meaningful when
        O(access_key_id) is supplied.
    type: str
    required: false
    choices: [active, inactive]
  rotate:
    description:
      - Create a new key and deactivate the oldest existing one.
      - Mutually exclusive with O(access_key_id).
    type: bool
    default: false
  state:
    description:
      - C(present) ensures the targeted key (or at least one key) exists
        with the desired status.
      - C(absent) deletes the addressed key.
    type: str
    default: present
    choices: [present, absent]
requirements:
  - byteplus-python-sdk-v2 >= 3.0.44
'''

EXAMPLES = r'''
- name: Ensure alice has at least one active access key
  fardani235.byteplus.byteplus_iam_access_key:
    user_name: alice
    state: present
  register: ak
- name: Capture the secret somewhere safe (only available at create)
  set_fact:
    alice_secret: "{{ ak.access_key.secret_access_key | default(omit) }}"
  when: ak.changed

- name: Deactivate a specific key
  fardani235.byteplus.byteplus_iam_access_key:
    user_name: alice
    access_key_id: AKIAEXAMPLE
    status: inactive
    state: present

- name: Rotate alice's keys (deactivates oldest, returns new secret)
  fardani235.byteplus.byteplus_iam_access_key:
    user_name: alice
    rotate: true
  register: rotated

- name: Delete a key explicitly
  fardani235.byteplus.byteplus_iam_access_key:
    user_name: alice
    access_key_id: AKIAEXAMPLE
    state: absent
'''

RETURN = r'''
access_key:
  description:
    - Newly created key, including C(secret_access_key). ONLY returned
      at create time. The module wraps this value in no_log_values.
  type: dict
  returned: when a new key was created
keys:
  description: All access keys for the user after the run, without secrets.
  type: list
  returned: always
changed:
  description: Whether any change was made.
  type: bool
  returned: always
'''

from ansible.module_utils.basic import AnsibleModule, env_fallback
from ansible_collections.fardani235.byteplus.plugins.module_utils.iam_common import (
    IAMClient,
    IAMError,
)


# Wire values for AccessKey.Status. The BytePlus API uses 'active' /
# 'inactive' (lowercase) — different from AWS IAM's 'Active' / 'Inactive'.
_STATUS_ACTIVE = 'active'
_STATUS_INACTIVE = 'inactive'


def _normalize_status(value):
    """Tolerant comparison helper — older SDK versions have returned
    'Active' (PascalCase) instead of 'active' for the same field."""
    if value is None:
        return None
    return str(value).lower()


def _needs_deactivate_before_delete(key):
    """BytePlus IAM refuses to DeleteAccessKey on a key in 'active'
    status — the server error is C(AccessKeyCanNotDelete): 'The access
    key identity is active, can not be deleted.' (Verified live via
    smoke_iam.yml.) Callers must deactivate the key first.

    Returns True if the key needs deactivation. A missing Status field
    is treated as active (the safer default — a spurious deactivate is
    a no-op; a missing deactivate aborts the delete with an opaque
    server error)."""
    if not key:
        return True
    status = _normalize_status(key.get('Status'))
    if status is None:
        return True
    return status == _STATUS_ACTIVE


def find_oldest_active(keys):
    """Return the AccessKey.Id of the oldest key whose status is Active,
    or None if there is none. Used by rotate to pick which key to
    deactivate after creating a fresh one."""
    actives = [
        k for k in (keys or [])
        if _normalize_status(k.get('Status')) == _STATUS_ACTIVE
    ]
    if not actives:
        return None
    # CreateDate is an ISO-8601 string; lexicographic sort is correct
    # for that format. Falls back to AccessKeyId for stable ordering
    # when CreateDate is missing.
    actives.sort(key=lambda k: (
        k.get('CreateDate') or '', k.get('AccessKeyId') or ''))
    return actives[0].get('AccessKeyId')


def _strip_secrets(keys):
    """Return a copy of `keys` with any secret-shaped field stripped.
    Used to shape the always-returned `keys` field — secret only ever
    rides on the freshly-returned `access_key` dict."""
    cleaned = []
    for k in keys or []:
        cleaned.append({
            field: value for field, value in (k or {}).items()
            if field.lower() not in ('secretaccesskey', 'secret_access_key')
        })
    return cleaned


def _do_rotate(module, client, user_name, existing):
    """Handle rotate=true: create one new key, deactivate the oldest
    existing active key. Fails fast if the user already has 2 keys —
    BytePlus's documented hard cap."""
    if len(existing) >= 2:
        module.fail_json(
            msg=("Cannot rotate: user {!r} already has {} access keys "
                 "(BytePlus maximum is 2). Delete one explicitly first "
                 "with state=absent and access_key_id=...").format(
                 user_name, len(existing)))

    if module.check_mode:
        module.exit_json(
            changed=True,
            msg="Would create a new access key and deactivate the "
                "oldest active one")

    create_resp = client.create_access_key(user_name=user_name) or {}
    new_key = create_resp.get('AccessKey') or {}

    # The new key's secret is in here — register the values with the
    # module so callbacks / logs redact them.
    secret = (new_key.get('SecretAccessKey')
              or new_key.get('secret_access_key'))
    if secret:
        module.no_log_values.add(secret)

    # Deactivate the oldest active key, if any. We do this AFTER
    # creating the new key so a failure in CreateAccessKey leaves the
    # old key intact and operational.
    oldest_id = find_oldest_active(existing)
    if oldest_id:
        client.update_access_key(
            access_key_id=oldest_id, status=_STATUS_INACTIVE,
            user_name=user_name)

    keys = _strip_secrets(
        client.list_access_keys(user_name=user_name) or [])
    module.exit_json(changed=True, access_key=new_key, keys=keys)


def _ensure_present_specific(module, client, user_name, key_id, status):
    """state=present with access_key_id set — toggle status of one key.
    No create."""
    existing = client.list_access_keys(user_name=user_name) or []
    found = next(
        (k for k in existing
         if (k.get('AccessKeyId') or k.get('access_key_id')) == key_id),
        None)
    if found is None:
        module.fail_json(
            msg="Access key {!r} does not exist for user {!r}".format(
                key_id, user_name))

    want_status = status or _STATUS_ACTIVE
    have_status = _normalize_status(found.get('Status'))
    if have_status == want_status:
        module.exit_json(
            changed=False, keys=_strip_secrets(existing))

    if module.check_mode:
        module.exit_json(
            changed=True,
            msg="Would set access key {} status to {}".format(
                key_id, want_status))
    client.update_access_key(
        access_key_id=key_id, status=want_status, user_name=user_name)
    keys = _strip_secrets(
        client.list_access_keys(user_name=user_name) or [])
    module.exit_json(changed=True, keys=keys)


def _ensure_present_any(module, client, user_name):
    """state=present, no access_key_id, no rotate — guarantee the user
    has at least one Active key. Create one if not."""
    existing = client.list_access_keys(user_name=user_name) or []
    any_active = any(
        _normalize_status(k.get('Status')) == _STATUS_ACTIVE
        for k in existing)
    if any_active:
        module.exit_json(
            changed=False, keys=_strip_secrets(existing))
    if len(existing) >= 2:
        module.fail_json(
            msg=("User {!r} has no Active keys but already has 2 "
                 "(inactive) keys, which is BytePlus's maximum. "
                 "Delete one with state=absent and access_key_id=... "
                 "before creating a new one.").format(user_name))
    if module.check_mode:
        module.exit_json(
            changed=True, msg="Would create a new access key")
    resp = client.create_access_key(user_name=user_name) or {}
    new_key = resp.get('AccessKey') or {}
    secret = (new_key.get('SecretAccessKey')
              or new_key.get('secret_access_key'))
    if secret:
        module.no_log_values.add(secret)
    keys = _strip_secrets(
        client.list_access_keys(user_name=user_name) or [])
    module.exit_json(changed=True, access_key=new_key, keys=keys)


def _ensure_absent(module, client, user_name, key_id):
    existing = client.list_access_keys(user_name=user_name) or []
    if key_id is None:
        module.fail_json(
            msg="access_key_id is required when state=absent")
    found = next(
        (k for k in existing
         if (k.get('AccessKeyId') or k.get('access_key_id')) == key_id),
        None)
    if found is None:
        module.exit_json(
            changed=False, keys=_strip_secrets(existing))
    if module.check_mode:
        module.exit_json(
            changed=True,
            msg="Would delete access key {}".format(key_id))
    # BytePlus refuses to delete an Active key with AccessKeyCanNotDelete.
    # Deactivate first; if the deactivate fails we'd rather surface that
    # specific error than the bewildering CanNotDelete one.
    if _needs_deactivate_before_delete(found):
        client.update_access_key(
            access_key_id=key_id, status=_STATUS_INACTIVE,
            user_name=user_name)
    client.delete_access_key(
        access_key_id=key_id, user_name=user_name)
    keys = _strip_secrets(
        client.list_access_keys(user_name=user_name) or [])
    module.exit_json(changed=True, keys=keys)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            access_key=dict(type='str', required=False,
                            fallback=(env_fallback, ['BYTEPLUS_ACCESS_KEY'])),
            secret_key=dict(type='str', required=False, no_log=True,
                            fallback=(env_fallback, ['BYTEPLUS_SECRET_KEY'])),
            region=dict(type='str', default='ap-southeast-1'),
            user_name=dict(type='str', required=False),
            access_key_id=dict(type='str', required=False),
            status=dict(type='str', required=False,
                        choices=['active', 'inactive']),
            rotate=dict(type='bool', default=False),
            state=dict(type='str', default='present',
                       choices=['present', 'absent']),
        ),
        supports_check_mode=True,
        mutually_exclusive=[('access_key_id', 'rotate')],
    )

    p = module.params
    try:
        client = IAMClient(
            access_key=p['access_key'],
            secret_key=p['secret_key'],
            region=p['region'],
        )
    except Exception as e:
        module.fail_json(
            msg="Failed to initialize BytePlus IAM client: {}".format(e))

    user_name = p['user_name']
    try:
        if p['state'] == 'absent':
            _ensure_absent(module, client, user_name, p['access_key_id'])
        elif p['rotate']:
            existing = client.list_access_keys(user_name=user_name) or []
            _do_rotate(module, client, user_name, existing)
        elif p['access_key_id']:
            _ensure_present_specific(
                module, client, user_name, p['access_key_id'], p['status'])
        else:
            _ensure_present_any(module, client, user_name)
    except IAMError as e:
        module.fail_json(msg=str(e))


if __name__ == '__main__':
    main()
