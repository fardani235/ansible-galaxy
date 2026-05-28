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
module: byteplus_iam_user_info
version_added: "1.2.0"
short_description: List or describe BytePlus IAM users
description:
  - Read-only listing or single-user describe.
  - Optionally expands per-user access-key metadata (never the secret —
    that is only ever returned at create time by C(byteplus_iam_access_key))
    and attached policies.
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
      - If set, describe just this user. Otherwise list every user.
    type: str
    required: false
  include_access_keys:
    description:
      - When true, populate C(access_keys) on each returned user with
        access-key metadata. The secret is never returned here.
    type: bool
    default: false
  include_attached_policies:
    description:
      - When true, populate C(attached_policies) on each returned user.
    type: bool
    default: false
requirements:
  - byteplus-python-sdk-v2 >= 3.0.44
'''

EXAMPLES = r'''
- name: List all IAM users
  fardani235.byteplus.byteplus_iam_user_info: {}
  register: users

- name: Describe one user with their AKs and policy attachments
  fardani235.byteplus.byteplus_iam_user_info:
    user_name: alice
    include_access_keys: true
    include_attached_policies: true
  register: alice
'''

RETURN = r'''
users:
  description: List of user dicts.
  type: list
  returned: always
count:
  description: Number of users returned.
  type: int
  returned: always
'''

from ansible.module_utils.basic import AnsibleModule, env_fallback
from ansible_collections.fardani235.byteplus.plugins.module_utils.iam_common import (
    IAMClient,
    IAMError,
)


def _expand_user(client, user, include_access_keys, include_attached_policies):
    """Decorate a user dict with optional access-key and attachment
    arrays. Mutates in place and returns the same dict for convenience."""
    user_name = user.get('UserName')
    if not user_name:
        # Defensive: the server should always populate this; if it
        # doesn't, skip expansion rather than raising — listing is a
        # read-only convenience and shouldn't fail noisily.
        return user
    if include_access_keys:
        keys = client.list_access_keys(user_name=user_name) or []
        # Strip any field that looks like it could be a secret — the
        # API doesn't return SecretAccessKey from ListAccessKeys, but
        # belt-and-braces in case a future SDK rev adds it.
        user['access_keys'] = [
            {k: v for k, v in (key or {}).items()
             if k.lower() not in ('secretaccesskey', 'secret_access_key')}
            for key in keys
        ]
    if include_attached_policies:
        user['attached_policies'] = (
            client.list_attached_user_policies(user_name=user_name) or [])
    return user


def main():
    module = AnsibleModule(
        argument_spec=dict(
            access_key=dict(type='str', required=False,
                            fallback=(env_fallback, ['BYTEPLUS_ACCESS_KEY'])),
            secret_key=dict(type='str', required=False, no_log=True,
                            fallback=(env_fallback, ['BYTEPLUS_SECRET_KEY'])),
            region=dict(type='str', default='ap-southeast-1'),
            user_name=dict(type='str', required=False),
            include_access_keys=dict(type='bool', default=False),
            include_attached_policies=dict(type='bool', default=False),
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
        if module.params['user_name']:
            user = client.get_user(module.params['user_name'])
            users = [user] if user else []
        else:
            users = list(client.list_users())

        for u in users:
            _expand_user(
                client, u,
                module.params['include_access_keys'],
                module.params['include_attached_policies'])
    except IAMError as e:
        module.fail_json(msg=str(e))

    module.exit_json(changed=False, users=users, count=len(users))


if __name__ == '__main__':
    main()
