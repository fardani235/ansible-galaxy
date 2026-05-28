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
module: byteplus_iam_policy
version_added: "1.2.0"
short_description: Manage customer-managed BytePlus IAM policies
description:
  - Create, update, and delete customer-managed IAM policies.
  - This module refuses to touch BytePlus system policies — those are
    managed by BytePlus and changing them by name would either no-op
    silently or break in surprising ways. Use C(byteplus_iam_policy_info)
    to inspect system policies and C(byteplus_iam_policy_attachment)
    to attach them.
  - Policy documents are compared after parse-then-key-sort, so
    re-running with a syntactically different but semantically identical
    JSON document does not register as a change.
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
    description: Policy name. Primary key.
    type: str
    required: true
  policy_document:
    description:
      - The policy body. Accepts either a dict (Ansible-native, preferred)
        or a JSON string. Required when O(state=present).
    type: raw
    required: false
  description:
    description: Free-form description.
    type: str
    required: false
  state:
    description:
      - C(present) creates or updates the policy.
      - C(absent) deletes it. The server refuses to delete policies that
        are still attached to users or roles; that error is surfaced
        verbatim (no auto-detach).
    type: str
    default: present
    choices: [present, absent]
requirements:
  - byteplus-python-sdk-v2 >= 3.0.44
'''

EXAMPLES = r'''
- name: Create a custom read-only policy
  fardani235.byteplus.byteplus_iam_policy:
    policy_name: tos-read-only
    description: "Read TOS buckets and objects only"
    policy_document:
      Statement:
        - Effect: Allow
          Action:
            - tos:GetObject
            - tos:ListBucket
          Resource: "*"
    state: present

- name: Delete the policy (must have no attachments)
  fardani235.byteplus.byteplus_iam_policy:
    policy_name: tos-read-only
    state: absent
'''

RETURN = r'''
policy:
  description: Full policy dict from BytePlus IAM, including the canonical document.
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


# A BytePlus IAM policy carries a PolicyType field on the GetPolicy
# response — 'Custom' for customer-managed, 'System' for BytePlus-managed.
_SYSTEM_TYPE = 'System'


def _wire_document(doc):
    """The BytePlus API expects PolicyDocument as a JSON STRING, not
    a structured object. Accept either input shape (dict OR string) and
    return what the wire wants."""
    if doc is None:
        return None
    if isinstance(doc, str):
        # Validate it parses — the server's error for malformed JSON is
        # blunt, and the operator deserves the parse error inline.
        try:
            json.loads(doc)
        except ValueError as e:
            raise ValueError(
                "policy_document is not valid JSON: {}".format(e))
        return doc
    return json.dumps(doc)


def _ensure_present(module, client):
    p = module.params
    if p['policy_document'] is None:
        module.fail_json(
            msg="policy_document is required when state=present")
    try:
        wire_doc = _wire_document(p['policy_document'])
        new_canon = canonicalize_policy_document(p['policy_document'])
    except (ValueError, TypeError) as e:
        module.fail_json(msg=str(e))

    existing = client.get_policy(p['policy_name'], policy_type='Custom')

    if existing is None:
        if module.check_mode:
            module.exit_json(
                changed=True,
                msg="Would create policy {}".format(p['policy_name']))
        client.create_policy(
            policy_name=p['policy_name'],
            policy_document=wire_doc,
            description=p['description'],
        )
        policy = client.get_policy(
            p['policy_name'], policy_type='Custom') or {}
        module.exit_json(changed=True, policy=policy)

    # Bail out before any mutation if the operator accidentally aimed
    # at a system policy. (GetPolicy with PolicyType=Custom should not
    # have returned one, but the API has surprised us before.)
    if existing.get('PolicyType') == _SYSTEM_TYPE:
        module.fail_json(
            msg=("Refusing to manage system policy {!r}. "
                 "byteplus_iam_policy manages customer-managed policies "
                 "only; use byteplus_iam_policy_attachment to attach a "
                 "system policy.").format(p['policy_name']))

    server_doc = existing.get('PolicyDocument')
    try:
        existing_canon = (
            canonicalize_policy_document(server_doc)
            if server_doc is not None else None)
    except (ValueError, TypeError):
        # If the server's document is somehow unparseable, treat as
        # drift and re-push the caller's canonical form rather than
        # crashing the play.
        existing_canon = None

    drift_doc = existing_canon != new_canon
    drift_desc = (p['description'] is not None
                  and existing.get('Description') != p['description'])

    if not drift_doc and not drift_desc:
        module.exit_json(changed=False, policy=existing)

    if module.check_mode:
        changed_keys = []
        if drift_doc:
            changed_keys.append('policy_document')
        if drift_desc:
            changed_keys.append('description')
        module.exit_json(
            changed=True,
            msg="Would update policy {}: {}".format(
                p['policy_name'], changed_keys))

    client.update_policy(
        policy_name=p['policy_name'],
        policy_document=wire_doc if drift_doc else None,
        description=p['description'] if drift_desc else None,
    )
    policy = client.get_policy(p['policy_name'], policy_type='Custom') or {}
    module.exit_json(changed=True, policy=policy)


def _ensure_absent(module, client):
    p = module.params
    existing = client.get_policy(p['policy_name'], policy_type='Custom')
    if existing is None:
        module.exit_json(changed=False)
    if existing.get('PolicyType') == _SYSTEM_TYPE:
        module.fail_json(
            msg=("Refusing to delete system policy {!r}").format(
                p['policy_name']))
    if module.check_mode:
        module.exit_json(
            changed=True,
            msg="Would delete policy {}".format(p['policy_name']))
    client.delete_policy(p['policy_name'])
    module.exit_json(changed=True)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            access_key=dict(type='str', required=False,
                            fallback=(env_fallback, ['BYTEPLUS_ACCESS_KEY'])),
            secret_key=dict(type='str', required=False, no_log=True,
                            fallback=(env_fallback, ['BYTEPLUS_SECRET_KEY'])),
            region=dict(type='str', default='ap-southeast-1'),
            policy_name=dict(type='str', required=True),
            # `raw` so callers can hand us a dict OR a JSON string —
            # both are common in real playbooks.
            policy_document=dict(type='raw', required=False, no_log=True),
            description=dict(type='str', required=False),
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
