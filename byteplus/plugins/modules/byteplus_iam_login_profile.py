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
module: byteplus_iam_login_profile
version_added: "1.2.0"
short_description: Manage the BytePlus IAM console login profile for a user
description:
  - Create, update, and delete the console login profile that lets an
    IAM user sign in to the BytePlus web console with a password.
  - BytePlus does not let us read a password back, so the module cannot
    detect password drift. By default, re-running with a different
    O(password) is a no-op — explicit O(force_password_update=true) is
    required to push a new password into an existing profile. This is a
    deliberate guard against accidental password rotation from a
    re-run of the same playbook.
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
    description: Target user.
    type: str
    required: true
  password:
    description:
      - Console login password. Required when O(state=present) and the
        profile does not yet exist.
      - On an existing profile, ignored unless O(force_password_update)
        is true. See the module description for the rationale.
    type: str
    required: false
    no_log: true
  password_reset_required:
    description:
      - Whether the user must change the password on next login.
    type: bool
    default: true
  login_allowed:
    description:
      - Whether the user is allowed to log in to the console at all.
        Setting this to false disables login without deleting the
        profile.
    type: bool
    default: true
  force_password_update:
    description:
      - Explicit opt-in to push a new password into an existing profile.
        Without this, the module never rotates a password automatically.
    type: bool
    default: false
  state:
    description:
      - C(present) creates or updates the profile.
      - C(absent) deletes it. The user account itself is not touched.
    type: str
    default: present
    choices: [present, absent]
requirements:
  - byteplus-python-sdk-v2 >= 3.0.44
'''

EXAMPLES = r'''
- name: Create a console profile (must-rotate)
  fardani235.byteplus.byteplus_iam_login_profile:
    user_name: alice
    password: "{{ lookup('password', '/dev/null length=32') }}"
    password_reset_required: true
    state: present

- name: Disable console login but keep the profile
  fardani235.byteplus.byteplus_iam_login_profile:
    user_name: alice
    login_allowed: false
    state: present

- name: Rotate the password (must opt in)
  fardani235.byteplus.byteplus_iam_login_profile:
    user_name: alice
    password: "{{ lookup('password', '/dev/null length=32') }}"
    force_password_update: true
    state: present

- name: Remove console login entirely
  fardani235.byteplus.byteplus_iam_login_profile:
    user_name: alice
    state: absent
'''

RETURN = r'''
login_profile:
  description: Login profile dict from BytePlus IAM (never includes the password).
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


def _ensure_present(module, client):
    p = module.params
    existing = client.get_login_profile(p['user_name'])

    if existing is None:
        if p['password'] is None:
            module.fail_json(
                msg=("password is required to create a new login profile "
                     "for {}").format(p['user_name']))
        if module.check_mode:
            module.exit_json(
                changed=True,
                msg=("Would create login profile for {}").format(
                    p['user_name']))
        client.create_login_profile(
            user_name=p['user_name'],
            password=p['password'],
            password_reset_required=p['password_reset_required'],
            login_allowed=p['login_allowed'],
        )
        profile = client.get_login_profile(p['user_name']) or {}
        module.exit_json(changed=True, login_profile=profile)

    # Drift detection for the fields we CAN read back.
    drift_reset = (
        existing.get('PasswordResetRequired') != p['password_reset_required'])
    drift_login = (existing.get('LoginAllowed') != p['login_allowed'])
    # Password drift is not directly observable — the API doesn't return
    # the password. We only act on password when the operator has
    # explicitly asked for a rotation.
    drift_password = bool(p['force_password_update'] and p['password'])

    if not (drift_reset or drift_login or drift_password):
        module.exit_json(changed=False, login_profile=existing)

    if module.check_mode:
        changed_keys = []
        if drift_reset:
            changed_keys.append('password_reset_required')
        if drift_login:
            changed_keys.append('login_allowed')
        if drift_password:
            changed_keys.append('password')
        module.exit_json(
            changed=True,
            msg="Would update login profile for {}: {}".format(
                p['user_name'], changed_keys))

    client.update_login_profile(
        user_name=p['user_name'],
        password=p['password'] if drift_password else None,
        password_reset_required=(
            p['password_reset_required'] if drift_reset else None),
        login_allowed=p['login_allowed'] if drift_login else None,
    )
    profile = client.get_login_profile(p['user_name']) or {}
    module.exit_json(changed=True, login_profile=profile)


def _ensure_absent(module, client):
    p = module.params
    existing = client.get_login_profile(p['user_name'])
    if existing is None:
        module.exit_json(changed=False)
    if module.check_mode:
        module.exit_json(
            changed=True,
            msg="Would delete login profile for {}".format(p['user_name']))
    client.delete_login_profile(p['user_name'])
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
            password=dict(type='str', required=False, no_log=True),
            # no_log=False is explicit on these bool flags. Ansible's
            # argspec scanner warns on any param name containing
            # "password" if no_log isn't set either way — these are
            # never sensitive on their own, only the `password` field is.
            password_reset_required=dict(type='bool', default=True, no_log=False),
            login_allowed=dict(type='bool', default=True),
            force_password_update=dict(type='bool', default=False, no_log=False),
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
