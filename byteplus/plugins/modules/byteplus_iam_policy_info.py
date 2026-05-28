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
module: byteplus_iam_policy_info
version_added: "1.2.0"
short_description: List or describe BytePlus IAM policies
description:
  - Read-only listing or single-policy describe across customer-managed
    and / or system policies.
  - Optionally expands per-policy attached users and roles.
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
  policy_name:
    description:
      - If set, describe just this policy. Otherwise list.
    type: str
    required: false
  policy_type:
    description:
      - When O(policy_name) is set, which family to look in. The same
        name can exist in both Custom and System scopes.
    type: str
    default: Custom
    choices: [Custom, System]
  scope:
    description:
      - When O(policy_name) is unset, which scope to list. C(All) lists
        both customer-managed and system policies.
    type: str
    default: All
    choices: [All, Custom, System]
  include_entities:
    description:
      - When true, populate C(attached_users) and C(attached_roles) on
        each returned policy.
    type: bool
    default: false
requirements:
  - byteplus-python-sdk-v2 >= 3.0.44
'''

EXAMPLES = r'''
- name: List all customer-managed policies
  fardani235.byteplus.byteplus_iam_policy_info:
    scope: Custom

- name: Describe one custom policy plus its attachments
  fardani235.byteplus.byteplus_iam_policy_info:
    policy_name: tos-read-only
    include_entities: true
  register: pol
'''

RETURN = r'''
policies:
  description: List of policy dicts.
  type: list
  returned: always
count:
  description: Number of policies returned.
  type: int
  returned: always
'''

from ansible.module_utils.basic import AnsibleModule, env_fallback
from ansible_collections.fardani235.byteplus.plugins.module_utils.iam_common import (
    IAMClient,
    IAMError,
)


def _expand(client, policy, include_entities):
    if not include_entities:
        return policy
    name = policy.get('PolicyName')
    if not name:
        return policy
    users, roles = client.list_entities_for_policy(
        name, policy_type=policy.get('PolicyType', 'Custom'))
    policy['attached_users'] = users
    policy['attached_roles'] = roles
    return policy


def main():
    module = AnsibleModule(
        argument_spec=dict(
            access_key=dict(type='str', required=False,
                            fallback=(env_fallback, ['BYTEPLUS_ACCESS_KEY'])),
            secret_key=dict(type='str', required=False, no_log=True,
                            fallback=(env_fallback, ['BYTEPLUS_SECRET_KEY'])),
            region=dict(type='str', default='ap-southeast-1'),
            policy_name=dict(type='str', required=False),
            policy_type=dict(type='str', default='Custom',
                             choices=['Custom', 'System']),
            scope=dict(type='str', default='All',
                       choices=['All', 'Custom', 'System']),
            include_entities=dict(type='bool', default=False),
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
        if module.params['policy_name']:
            pol = client.get_policy(
                module.params['policy_name'],
                policy_type=module.params['policy_type'])
            policies = [pol] if pol else []
        else:
            policies = list(client.list_policies(
                scope=module.params['scope']))

        for p in policies:
            _expand(client, p, module.params['include_entities'])
    except IAMError as e:
        module.fail_json(msg=str(e))

    module.exit_json(
        changed=False, policies=policies, count=len(policies))


if __name__ == '__main__':
    main()
