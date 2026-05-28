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
module: byteplus_iam_policy_attachment
version_added: "1.2.0"
short_description: Attach or detach a BytePlus IAM policy to a user or role
description:
  - One module covering all four BytePlus IAM attachment verbs
    (AttachUserPolicy, DetachUserPolicy, AttachRolePolicy,
    DetachRolePolicy). Dispatched by O(target_type).
  - Idempotency pre-checks current attachments via the matching C(List*)
    verb so C(changed) is honest.
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
    description: Policy name to attach or detach.
    type: str
    required: true
  policy_type:
    description: Which policy family to look in.
    type: str
    default: Custom
    choices: [Custom, System]
  target_type:
    description: Whether the attachment target is a user or a role.
    type: str
    required: true
    choices: [user, role]
  target_name:
    description: The user name or role name receiving (or losing) the attachment.
    type: str
    required: true
  state:
    description:
      - C(present) ensures the policy is attached.
      - C(absent) ensures it is detached.
    type: str
    default: present
    choices: [present, absent]
requirements:
  - byteplus-python-sdk-v2 >= 3.0.44
'''

EXAMPLES = r'''
- name: Attach a custom policy to a user
  fardani235.byteplus.byteplus_iam_policy_attachment:
    policy_name: tos-read-only
    target_type: user
    target_name: alice
    state: present

- name: Attach a BytePlus system policy to a role
  fardani235.byteplus.byteplus_iam_policy_attachment:
    policy_name: AdministratorAccess
    policy_type: System
    target_type: role
    target_name: deploy-role
    state: present

- name: Detach the same policy
  fardani235.byteplus.byteplus_iam_policy_attachment:
    policy_name: AdministratorAccess
    policy_type: System
    target_type: role
    target_name: deploy-role
    state: absent
'''

RETURN = r'''
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


def is_attached(client, policy_name, policy_type, target_type, target_name):
    """Return True iff (policy_name, policy_type) is currently attached
    to (target_type, target_name). Matching is exact on both fields —
    the same policy_name can exist under both Custom and System scopes,
    so PolicyType is part of the identity."""
    if target_type == 'user':
        attached = client.list_attached_user_policies(target_name)
    else:
        attached = client.list_attached_role_policies(target_name)
    for a in attached or []:
        if (a.get('PolicyName') == policy_name
                and a.get('PolicyType') == policy_type):
            return True
    return False


def _attach(client, policy_name, policy_type, target_type, target_name):
    if target_type == 'user':
        return client.attach_user_policy(
            policy_name=policy_name, policy_type=policy_type,
            user_name=target_name)
    return client.attach_role_policy(
        policy_name=policy_name, policy_type=policy_type,
        role_name=target_name)


def _detach(client, policy_name, policy_type, target_type, target_name):
    if target_type == 'user':
        return client.detach_user_policy(
            policy_name=policy_name, policy_type=policy_type,
            user_name=target_name)
    return client.detach_role_policy(
        policy_name=policy_name, policy_type=policy_type,
        role_name=target_name)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            access_key=dict(type='str', required=False,
                            fallback=(env_fallback, ['BYTEPLUS_ACCESS_KEY'])),
            secret_key=dict(type='str', required=False, no_log=True,
                            fallback=(env_fallback, ['BYTEPLUS_SECRET_KEY'])),
            region=dict(type='str', default='ap-southeast-1'),
            policy_name=dict(type='str', required=True),
            policy_type=dict(type='str', default='Custom',
                             choices=['Custom', 'System']),
            target_type=dict(type='str', required=True,
                             choices=['user', 'role']),
            target_name=dict(type='str', required=True),
            state=dict(type='str', default='present',
                       choices=['present', 'absent']),
        ),
        supports_check_mode=True,
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

    try:
        currently_attached = is_attached(
            client, p['policy_name'], p['policy_type'],
            p['target_type'], p['target_name'])

        want_attached = (p['state'] == 'present')
        if currently_attached == want_attached:
            module.exit_json(changed=False)

        verb = 'attach' if want_attached else 'detach'
        if module.check_mode:
            module.exit_json(
                changed=True,
                msg="Would {} policy {!r} {} {} {!r}".format(
                    verb, p['policy_name'],
                    'to' if want_attached else 'from',
                    p['target_type'], p['target_name']))

        if want_attached:
            _attach(client, p['policy_name'], p['policy_type'],
                    p['target_type'], p['target_name'])
        else:
            _detach(client, p['policy_name'], p['policy_type'],
                    p['target_type'], p['target_name'])
    except IAMError as e:
        module.fail_json(msg=str(e))

    module.exit_json(changed=True)


if __name__ == '__main__':
    main()
