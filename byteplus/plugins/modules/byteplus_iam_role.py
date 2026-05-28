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
module: byteplus_iam_role
version_added: "1.2.0"
short_description: Manage BytePlus IAM roles
description:
  - Create, update, and delete BytePlus IAM roles.
  - Idempotent — trust policy is compared after parse-then-key-sort, so
    re-running with a syntactically different but semantically identical
    JSON document does not register as a change.
  - Delete fails (and the error is surfaced verbatim) when the role
    still has attached policies — teardown is explicit, never auto-cascaded.
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
    description: Role name. Primary key.
    type: str
    required: true
  trust_policy_document:
    description:
      - The trust-relationship document. Accepts a dict or a JSON string.
        Required when O(state=present).
    type: raw
    required: false
  description:
    description: Free-form description.
    type: str
    required: false
  max_session_duration:
    description:
      - Maximum session duration for AssumeRole, in seconds.
      - BytePlus default is 3600 (1 hour). Maximum is 43200 (12 hours).
    type: int
    required: false
  state:
    description:
      - C(present) ensures the role exists with the specified attributes.
      - C(absent) ensures the role does not exist.
    type: str
    default: present
    choices: [present, absent]
requirements:
  - byteplus-python-sdk-v2 >= 3.0.44
'''

EXAMPLES = r'''
- name: Create a role assumable by ECS instances
  fardani235.byteplus.byteplus_iam_role:
    role_name: ecs-runtime-role
    description: Used by ECS instances at runtime
    max_session_duration: 7200
    trust_policy_document:
      Statement:
        - Effect: Allow
          Principal:
            Service: [ecs]
          Action: sts:AssumeRole
    state: present

- name: Delete the role (must have no attached policies)
  fardani235.byteplus.byteplus_iam_role:
    role_name: ecs-runtime-role
    state: absent
'''

RETURN = r'''
role:
  description: Full role dict from BytePlus IAM.
  type: dict
  returned: when state=present
changed:
  description: Whether any change was made.
  type: bool
  returned: always
'''

import json

from ansible.module_utils.basic import AnsibleModule, env_fallback
from ansible_collections.fardani235.byteplus.plugins.module_utils.iam_common import (
    IAMClient,
    IAMError,
    canonicalize_policy_document,
)


_MIN_SESSION = 3600
_MAX_SESSION = 43200


def _wire_document(doc):
    """Same as byteplus_iam_policy._wire_document — server wants a JSON
    string, callers may have given us a dict or a string. Validate the
    string case so the operator sees a clean error instead of the
    server's blunt one."""
    if doc is None:
        return None
    if isinstance(doc, str):
        try:
            json.loads(doc)
        except ValueError as e:
            raise ValueError(
                "trust_policy_document is not valid JSON: {}".format(e))
        return doc
    return json.dumps(doc)


def _ensure_present(module, client):
    p = module.params
    if p['trust_policy_document'] is None:
        module.fail_json(
            msg="trust_policy_document is required when state=present")
    msd = p.get('max_session_duration')
    if msd is not None and (msd < _MIN_SESSION or msd > _MAX_SESSION):
        module.fail_json(
            msg=("max_session_duration must be between {} and {} seconds, "
                 "got {}").format(_MIN_SESSION, _MAX_SESSION, msd))

    try:
        wire_doc = _wire_document(p['trust_policy_document'])
        new_canon = canonicalize_policy_document(
            p['trust_policy_document'],
            param_name='trust_policy_document')
    except (ValueError, TypeError) as e:
        module.fail_json(msg=str(e))

    existing = client.get_role(p['role_name'])

    if existing is None:
        if module.check_mode:
            module.exit_json(
                changed=True,
                msg="Would create role {}".format(p['role_name']))
        client.create_role(
            role_name=p['role_name'],
            trust_policy_document=wire_doc,
            description=p['description'],
            max_session_duration=msd,
        )
        role = client.get_role(p['role_name']) or {}
        module.exit_json(changed=True, role=role)

    server_doc = existing.get('TrustPolicyDocument')
    try:
        existing_canon = (
            canonicalize_policy_document(server_doc)
            if server_doc is not None else None)
    except (ValueError, TypeError):
        existing_canon = None

    drift_doc = existing_canon != new_canon
    drift_desc = (p['description'] is not None
                  and existing.get('Description') != p['description'])
    drift_msd = (msd is not None
                 and existing.get('MaxSessionDuration') != msd)

    if not (drift_doc or drift_desc or drift_msd):
        module.exit_json(changed=False, role=existing)

    if module.check_mode:
        changed_keys = []
        if drift_doc:
            changed_keys.append('trust_policy_document')
        if drift_desc:
            changed_keys.append('description')
        if drift_msd:
            changed_keys.append('max_session_duration')
        module.exit_json(
            changed=True,
            msg="Would update role {}: {}".format(
                p['role_name'], changed_keys))

    client.update_role(
        role_name=p['role_name'],
        trust_policy_document=wire_doc if drift_doc else None,
        description=p['description'] if drift_desc else None,
        max_session_duration=msd if drift_msd else None,
    )
    role = client.get_role(p['role_name']) or {}
    module.exit_json(changed=True, role=role)


def _ensure_absent(module, client):
    p = module.params
    existing = client.get_role(p['role_name'])
    if existing is None:
        module.exit_json(changed=False)
    if module.check_mode:
        module.exit_json(
            changed=True,
            msg="Would delete role {}".format(p['role_name']))
    client.delete_role(p['role_name'])
    module.exit_json(changed=True)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            access_key=dict(type='str', required=False,
                            fallback=(env_fallback, ['BYTEPLUS_ACCESS_KEY'])),
            secret_key=dict(type='str', required=False, no_log=True,
                            fallback=(env_fallback, ['BYTEPLUS_SECRET_KEY'])),
            region=dict(type='str', default='ap-southeast-1'),
            role_name=dict(type='str', required=True),
            trust_policy_document=dict(
                type='raw', required=False, no_log=True),
            description=dict(type='str', required=False),
            max_session_duration=dict(type='int', required=False),
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
