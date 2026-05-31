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
module: byteplus_route_table
version_added: "1.3.0"
short_description: Manage BytePlus VPC custom route tables
description:
  - Create, modify, and delete custom (user-managed) BytePlus VPC route tables.
  - Optionally synchronises the table's subnet associations via
    O(associated_subnet_ids). When the parameter is omitted, associations are
    left untouched — supplying the parameter takes ownership of the full set.
  - The VPC-provided default route table (C(RouteTableType=System)) is
    rejected on both C(present)-mode attribute changes and C(absent). Routes
    can still be added to it via M(fardani235.byteplus.byteplus_route_entry).
options:
  state:
    description:
      - C(present) creates the route table if missing; otherwise reconciles
        mutable attributes (name, description) and associations.
      - C(absent) deletes the route table. BytePlus refuses deletion while
        custom entries or associations remain — surface the API error.
    type: str
    default: present
    choices: [present, absent]
  route_table_id:
    description: ID of an existing route table. Used for direct lookup.
    type: str
  route_table_name:
    description:
      - Display name. Used together with O(vpc_id) to look up an existing
        route table when O(route_table_id) is not supplied.
    type: str
  vpc_id:
    description:
      - ID of the VPC the route table belongs to. Required when creating, and
        required when looking up by name.
    type: str
  description:
    description: Free-form description.
    type: str
  associated_subnet_ids:
    description:
      - Subnets that should be associated with this route table. When set,
        the module reconciles the current set to exactly this list
        (associates missing, disassociates extras).
      - Omit to leave the existing associations untouched.
    type: list
    elements: str
  project_name:
    description:
      - BytePlus project to place the route table in. Also narrows by-name
        lookup when the same name is used across projects.
    type: str
  tags:
    description: Tag list as C({key, value}) dicts. Applied only on create.
    type: list
    elements: dict
  client_token:
    description: Idempotency token forwarded to CreateRouteTable.
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
- name: Create a route table and bind it to two subnets
  fardani235.byteplus.byteplus_route_table:
    route_table_name: prod-app
    vpc_id: vpc-xxx
    description: Custom routes for the app tier
    associated_subnet_ids:
      - subnet-aaa
      - subnet-bbb
    project_name: prod

- name: Rename a route table without touching its associations
  fardani235.byteplus.byteplus_route_table:
    route_table_id: vtb-yyy
    route_table_name: prod-app-v2

- name: Delete a route table by name
  fardani235.byteplus.byteplus_route_table:
    route_table_name: scratch
    vpc_id: vpc-xxx
    state: absent
'''

RETURN = r'''
route_table:
  description: Route table record. None when state=absent and the table was deleted.
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
    associated_subnet_ids,
    diff_route_table_associations,
    is_system_route_table,
    resolve_credentials,
)


def _resolve(module, client):
    """Return (rt_dict_or_None, route_table_id_or_None)."""
    rid = module.params.get('route_table_id')
    name = module.params.get('route_table_name')
    if rid:
        return client.get_route_table(rid), rid
    if name:
        vpc_id = module.params.get('vpc_id')
        if not vpc_id:
            module.fail_json(
                msg="vpc_id is required when looking up a route table by name")
        try:
            r = client.find_route_table_by_name(
                name, vpc_id,
                project_name=module.params.get('project_name'))
        except Exception as e:
            module.fail_json(msg=str(e))
            return None, None  # unreachable
        if r:
            return r, r.get('route_table_id') or r.get('RouteTableId')
    return None, None


def _create_kwargs(p):
    kwargs = {'vpc_id': p['vpc_id']}
    for k in ('route_table_name', 'description', 'project_name',
              'tags', 'client_token'):
        v = p.get(k)
        if v is not None:
            kwargs[k] = v
    return kwargs


def _attr_modify_kwargs(p, existing):
    """Return kwargs for ModifyRouteTableAttributes if name/description drift.

    Associations are NOT diffed here — they're a separate set of API calls
    handled by _reconcile_associations.
    """
    out = {}
    new_name = p.get('route_table_name')
    if new_name and new_name != (
            existing.get('route_table_name') or existing.get('RouteTableName')):
        out['route_table_name'] = new_name
    new_desc = p.get('description')
    if new_desc is not None and new_desc != (
            existing.get('description') or existing.get('Description') or ''):
        out['description'] = new_desc
    return out or None


def _reconcile_associations(module, client, route_table_id, existing, check_mode):
    """Apply associated_subnet_ids if the user provided it.

    Returns True if any association API call ran (or would have, in check mode).
    """
    desired = module.params.get('associated_subnet_ids')
    if desired is None:
        return False  # not under management
    current = associated_subnet_ids(existing)
    to_add, to_remove = diff_route_table_associations(current, desired)
    if not to_add and not to_remove:
        return False
    if check_mode:
        return True
    for sid in to_add:
        client.associate_route_table(route_table_id, sid)
    for sid in to_remove:
        client.disassociate_route_table(route_table_id, sid)
    return True


def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(type='str', default='present', choices=['present', 'absent']),
            route_table_id=dict(type='str'),
            route_table_name=dict(type='str'),
            vpc_id=dict(type='str'),
            description=dict(type='str'),
            associated_subnet_ids=dict(type='list', elements='str'),
            project_name=dict(type='str'),
            tags=dict(type='list', elements='dict'),
            client_token=dict(type='str'),
            access_key=dict(type='str', no_log=True),
            secret_key=dict(type='str', no_log=True),
            session_token=dict(type='str', no_log=True),
            region=dict(type='str'),
        ),
        supports_check_mode=True,
        required_one_of=[('route_table_id', 'route_table_name')],
    )

    ak, sk, region, st = resolve_credentials(module)
    try:
        client = VPCClient(ak, sk, region, session_token=st)
    except Exception as e:
        module.fail_json(msg="Failed to initialize VPC client: {}".format(str(e)))

    state = module.params['state']
    existing, rt_id = _resolve(module, client)

    if state == 'present':
        if existing:
            if is_system_route_table(existing):
                # Refuse name/description renames or association rewrites
                # against the default table — these are almost always
                # mistakes and BytePlus's own error messages are unhelpful.
                attr_drift = _attr_modify_kwargs(module.params, existing)
                assoc_requested = module.params.get('associated_subnet_ids') is not None
                if attr_drift or assoc_requested:
                    module.fail_json(
                        msg=("refusing to modify system route table {} for VPC {}; "
                             "use byteplus_route_entry to add routes to the default table"
                             .format(rt_id,
                                     existing.get('vpc_id') or existing.get('VpcId'))),
                        route_table_id=rt_id)
                module.exit_json(changed=False, route_table=existing)

            changed = False
            modify = _attr_modify_kwargs(module.params, existing)
            if modify:
                if module.check_mode:
                    changed = True
                else:
                    try:
                        client.modify_route_table(rt_id, **modify)
                    except Exception as e:
                        module.fail_json(msg=str(e), route_table_id=rt_id)
                    changed = True

            try:
                assoc_changed = _reconcile_associations(
                    module, client, rt_id, existing, module.check_mode)
            except Exception as e:
                module.fail_json(msg=str(e), route_table_id=rt_id)
                return  # unreachable
            changed = changed or assoc_changed

            if not changed:
                module.exit_json(changed=False, route_table=existing)
            if module.check_mode:
                module.exit_json(changed=True, route_table=existing,
                                 msg="Would update route table {}".format(rt_id))
            module.exit_json(changed=True, route_table=client.get_route_table(rt_id))

        # No existing route table: create one.
        if not module.params.get('vpc_id'):
            module.fail_json(msg="vpc_id is required when creating a route table")
        if module.check_mode:
            module.exit_json(changed=True, route_table=None,
                             msg="Would create route table")
        try:
            result = client.create_route_table(**_create_kwargs(module.params))
        except Exception as e:
            module.fail_json(msg=str(e))
            return  # unreachable
        new_id = result.get('route_table_id') or result.get('RouteTableId')
        # Wire up associations on the freshly-created table if requested.
        new_rt = client.get_route_table(new_id)
        if module.params.get('associated_subnet_ids'):
            try:
                _reconcile_associations(
                    module, client, new_id, new_rt or {}, False)
            except Exception as e:
                module.fail_json(msg=str(e), route_table_id=new_id)
        module.exit_json(changed=True, route_table=client.get_route_table(new_id))

    # state == 'absent'
    if not existing:
        module.exit_json(changed=False, route_table=None,
                         msg="Route table not found; nothing to delete")
    if is_system_route_table(existing):
        module.fail_json(
            msg=("refusing to delete system route table {} for VPC {}; "
                 "it is owned by the VPC and removed with it"
                 .format(rt_id,
                         existing.get('vpc_id') or existing.get('VpcId'))),
            route_table_id=rt_id)
    if module.check_mode:
        module.exit_json(changed=True,
                         msg="Would delete route table {}".format(rt_id))
    try:
        client.delete_route_table(rt_id)
    except Exception as e:
        module.fail_json(msg=str(e), route_table_id=rt_id)
    module.exit_json(changed=True, route_table=None)


if __name__ == '__main__':
    main()
