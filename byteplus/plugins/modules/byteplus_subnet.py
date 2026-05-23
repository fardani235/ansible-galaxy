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
module: byteplus_subnet
version_added: "1.0.0"
short_description: Manage BytePlus subnets
description:
  - Create and delete subnets in a BytePlus VPC.
  - Name and description changes are applied via ModifySubnetAttributes;
    CIDR and zone are immutable.
options:
  state:
    description: Desired state.
    type: str
    default: present
    choices: [present, absent]
  subnet_id:
    description: ID of an existing subnet. Required for C(absent) when O(subnet_name) is not given.
    type: str
  subnet_name:
    description:
      - Display name. Used with O(vpc_id) to look up an existing subnet.
      - Names are not unique across BytePlus, but the module enforces uniqueness within a VPC.
    type: str
  vpc_id:
    description: VPC the subnet belongs to. Required when creating, and when looking up by O(subnet_name).
    type: str
  zone_id:
    description: Availability zone. Required when creating.
    type: str
  cidr_block:
    description: IPv4 CIDR within the parent VPC. Required when creating.
    type: str
  ipv6_cidr_block:
    description: IPv6 sub-CIDR (e.g. C(0)–C(255) suffix for the parent VPC IPv6 block).
    type: str
  description:
    description: Free-form description.
    type: str
  project_name:
    description: BytePlus project, used to narrow lookups.
    type: str
  tags:
    description: Tag list as C({key, value}) dicts.
    type: list
    elements: dict
  client_token:
    description: Idempotency token forwarded to CreateSubnet.
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
- name: Create a subnet
  fardani235.byteplus.byteplus_subnet:
    subnet_name: web-tier-a
    vpc_id: vpc-2d6jskeu1exxw58ozfd5xyz
    zone_id: ap-southeast-1a
    cidr_block: 172.16.1.0/24

- name: Delete a subnet by name
  fardani235.byteplus.byteplus_subnet:
    subnet_name: web-tier-a
    vpc_id: vpc-2d6jskeu1exxw58ozfd5xyz
    state: absent
'''

RETURN = r'''
subnet:
  description: Subnet record. None when state=absent and the subnet was deleted.
  type: dict
  returned: when state=present
changed:
  description: Whether any change was made.
  type: bool
  returned: always
'''

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.fardani235.byteplus.plugins.module_utils.vpc_common import (
    VPCClient,
    resolve_credentials,
)


def _resolve_subnet(module, client):
    subnet_id = module.params.get('subnet_id')
    if subnet_id:
        return client.get_subnet(subnet_id), subnet_id
    name = module.params.get('subnet_name')
    vpc_id = module.params.get('vpc_id')
    if name and vpc_id:
        try:
            s = client.find_subnet_by_name(
                name, vpc_id=vpc_id,
                project_name=module.params.get('project_name'))
        except Exception as e:
            module.fail_json(msg=str(e))
            return None, None  # unreachable
        if s:
            return s, s.get('subnet_id') or s.get('SubnetId')
    return None, None


def _create_kwargs(p):
    kwargs = {
        'vpc_id': p['vpc_id'],
        'zone_id': p['zone_id'],
        'cidr_block': p['cidr_block'],
    }
    for k in ('subnet_name', 'description', 'ipv6_cidr_block', 'tags', 'client_token'):
        v = p.get(k)
        if v is not None:
            kwargs[k] = v
    return kwargs


def _drift_modify_kwargs(p, existing):
    out = {}
    new_name = p.get('subnet_name')
    if new_name and new_name != (existing.get('subnet_name') or existing.get('SubnetName')):
        out['subnet_name'] = new_name
    new_desc = p.get('description')
    if new_desc is not None and new_desc != (
            existing.get('description') or existing.get('Description') or ''):
        out['description'] = new_desc
    return out or None


def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(type='str', default='present', choices=['present', 'absent']),
            subnet_id=dict(type='str'),
            subnet_name=dict(type='str'),
            vpc_id=dict(type='str'),
            zone_id=dict(type='str'),
            cidr_block=dict(type='str'),
            ipv6_cidr_block=dict(type='str'),
            description=dict(type='str'),
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
    existing, subnet_id = _resolve_subnet(module, client)

    if state == 'present':
        if existing:
            modify = _drift_modify_kwargs(module.params, existing)
            if not modify:
                module.exit_json(changed=False, subnet=existing)
            if module.check_mode:
                module.exit_json(changed=True, subnet=existing,
                                 msg="Would modify subnet {}".format(subnet_id))
            try:
                client.modify_subnet(subnet_id, **modify)
            except Exception as e:
                module.fail_json(msg=str(e), subnet_id=subnet_id)
            module.exit_json(changed=True, subnet=client.get_subnet(subnet_id))

        missing = [k for k in ('vpc_id', 'zone_id', 'cidr_block')
                   if not module.params.get(k)]
        if missing:
            module.fail_json(
                msg="Missing required params for creating a subnet: {}".format(
                    ', '.join(missing)))
        if module.check_mode:
            module.exit_json(changed=True, subnet=None, msg="Would create subnet")
        try:
            result = client.create_subnet(**_create_kwargs(module.params))
        except Exception as e:
            module.fail_json(msg=str(e))
            return  # unreachable
        new_id = result.get('subnet_id') or result.get('SubnetId')
        module.exit_json(changed=True, subnet=client.get_subnet(new_id))

    # state == 'absent'
    if not existing:
        module.exit_json(changed=False, subnet=None,
                         msg="Subnet not found; nothing to delete")
    if module.check_mode:
        module.exit_json(changed=True, msg="Would delete subnet {}".format(subnet_id))
    try:
        client.delete_subnet(subnet_id)
    except Exception as e:
        module.fail_json(msg=str(e), subnet_id=subnet_id)
    module.exit_json(changed=True, subnet=None)


if __name__ == '__main__':
    main()
