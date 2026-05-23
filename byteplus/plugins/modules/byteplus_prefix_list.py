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
module: byteplus_prefix_list
version_added: "1.0.0"
short_description: Manage BytePlus VPC prefix lists
description:
  - Create, modify, and delete BytePlus VPC prefix lists.
  - Optionally reconciles the entry set (CIDRs in the list) so a single
    playbook invocation can declare the desired membership.
  - When O(entries) is supplied, the module reconciles the list. By default
    it only adds missing CIDRs; set O(purge_entries=true) to also remove
    CIDRs that exist on the server but are not in O(entries).
  - C(ip_version) and tags can only be set at create time; changing them
    later is not supported by the API.
options:
  state:
    description: Desired state.
    type: str
    default: present
    choices: [present, absent]
  prefix_list_id:
    description: ID of an existing prefix list. Required for C(absent) when O(prefix_list_name) is not given.
    type: str
  prefix_list_name:
    description:
      - Display name. Combined with O(project_name) for lookup.
      - Names are not unique server-side; set O(project_name) to scope the lookup.
    type: str
  description:
    description: Free-form description.
    type: str
  ip_version:
    description: Address family. Only honored at create time.
    type: str
    choices: [IPv4, IPv6]
    default: IPv4
  max_entries:
    description:
      - Maximum number of entries the prefix list can hold. Required when creating.
      - Can be increased (but not decreased) on existing lists via ModifyPrefixList.
    type: int
  entries:
    description:
      - List of CIDR entries to ensure are present on the prefix list.
      - Each item is a dict with C(cidr) (required) and optional C(description).
    type: list
    elements: dict
    suboptions:
      cidr:
        description: CIDR block (e.g. C(10.0.0.0/16) or C(2001:db8::/32)).
        type: str
        required: true
      description:
        description: Free-form per-entry description.
        type: str
  purge_entries:
    description:
      - When C(true) and O(entries) is provided, any entry on the server
        that is NOT in O(entries) will be removed so the membership
        converges exactly to O(entries).
      - When C(false) (the default), the module only adds/updates;
        nothing is removed.
    type: bool
    default: false
  project_name:
    description: BytePlus project, also used to narrow lookups.
    type: str
  tags:
    description: Tag list as C({key, value}) dicts. Only applied at create time.
    type: list
    elements: dict
  client_token:
    description: Idempotency token forwarded to CreatePrefixList.
    type: str
  access_key:
    description: BytePlus access key. Falls back to C(BYTEPLUS_ACCESS_KEY).
    type: str
    no_log: true
  secret_key:
    description: BytePlus secret key. Falls back to C(BYTEPLUS_SECRET_KEY).
    type: str
    no_log: true
  session_token:
    description: Optional STS session token.
    type: str
    no_log: true
  region:
    description: API region. Falls back to C(BYTEPLUS_REGION), then C(ap-southeast-1).
    type: str
requirements:
  - byteplus-python-sdk-v2 >= 3.0.44
author:
  - BytePlus
'''

EXAMPLES = r'''
- name: Create a prefix list for office IP whitelisting
  fardani235.byteplus.byteplus_prefix_list:
    prefix_list_name: office-egress
    description: Corporate network egress IPs
    max_entries: 50
    project_name: prod
    entries:
      - cidr: 203.0.113.0/24
        description: HQ Singapore
      - cidr: 198.51.100.0/24
        description: Branch Tokyo

- name: Add a new office network to an existing list (no removals)
  fardani235.byteplus.byteplus_prefix_list:
    prefix_list_name: office-egress
    project_name: prod
    entries:
      - cidr: 192.0.2.0/24
        description: New branch Sydney

- name: Reconcile membership exactly (removes anything not listed)
  fardani235.byteplus.byteplus_prefix_list:
    prefix_list_name: office-egress
    project_name: prod
    purge_entries: true
    entries:
      - cidr: 203.0.113.0/24
      - cidr: 192.0.2.0/24

- name: Reference the prefix list from a security group rule
  fardani235.byteplus.byteplus_security_group_rule:
    security_group_id: sg-web
    direction: ingress
    protocol: tcp
    port_start: 443
    port_end: 443
    prefix_list_id: "{{ pl.prefix_list.prefix_list_id }}"

- name: Delete a prefix list
  fardani235.byteplus.byteplus_prefix_list:
    prefix_list_name: legacy-vpn-peers
    project_name: prod
    state: absent
'''

RETURN = r'''
prefix_list:
  description: PrefixList record after the change. None when state=absent and the PL was deleted.
  type: dict
  returned: when state=present
entries:
  description: Final list of entries after reconciliation, when O(entries) was supplied.
  type: list
  elements: dict
  returned: when entries was supplied
changed:
  description: Whether any change was made.
  type: bool
  returned: always
'''

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.fardani235.byteplus.plugins.module_utils.vpc_common import (
    VPCClient,
    diff_prefix_list_entries,
    resolve_credentials,
)


def _resolve_prefix_list(module, client):
    pl_id = module.params.get('prefix_list_id')
    if pl_id:
        return client.get_prefix_list(pl_id), pl_id
    name = module.params.get('prefix_list_name')
    if name:
        try:
            pl = client.find_prefix_list_by_name(
                name, project_name=module.params.get('project_name'))
        except Exception as e:
            module.fail_json(msg=str(e))
            return None, None  # unreachable
        if pl:
            return pl, pl.get('prefix_list_id') or pl.get('PrefixListId')
    return None, None


def _create_kwargs(p):
    kwargs = {
        'prefix_list_name': p.get('prefix_list_name'),
        'max_entries': p['max_entries'],
        'ip_version': p['ip_version'],
    }
    for k in ('description', 'project_name', 'tags', 'client_token'):
        v = p.get(k)
        if v is not None:
            kwargs[k] = v
    if p.get('entries'):
        kwargs['prefix_list_entries'] = p['entries']
    return kwargs


def _attribute_drift(p, existing):
    """Drift on mutable attributes that ModifyPrefixList accepts.

    The API allows updating prefix_list_name, description, and max_entries.
    ip_version and tags are immutable post-create — we don't try.
    """
    out = {}
    new_name = p.get('prefix_list_name')
    if new_name and new_name != (
            existing.get('prefix_list_name') or existing.get('PrefixListName')):
        out['prefix_list_name'] = new_name
    new_desc = p.get('description')
    if new_desc is not None and new_desc != (
            existing.get('description') or existing.get('Description') or ''):
        out['description'] = new_desc
    new_max = p.get('max_entries')
    if new_max is not None and new_max != (
            existing.get('max_entries') or existing.get('MaxEntries')):
        out['max_entries'] = new_max
    return out


def _reconcile_entries(client, pl_id, desired, purge, check_mode):
    """Apply entry diff via ModifyPrefixList. Returns (changed, final_entries).

    BytePlus's modify-prefix-list API allows add and remove in the same call,
    but description-only updates require re-adding the CIDR. Description-only
    updates are bundled into the add list.
    """
    existing = client.describe_prefix_list_entries(pl_id)
    to_add, to_remove, to_update_desc = diff_prefix_list_entries(
        existing, desired, purge=purge)

    # Treat description-only updates as adds; the API merges them in place.
    adds = to_add + to_update_desc
    if not adds and not to_remove:
        return False, existing

    if check_mode:
        # Simulate by mutating a local copy.
        existing_map = {e.get('cidr') or e.get('Cidr'): e for e in existing}
        for e in to_remove:
            existing_map.pop(e['cidr'], None)
        for e in adds:
            existing_map[e['cidr']] = {'cidr': e['cidr'],
                                        'description': e.get('description', '')}
        return True, list(existing_map.values())

    client.modify_prefix_list(pl_id, add_entries=adds, remove_entries=to_remove)
    return True, client.describe_prefix_list_entries(pl_id)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(type='str', default='present', choices=['present', 'absent']),
            prefix_list_id=dict(type='str'),
            prefix_list_name=dict(type='str'),
            description=dict(type='str'),
            ip_version=dict(type='str', default='IPv4', choices=['IPv4', 'IPv6']),
            max_entries=dict(type='int'),
            entries=dict(type='list', elements='dict'),
            purge_entries=dict(type='bool', default=False),
            project_name=dict(type='str'),
            tags=dict(type='list', elements='dict'),
            client_token=dict(type='str'),
            access_key=dict(type='str', no_log=True),
            secret_key=dict(type='str', no_log=True),
            session_token=dict(type='str', no_log=True),
            region=dict(type='str'),
        ),
        supports_check_mode=True,
    )

    ak, sk, region, st = resolve_credentials(module)
    try:
        client = VPCClient(ak, sk, region, session_token=st)
    except Exception as e:
        module.fail_json(msg="Failed to initialize VPC client: {}".format(str(e)))

    state = module.params['state']
    existing, pl_id = _resolve_prefix_list(module, client)

    if state == 'present':
        if existing:
            changed = False
            drift = _attribute_drift(module.params, existing)
            if drift:
                if module.check_mode:
                    module.exit_json(changed=True, prefix_list=existing,
                                     msg="Would modify prefix list {}".format(pl_id))
                try:
                    client.modify_prefix_list(pl_id, **drift)
                except Exception as e:
                    module.fail_json(msg=str(e), prefix_list_id=pl_id)
                changed = True
                existing = client.get_prefix_list(pl_id)

            final_entries = None
            if module.params.get('entries') is not None:
                try:
                    entries_changed, final_entries = _reconcile_entries(
                        client, pl_id,
                        module.params['entries'],
                        module.params['purge_entries'],
                        module.check_mode)
                except (Exception, ValueError) as e:
                    module.fail_json(msg=str(e), prefix_list_id=pl_id)
                    return  # unreachable
                changed = changed or entries_changed

            result = {'changed': changed, 'prefix_list': existing}
            if final_entries is not None:
                result['entries'] = final_entries
            module.exit_json(**result)

        # Create path.
        if not module.params.get('max_entries'):
            module.fail_json(msg="max_entries is required when creating a prefix list")
        if module.check_mode:
            module.exit_json(changed=True, prefix_list=None,
                             msg="Would create prefix list")
        try:
            result = client.create_prefix_list(**_create_kwargs(module.params))
        except Exception as e:
            module.fail_json(msg=str(e))
            return  # unreachable
        new_id = result.get('prefix_list_id') or result.get('PrefixListId')
        new_pl = client.get_prefix_list(new_id)
        response = {'changed': True, 'prefix_list': new_pl}
        if module.params.get('entries') is not None:
            response['entries'] = client.describe_prefix_list_entries(new_id)
        module.exit_json(**response)

    # state == 'absent'
    if not existing:
        module.exit_json(changed=False, prefix_list=None,
                         msg="Prefix list not found; nothing to delete")
    if module.check_mode:
        module.exit_json(changed=True,
                         msg="Would delete prefix list {}".format(pl_id))
    try:
        client.delete_prefix_list(pl_id)
    except Exception as e:
        module.fail_json(msg=str(e), prefix_list_id=pl_id)
    module.exit_json(changed=True, prefix_list=None)


if __name__ == '__main__':
    main()
