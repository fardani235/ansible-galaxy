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
module: byteplus_ecs_snapshot_info
version_added: "1.1.0"
short_description: Describe BytePlus EBS snapshots and snapshot groups
description:
  - Read-only listing of EBS snapshots (single-volume) or snapshot groups
    (multi-volume / instance snapshots). Pagination is handled automatically.
options:
  kind:
    description:
      - Selects which API endpoint to query.
      - C(snapshot) lists individual volume snapshots.
      - C(snapshot_group) lists instance-wide snapshot groups.
    type: str
    default: snapshot
    choices: [snapshot, snapshot_group]
  snapshot_ids:
    description: For C(kind=snapshot), list of snapshot IDs to fetch.
    type: list
    elements: str
  snapshot_group_ids:
    description: For C(kind=snapshot_group), list of snapshot group IDs to fetch.
    type: list
    elements: str
  snapshot_name:
    description: For C(kind=snapshot), filter by exact snapshot name.
    type: str
  name:
    description: For C(kind=snapshot_group), filter by exact group name.
    type: str
  volume_id:
    description: For C(kind=snapshot), filter to one volume.
    type: str
  instance_id:
    description: For C(kind=snapshot_group), filter to groups for one instance.
    type: str
  zone_id:
    description: For C(kind=snapshot), filter to one availability zone.
    type: str
  status:
    description:
      - Filter by lifecycle status. C(available), C(creating), C(failed),
        C(deleting). Used for both kinds.
    type: str
  snapshot_types:
    description:
      - For C(kind=snapshot) only, restrict to snapshot types (e.g. C(All),
        C(Auto), C(User)).
    type: list
    elements: str
  project_name:
    description: Filter by project.
    type: str
  tags:
    description:
      - Filter by tag. Pass as a list of C({key, value}) dicts; the API
        returns objects matching ANY of the supplied tag filters.
    type: list
    elements: dict
  max_results:
    description: Page size hint (C(kind=snapshot) only).
    type: int
    default: 100
  page_size:
    description: Page size for C(kind=snapshot_group).
    type: int
    default: 100
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
- name: List all snapshots of a specific volume
  fardani235.byteplus.byteplus_ecs_snapshot_info:
    kind: snapshot
    volume_id: vol-yb1111
  register: snap_info

- name: List instance-wide snapshot groups for one instance
  fardani235.byteplus.byteplus_ecs_snapshot_info:
    kind: snapshot_group
    instance_id: i-ybw0lke12345
  register: grp_info
'''

RETURN = r'''
snapshots:
  description: List of snapshot descriptions (when kind=snapshot).
  type: list
  elements: dict
  returned: when kind=snapshot
snapshot_groups:
  description: List of snapshot group descriptions (when kind=snapshot_group).
  type: list
  elements: dict
  returned: when kind=snapshot_group
count:
  description: Number of items returned.
  type: int
  returned: always
'''

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.fardani235.byteplus.plugins.module_utils.snapshot_common import (
    SnapshotClient,
    resolve_credentials,
)


# Translate Ansible module params into the request kwargs each endpoint
# accepts. Keeping these whitelists explicit means we never accidentally
# forward an unsupported field and get a generic API error.
_SNAPSHOT_FILTERS = (
    'snapshot_ids', 'snapshot_name', 'volume_id', 'zone_id',
    'project_name', 'snapshot_types', 'max_results',
)
_GROUP_FILTERS = (
    'snapshot_group_ids', 'name', 'instance_id', 'project_name',
    'page_size',
)


def _list_snapshots(module, client):
    p = module.params
    filters = {}
    for k in _SNAPSHOT_FILTERS:
        v = p.get(k)
        if v is not None:
            filters[k] = v
    if p.get('status') is not None:
        # DescribeSnapshots accepts the lifecycle status under
        # `snapshot_status`, not `status` — easy footgun for callers.
        filters['snapshot_status'] = p['status']
    if p.get('tags'):
        filters['tag_filters'] = p['tags']
    try:
        items = client.describe_all_snapshots(**filters)
    except Exception as e:
        module.fail_json(msg=str(e))
        return  # unreachable
    module.exit_json(changed=False, snapshots=items, count=len(items))


def _list_snapshot_groups(module, client):
    p = module.params
    filters = {}
    for k in _GROUP_FILTERS:
        v = p.get(k)
        if v is not None:
            filters[k] = v
    if p.get('status') is not None:
        filters['status'] = p['status']
    if p.get('tags'):
        filters['tag_filters'] = p['tags']
    try:
        items = client.describe_all_snapshot_groups(**filters)
    except Exception as e:
        module.fail_json(msg=str(e))
        return  # unreachable
    module.exit_json(changed=False, snapshot_groups=items, count=len(items))


def main():
    module = AnsibleModule(
        argument_spec=dict(
            kind=dict(type='str', default='snapshot',
                      choices=['snapshot', 'snapshot_group']),
            snapshot_ids=dict(type='list', elements='str'),
            snapshot_group_ids=dict(type='list', elements='str'),
            snapshot_name=dict(type='str'),
            name=dict(type='str'),
            volume_id=dict(type='str'),
            instance_id=dict(type='str'),
            zone_id=dict(type='str'),
            status=dict(type='str'),
            snapshot_types=dict(type='list', elements='str'),
            project_name=dict(type='str'),
            tags=dict(type='list', elements='dict'),
            max_results=dict(type='int', default=100),
            page_size=dict(type='int', default=100),
            access_key=dict(type='str', no_log=True),
            secret_key=dict(type='str', no_log=True),
            session_token=dict(type='str', no_log=True),
            region=dict(type='str'),
        ),
        supports_check_mode=True,
    )

    ak, sk, region, st = resolve_credentials(module)
    try:
        client = SnapshotClient(ak, sk, region, session_token=st)
    except Exception as e:
        module.fail_json(
            msg="Failed to initialize EBS snapshot client: {}".format(str(e)))

    if module.params['kind'] == 'snapshot':
        _list_snapshots(module, client)
    else:
        _list_snapshot_groups(module, client)


if __name__ == '__main__':
    main()
