#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright BytePlus Inc.
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type


DOCUMENTATION = r'''
---
module: byteplus_security_group
version_added: "1.0.0"
short_description: Manage BytePlus security groups
description:
  - Create and delete BytePlus VPC security groups.
  - Manages the SG itself; rule authorization/revocation is out of scope
    for this module (see C(byteplus_security_group_rule) in a future release).
  - Name and description changes are applied via ModifySecurityGroupAttributes.
options:
  state:
    description: Desired state.
    type: str
    default: present
    choices: [present, absent]
  security_group_id:
    description: ID of an existing SG. Required for C(absent) when O(security_group_name) is not given.
    type: str
  security_group_name:
    description:
      - Display name. Combined with O(vpc_id) for lookup.
      - Names are not unique across BytePlus, but the module enforces
        uniqueness within a VPC for lookups.
    type: str
  vpc_id:
    description: VPC the SG belongs to. Required when creating, and when looking up by name.
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
    description: Idempotency token forwarded to CreateSecurityGroup.
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
- name: Create a security group
  byteplus.cloud.byteplus_security_group:
    security_group_name: web-tier
    vpc_id: vpc-2d6jskeu1exxw58ozfd5xyz
    description: Allows HTTPS in
    project_name: prod

- name: Delete an SG by name
  byteplus.cloud.byteplus_security_group:
    security_group_name: web-tier
    vpc_id: vpc-2d6jskeu1exxw58ozfd5xyz
    state: absent
'''

RETURN = r'''
security_group:
  description: Security group record. None when state=absent and the SG was deleted.
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


def _resolve_sg(module, client):
    sg_id = module.params.get('security_group_id')
    if sg_id:
        return client.get_security_group(sg_id), sg_id
    name = module.params.get('security_group_name')
    vpc_id = module.params.get('vpc_id')
    if name and vpc_id:
        try:
            sg = client.find_security_group_by_name(
                name, vpc_id=vpc_id,
                project_name=module.params.get('project_name'))
        except Exception as e:
            module.fail_json(msg=str(e))
            return None, None  # unreachable
        if sg:
            return sg, sg.get('security_group_id') or sg.get('SecurityGroupId')
    return None, None


def _create_kwargs(p):
    kwargs = {'vpc_id': p['vpc_id']}
    for k in ('security_group_name', 'description', 'project_name',
              'tags', 'client_token'):
        v = p.get(k)
        if v is not None:
            kwargs[k] = v
    return kwargs


def _drift_modify_kwargs(p, existing):
    out = {}
    new_name = p.get('security_group_name')
    if new_name and new_name != (
            existing.get('security_group_name') or existing.get('SecurityGroupName')):
        out['security_group_name'] = new_name
    new_desc = p.get('description')
    if new_desc is not None and new_desc != (
            existing.get('description') or existing.get('Description') or ''):
        out['description'] = new_desc
    return out or None


def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(type='str', default='present', choices=['present', 'absent']),
            security_group_id=dict(type='str'),
            security_group_name=dict(type='str'),
            vpc_id=dict(type='str'),
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
    existing, sg_id = _resolve_sg(module, client)

    if state == 'present':
        if existing:
            modify = _drift_modify_kwargs(module.params, existing)
            if not modify:
                module.exit_json(changed=False, security_group=existing)
            if module.check_mode:
                module.exit_json(changed=True, security_group=existing,
                                 msg="Would modify security group {}".format(sg_id))
            try:
                client.modify_security_group(sg_id, **modify)
            except Exception as e:
                module.fail_json(msg=str(e), security_group_id=sg_id)
            module.exit_json(changed=True,
                             security_group=client.get_security_group(sg_id))

        if not module.params.get('vpc_id'):
            module.fail_json(msg="vpc_id is required when creating a security group")
        if module.check_mode:
            module.exit_json(changed=True, security_group=None,
                             msg="Would create security group")
        try:
            result = client.create_security_group(**_create_kwargs(module.params))
        except Exception as e:
            module.fail_json(msg=str(e))
            return  # unreachable
        new_id = result.get('security_group_id') or result.get('SecurityGroupId')
        module.exit_json(changed=True,
                         security_group=client.get_security_group(new_id))

    # state == 'absent'
    if not existing:
        module.exit_json(changed=False, security_group=None,
                         msg="Security group not found; nothing to delete")
    if module.check_mode:
        module.exit_json(changed=True,
                         msg="Would delete security group {}".format(sg_id))
    try:
        client.delete_security_group(sg_id)
    except Exception as e:
        module.fail_json(msg=str(e), security_group_id=sg_id)
    module.exit_json(changed=True, security_group=None)


if __name__ == '__main__':
    main()
