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
module: byteplus_route_entry
version_added: "1.3.0"
short_description: Manage a single BytePlus VPC route entry
description:
  - Create, modify, or delete one route entry inside a route table,
    identified by C((route_table_id, destination_cidr_block)).
  - Modifying the next-hop or description is done via ModifyRouteEntry,
    so in-flight traffic is not interrupted by a revoke/re-authorize cycle.
options:
  state:
    description:
      - C(present) creates the route entry if missing; otherwise reconciles
        next-hop and description.
      - C(absent) deletes the entry if it exists.
    type: str
    default: present
    choices: [present, absent]
  route_table_id:
    description: ID of the route table that owns this entry. Required.
    type: str
    required: true
  destination_cidr_block:
    description:
      - Destination CIDR block (the route's "match"). Required.
      - Within a route table, this is the entry's identity — there can only
        be one entry per destination.
    type: str
    required: true
  next_hop_type:
    description:
      - Where matching traffic should be forwarded. Required when
        C(state=present).
      - The value is translated to BytePlus's PascalCase spelling on the wire
        (e.g. C(nat_gateway) becomes C(NatGW)).
    type: str
    choices:
      - instance
      - network_interface
      - nat_gateway
      - vpn_gateway
      - transit_router
      - ipv6_gateway
      - ha_vip
      - private_link_vpc_endpoint
      - ip_address
  next_hop_id:
    description:
      - ID of the resource that traffic is forwarded to. Required when
        C(state=present), except for C(ip_address) next-hops where the
        target is encoded in the destination instead.
    type: str
  description:
    description: Free-form description for the entry.
    type: str
  route_entry_name:
    description: Optional display name for the entry. Applied on create
        and updated via ModifyRouteEntry on drift.
    type: str
  client_token:
    description: Idempotency token forwarded to CreateRouteEntry.
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
- name: Route everything to a NAT gateway
  fardani235.byteplus.byteplus_route_entry:
    route_table_id: vtb-xxx
    destination_cidr_block: 0.0.0.0/0
    next_hop_type: nat_gateway
    next_hop_id: ngw-yyy
    description: default egress

- name: Re-point an existing route at a different ENI
  fardani235.byteplus.byteplus_route_entry:
    route_table_id: vtb-xxx
    destination_cidr_block: 10.10.0.0/16
    next_hop_type: network_interface
    next_hop_id: eni-zzz

- name: Remove a route
  fardani235.byteplus.byteplus_route_entry:
    route_table_id: vtb-xxx
    destination_cidr_block: 192.0.2.0/24
    state: absent
'''

RETURN = r'''
route_entry:
  description: Route entry record. None when state=absent and the entry was deleted.
  type: dict
  returned: when state=present
changed:
  description: Whether any change was made.
  type: bool
  returned: always
'''

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.fardani235.byteplus.plugins.module_utils.vpc_common import (
    NEXT_HOP_TYPE_MAP,
    NEXT_HOP_TYPE_REVERSE,
    VPCClient,
    find_route_entry_match,
    resolve_credentials,
)


def _api_next_hop_type(snake):
    """Translate the user-facing snake_case value to BytePlus PascalCase.
    Returns None for None input — keeps optional-field handling uniform.
    """
    if snake is None:
        return None
    return NEXT_HOP_TYPE_MAP[snake]


def _existing_next_hop_type_snake(existing):
    """Read the next-hop type off a route-entry describe record and translate
    it back to snake_case for diff comparison. Unknown types pass through
    unchanged so the diff still works for future API additions.
    """
    raw = (existing.get('next_hop_type')
           or existing.get('NextHopType'))
    return NEXT_HOP_TYPE_REVERSE.get(raw, raw)


def _existing_field(existing, snake):
    """Read a snake/PascalCase field off a route-entry describe record."""
    pascal = ''.join(p.capitalize() for p in snake.split('_'))
    return existing.get(snake) or existing.get(pascal)


def _modify_kwargs(p, existing):
    """Compute the kwargs needed to bring an existing entry to the desired
    state. Returns None when no fields drift.

    Description and route_entry_name are compared with '' as the empty
    sentinel because that's how BytePlus's describe returns them when unset.
    """
    out = {}

    desired_type = p.get('next_hop_type')
    if desired_type and desired_type != _existing_next_hop_type_snake(existing):
        out['next_hop_type'] = _api_next_hop_type(desired_type)

    desired_nh = p.get('next_hop_id')
    if desired_nh is not None and desired_nh != (
            _existing_field(existing, 'next_hop_id') or ''):
        out['next_hop_id'] = desired_nh

    desired_desc = p.get('description')
    if desired_desc is not None and desired_desc != (
            _existing_field(existing, 'description') or ''):
        out['description'] = desired_desc

    desired_name = p.get('route_entry_name')
    if desired_name is not None and desired_name != (
            _existing_field(existing, 'route_entry_name') or ''):
        out['route_entry_name'] = desired_name

    return out or None


def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(type='str', default='present',
                       choices=['present', 'absent']),
            route_table_id=dict(type='str', required=True),
            destination_cidr_block=dict(type='str', required=True),
            next_hop_type=dict(type='str',
                               choices=sorted(NEXT_HOP_TYPE_MAP.keys())),
            next_hop_id=dict(type='str'),
            description=dict(type='str'),
            route_entry_name=dict(type='str'),
            client_token=dict(type='str'),
            access_key=dict(type='str', no_log=True),
            secret_key=dict(type='str', no_log=True),
            session_token=dict(type='str', no_log=True),
            region=dict(type='str'),
        ),
        supports_check_mode=True,
    )

    p = module.params
    state = p['state']

    if state == 'present':
        if not p.get('next_hop_type'):
            module.fail_json(
                msg="next_hop_type is required when state=present")
        # IPAddress next-hops encode the target in the CIDR itself; everything
        # else needs an explicit next_hop_id to point at.
        if p['next_hop_type'] != 'ip_address' and not p.get('next_hop_id'):
            module.fail_json(
                msg=("next_hop_id is required when state=present and "
                     "next_hop_type is not 'ip_address'"))

    ak, sk, region, st = resolve_credentials(module)
    try:
        client = VPCClient(ak, sk, region, session_token=st)
    except Exception as e:
        module.fail_json(msg="Failed to initialize VPC client: {}".format(str(e)))

    rt_id = p['route_table_id']
    cidr = p['destination_cidr_block']

    try:
        entries = client.describe_route_entries(route_table_id=rt_id)
    except Exception as e:
        module.fail_json(msg=str(e), route_table_id=rt_id)
        return  # unreachable
    existing = find_route_entry_match(entries, cidr)

    if state == 'present':
        if existing:
            modify = _modify_kwargs(p, existing)
            if not modify:
                module.exit_json(changed=False, route_entry=existing)
            entry_id = (existing.get('route_entry_id')
                        or existing.get('RouteEntryId'))
            if module.check_mode:
                module.exit_json(changed=True, route_entry=existing,
                                 msg="Would modify route entry {}".format(entry_id))
            try:
                client.modify_route_entry(entry_id, **modify)
            except Exception as e:
                module.fail_json(msg=str(e),
                                 route_table_id=rt_id,
                                 route_entry_id=entry_id)
            # Re-read to surface the updated record. The describe is bounded
            # by the table size, so an extra call is cheap here.
            fresh = find_route_entry_match(
                client.describe_route_entries(route_table_id=rt_id), cidr)
            module.exit_json(changed=True, route_entry=fresh)

        # Create
        if module.check_mode:
            module.exit_json(changed=True, route_entry=None,
                             msg="Would create route entry")
        create_kwargs = {
            'route_table_id': rt_id,
            'destination_cidr_block': cidr,
            'next_hop_type': _api_next_hop_type(p['next_hop_type']),
        }
        for k in ('next_hop_id', 'description', 'route_entry_name',
                  'client_token'):
            v = p.get(k)
            if v is not None:
                create_kwargs[k] = v
        try:
            client.create_route_entry(**create_kwargs)
        except Exception as e:
            module.fail_json(msg=str(e), route_table_id=rt_id)
        fresh = find_route_entry_match(
            client.describe_route_entries(route_table_id=rt_id), cidr)
        module.exit_json(changed=True, route_entry=fresh)

    # state == 'absent'
    if not existing:
        module.exit_json(changed=False, route_entry=None,
                         msg="Route entry not found; nothing to delete")
    entry_id = existing.get('route_entry_id') or existing.get('RouteEntryId')
    if module.check_mode:
        module.exit_json(changed=True,
                         msg="Would delete route entry {}".format(entry_id))
    try:
        client.delete_route_entry(entry_id)
    except Exception as e:
        module.fail_json(msg=str(e), route_entry_id=entry_id)
    module.exit_json(changed=True, route_entry=None)


if __name__ == '__main__':
    main()
