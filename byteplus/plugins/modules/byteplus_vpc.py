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
module: byteplus_vpc
version_added: "1.0.0"
short_description: Manage BytePlus VPCs
description:
  - Create and delete BytePlus VPCs.
  - Description and DNS server changes on existing VPCs are applied via
    ModifyVpcAttributes; CIDR block and IPv6 settings are immutable after creation.
options:
  state:
    description:
      - C(present) ensures the VPC exists; creates it if missing.
      - C(absent) deletes the VPC. The VPC must already be empty (no subnets,
        no attached instances) — the API rejects deletion of non-empty VPCs.
    type: str
    default: present
    choices: [present, absent]
  vpc_id:
    description: ID of an existing VPC. Required for C(absent) when O(vpc_name) is not given.
    type: str
  vpc_name:
    description:
      - Display name. Used to look up a VPC when O(vpc_id) is not provided.
      - Names are not unique server-side; set O(project_name) to scope the lookup
        if the same name is used across BytePlus projects.
    type: str
  cidr_block:
    description: IPv4 CIDR block, e.g. C(172.16.0.0/16). Required when creating.
    type: str
  description:
    description: Free-form description.
    type: str
  dns_servers:
    description: List of DNS server IPs (max 4) the VPC will hand to instances.
    type: list
    elements: str
  enable_ipv6:
    description: Enable IPv6 on the VPC.
    type: bool
  ipv6_cidr_block:
    description: User-supplied IPv6 CIDR (otherwise BytePlus assigns one).
    type: str
  project_name:
    description:
      - BytePlus project to place the VPC in. Also used to narrow O(vpc_name) lookup.
    type: str
  tags:
    description: Tag list as C({key, value}) dicts.
    type: list
    elements: dict
  client_token:
    description: Idempotency token forwarded to CreateVpc.
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
- name: Create a VPC
  fardani235.byteplus.byteplus_vpc:
    vpc_name: prod-vpc
    cidr_block: 172.16.0.0/16
    project_name: prod
    tags:
      - key: env
        value: prod

- name: Delete a VPC by name
  fardani235.byteplus.byteplus_vpc:
    vpc_name: scratch-vpc
    project_name: dev
    state: absent
'''

RETURN = r'''
vpc:
  description: VPC record. None when state=absent and the VPC was deleted.
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


def _resolve_vpc(module, client):
    """Return (vpc_dict_or_None, vpc_id_or_None)."""
    vpc_id = module.params.get('vpc_id')
    name = module.params.get('vpc_name')
    if vpc_id:
        return client.get_vpc(vpc_id), vpc_id
    if name:
        try:
            v = client.find_vpc_by_name(name,
                                        project_name=module.params.get('project_name'))
        except Exception as e:
            module.fail_json(msg=str(e))
            return None, None  # unreachable
        if v:
            return v, v.get('vpc_id') or v.get('VpcId')
    return None, None


def _create_kwargs(p):
    kwargs = {'cidr_block': p['cidr_block']}
    for k in ('vpc_name', 'description', 'dns_servers', 'enable_ipv6',
              'ipv6_cidr_block', 'project_name', 'tags', 'client_token'):
        v = p.get(k)
        if v is not None:
            kwargs[k] = v
    return kwargs


def _drift_modify_kwargs(p, existing):
    """Return kwargs for ModifyVpcAttributes if mutable fields drift, else None.

    Only attributes that BytePlus allows to be changed post-create are
    diffed here. CIDR and IPv6 settings are immutable — we won't try.
    """
    out = {}
    new_name = p.get('vpc_name')
    if new_name and new_name != (existing.get('vpc_name') or existing.get('VpcName')):
        out['vpc_name'] = new_name
    new_desc = p.get('description')
    if new_desc is not None and new_desc != (
            existing.get('description') or existing.get('Description') or ''):
        out['description'] = new_desc
    new_dns = p.get('dns_servers')
    if new_dns is not None:
        cur_dns = existing.get('dns_servers') or existing.get('DnsServers') or []
        if list(new_dns) != list(cur_dns):
            out['dns_servers'] = new_dns
    return out or None


def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(type='str', default='present', choices=['present', 'absent']),
            vpc_id=dict(type='str'),
            vpc_name=dict(type='str'),
            cidr_block=dict(type='str'),
            description=dict(type='str'),
            dns_servers=dict(type='list', elements='str'),
            enable_ipv6=dict(type='bool'),
            ipv6_cidr_block=dict(type='str'),
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
    existing, vpc_id = _resolve_vpc(module, client)

    if state == 'present':
        if existing:
            modify = _drift_modify_kwargs(module.params, existing)
            if not modify:
                module.exit_json(changed=False, vpc=existing)
            if module.check_mode:
                module.exit_json(changed=True, vpc=existing,
                                 msg="Would modify VPC {}".format(vpc_id))
            try:
                client.modify_vpc(vpc_id, **modify)
            except Exception as e:
                module.fail_json(msg=str(e), vpc_id=vpc_id)
            module.exit_json(changed=True, vpc=client.get_vpc(vpc_id))

        if not module.params.get('cidr_block'):
            module.fail_json(msg="cidr_block is required when creating a VPC")
        if module.check_mode:
            module.exit_json(changed=True, vpc=None, msg="Would create VPC")
        try:
            result = client.create_vpc(**_create_kwargs(module.params))
        except Exception as e:
            module.fail_json(msg=str(e))
            return  # unreachable
        new_id = result.get('vpc_id') or result.get('VpcId')
        module.exit_json(changed=True, vpc=client.get_vpc(new_id))

    # state == 'absent'
    if not existing:
        module.exit_json(changed=False, vpc=None,
                         msg="VPC not found; nothing to delete")
    if module.check_mode:
        module.exit_json(changed=True, msg="Would delete VPC {}".format(vpc_id))
    try:
        client.delete_vpc(vpc_id)
    except Exception as e:
        module.fail_json(msg=str(e), vpc_id=vpc_id)
    module.exit_json(changed=True, vpc=None)


if __name__ == '__main__':
    main()
