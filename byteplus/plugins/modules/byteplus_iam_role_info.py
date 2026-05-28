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
module: byteplus_iam_role_info
version_added: "1.2.0"
short_description: List or describe BytePlus IAM roles
description:
  - Read-only listing or single-role describe.
  - Optionally expands per-role attached policies.
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
  role_name:
    description:
      - If set, describe just this role. Otherwise list every role.
    type: str
    required: false
  include_attached_policies:
    description:
      - When true, populate C(attached_policies) on each returned role.
    type: bool
    default: false
requirements:
  - byteplus-python-sdk-v2 >= 3.0.44
'''

EXAMPLES = r'''
- name: List all roles
  fardani235.byteplus.byteplus_iam_role_info: {}

- name: Describe one role with attachments
  fardani235.byteplus.byteplus_iam_role_info:
    role_name: ecs-runtime-role
    include_attached_policies: true
'''

RETURN = r'''
roles:
  description: List of role dicts.
  type: list
  returned: always
count:
  description: Number of roles returned.
  type: int
  returned: always
'''

from ansible.module_utils.basic import AnsibleModule, env_fallback
from ansible_collections.fardani235.byteplus.plugins.module_utils.iam_common import (
    IAMClient,
    IAMError,
)


def _expand(client, role, include_attached_policies):
    if not include_attached_policies:
        return role
    name = role.get('RoleName')
    if not name:
        return role
    role['attached_policies'] = (
        client.list_attached_role_policies(name) or [])
    return role


def main():
    module = AnsibleModule(
        argument_spec=dict(
            access_key=dict(type='str', required=False,
                            fallback=(env_fallback, ['BYTEPLUS_ACCESS_KEY'])),
            secret_key=dict(type='str', required=False, no_log=True,
                            fallback=(env_fallback, ['BYTEPLUS_SECRET_KEY'])),
            region=dict(type='str', default='ap-southeast-1'),
            role_name=dict(type='str', required=False),
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
        if module.params['role_name']:
            role = client.get_role(module.params['role_name'])
            roles = [role] if role else []
        else:
            roles = list(client.list_roles())

        for r in roles:
            _expand(client, r, module.params['include_attached_policies'])
    except IAMError as e:
        module.fail_json(msg=str(e))

    module.exit_json(changed=False, roles=roles, count=len(roles))


if __name__ == '__main__':
    main()
