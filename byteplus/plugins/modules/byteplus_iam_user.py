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
module: byteplus_iam_user
version_added: "1.2.0"
short_description: Manage BytePlus IAM users
description:
  - Create, update, and delete BytePlus IAM users.
  - Idempotent — only makes changes when the desired state differs from
    the server state.
  - C(user_name) is the primary key and cannot be changed by this
    module. Use the IAM console / RenameUser if you need to rename a
    user; renaming an Ansible-managed resource is generally a sign the
    inventory should rotate the name instead.
author: BytePlus
options:
  access_key:
    description:
      - BytePlus Access Key.
      - Can also be set via C(BYTEPLUS_ACCESS_KEY) environment variable.
    type: str
    required: false
  secret_key:
    description:
      - BytePlus Secret Key.
      - Can also be set via C(BYTEPLUS_SECRET_KEY) environment variable.
    type: str
    required: false
    no_log: true
  region:
    description:
      - BytePlus region. IAM is global but the SDK still requires one.
    type: str
    default: ap-southeast-1
  user_name:
    description: Login / API name for the IAM user. Primary key.
    type: str
    required: true
  display_name:
    description: Human-readable display name.
    type: str
    required: false
  description:
    description: Free-form description.
    type: str
    required: false
  email:
    description: Contact email for the user.
    type: str
    required: false
  mobile_phone:
    description: Mobile phone with country code prefix (e.g. C(+86-13800000000)).
    type: str
    required: false
  state:
    description:
      - C(present) ensures the user exists with the specified attributes.
      - C(absent) ensures the user does not exist. Delete fails (and the
        error is surfaced verbatim) when the user still has access keys
        or policy attachments — teardown is explicit, never auto-cascaded.
    type: str
    default: present
    choices: [present, absent]
requirements:
  - byteplus-python-sdk-v2 >= 3.0.44
'''

EXAMPLES = r'''
- name: Create an IAM user
  fardani235.byteplus.byteplus_iam_user:
    user_name: alice
    display_name: Alice Example
    email: alice@example.com
    state: present

- name: Update display name
  fardani235.byteplus.byteplus_iam_user:
    user_name: alice
    display_name: Alice E.
    state: present

- name: Delete user (must have no keys / attachments)
  fardani235.byteplus.byteplus_iam_user:
    user_name: alice
    state: absent
'''

RETURN = r'''
user:
  description: Full user dict from BytePlus IAM.
  type: dict
  returned: when state=present
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


# Fields that, when supplied, are compared against the server-side user
# to detect drift. UserName is the primary key and never participates
# in drift detection.
_MUTABLE_FIELDS = (
    # (module_param, server_field)
    ('display_name', 'DisplayName'),
    ('description', 'Description'),
    ('email', 'Email'),
    ('mobile_phone', 'MobilePhone'),
)


def _diff(params, existing):
    """Return a dict of {module_param: new_value} for fields the caller
    explicitly set that differ from the server-side user. Fields the
    caller did NOT set (None) are not considered drift — Ansible's "no
    value supplied" semantic is "leave it alone", not "clear it"."""
    out = {}
    for param, server in _MUTABLE_FIELDS:
        if params.get(param) is None:
            continue
        if (existing or {}).get(server) != params[param]:
            out[param] = params[param]
    return out


def _ensure_present(module, client):
    p = module.params
    existing = client.get_user(p['user_name'])

    if existing is None:
        if module.check_mode:
            module.exit_json(
                changed=True,
                msg="Would create IAM user {}".format(p['user_name']))
        client.create_user(
            user_name=p['user_name'],
            display_name=p['display_name'],
            description=p['description'],
            email=p['email'],
            mobile_phone=p['mobile_phone'],
        )
        # Re-read so the caller gets a canonical view of what BytePlus
        # actually stored (server may normalize whitespace, etc.).
        user = client.get_user(p['user_name']) or {}
        module.exit_json(changed=True, user=user)

    drift = _diff(p, existing)
    if not drift:
        module.exit_json(changed=False, user=existing)

    if module.check_mode:
        module.exit_json(
            changed=True,
            msg="Would update IAM user {}: {}".format(
                p['user_name'], sorted(drift.keys())))
    client.update_user(user_name=p['user_name'], **drift)
    user = client.get_user(p['user_name']) or {}
    module.exit_json(changed=True, user=user)


def _ensure_absent(module, client):
    p = module.params
    existing = client.get_user(p['user_name'])
    if existing is None:
        module.exit_json(changed=False)
    if module.check_mode:
        module.exit_json(
            changed=True,
            msg="Would delete IAM user {}".format(p['user_name']))
    # Surface the server's "still has keys / attachments" error verbatim
    # — same posture as byteplus_vpc. No auto-cascade.
    client.delete_user(p['user_name'])
    module.exit_json(changed=True)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            access_key=dict(type='str', required=False,
                            fallback=(env_fallback, ['BYTEPLUS_ACCESS_KEY'])),
            secret_key=dict(type='str', required=False, no_log=True,
                            fallback=(env_fallback, ['BYTEPLUS_SECRET_KEY'])),
            region=dict(type='str', default='ap-southeast-1'),
            user_name=dict(type='str', required=True),
            display_name=dict(type='str', required=False),
            description=dict(type='str', required=False),
            email=dict(type='str', required=False),
            mobile_phone=dict(type='str', required=False),
            state=dict(type='str', default='present',
                       choices=['present', 'absent']),
        ),
        supports_check_mode=True,
    )

    try:
        client = IAMClient(
            access_key=module.params['access_key'],
            secret_key=module.params['secret_key'],
            region=module.params['region'],
        )
    except Exception as e:
        module.fail_json(
            msg="Failed to initialize BytePlus IAM client: {}".format(e))

    try:
        if module.params['state'] == 'present':
            _ensure_present(module, client)
        else:
            _ensure_absent(module, client)
    except IAMError as e:
        module.fail_json(msg=str(e))


if __name__ == '__main__':
    main()
