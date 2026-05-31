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
module: byteplus_route_table_info
version_added: "1.3.0"
short_description: Describe BytePlus VPC route tables
description:
  - Read-only listing of BytePlus VPC route tables, optionally with their
    route entries hydrated inline.
  - Pagination is handled automatically.
options:
  route_table_ids:
    description:
      - List of route table IDs to fetch. BytePlus's underlying
        DescribeRouteTableList accepts a single id at a time; the module
        fans out one call per id when more than one is supplied.
    type: list
    elements: str
  route_table_name:
    description: Filter by exact name (use with O(vpc_id) for disambiguation).
    type: str
  vpc_id:
    description: Filter to route tables within a given VPC.
    type: str
  project_name:
    description: Filter by project.
    type: str
  include_entries:
    description:
      - When C(true), each route table in the result has its C(entries)
        populated via DescribeRouteEntryList. Costs one extra API call per
        route table, so leave off unless you need it.
    type: bool
    default: false
  max_results:
    description: Page size hint for the underlying API.
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
- name: List all route tables in a VPC
  fardani235.byteplus.byteplus_route_table_info:
    vpc_id: vpc-xxx
  register: rt_info

- name: Inspect one route table along with its routes
  fardani235.byteplus.byteplus_route_table_info:
    route_table_ids:
      - vtb-yyy
    include_entries: true
  register: rt_full
'''

RETURN = r'''
route_tables:
  description: Route table records (with C(entries) populated when O(include_entries=true)).
  type: list
  elements: dict
  returned: always
count:
  description: Number of records returned.
  type: int
  returned: always
'''

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.fardani235.byteplus.plugins.module_utils.vpc_common import (
    VPCClient,
    resolve_credentials,
)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            route_table_ids=dict(type='list', elements='str'),
            route_table_name=dict(type='str'),
            vpc_id=dict(type='str'),
            project_name=dict(type='str'),
            include_entries=dict(type='bool', default=False),
            max_results=dict(type='int', default=100),
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

    common = {'max_results': module.params['max_results']}
    if module.params.get('vpc_id'):
        common['vpc_id'] = module.params['vpc_id']
    if module.params.get('route_table_name'):
        common['route_table_name'] = module.params['route_table_name']
    if module.params.get('project_name'):
        common['project_name'] = module.params['project_name']

    ids = module.params.get('route_table_ids') or []
    try:
        if ids:
            # DescribeRouteTableList accepts only one route_table_id per call,
            # so fan out and concat.
            tables = []
            for rid in ids:
                filters = dict(common)
                filters['route_table_id'] = rid
                tables.extend(client.describe_route_tables(**filters))
        else:
            tables = client.describe_route_tables(**common)

        if module.params['include_entries']:
            for t in tables:
                tid = t.get('route_table_id') or t.get('RouteTableId')
                t['entries'] = client.describe_route_entries(route_table_id=tid)
    except Exception as e:
        module.fail_json(msg=str(e))

    module.exit_json(changed=False, route_tables=tables, count=len(tables))


if __name__ == '__main__':
    main()
