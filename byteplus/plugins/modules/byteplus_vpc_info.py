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
module: byteplus_vpc_info
version_added: "1.3.0"
short_description: Describe BytePlus VPCs
description:
  - Read-only listing of BytePlus VPCs.
  - Pagination is handled automatically.
options:
  vpc_ids:
    description: List of VPC IDs to fetch.
    type: list
    elements: str
  vpc_name:
    description: Filter by exact name.
    type: str
  project_name:
    description: Filter by project.
    type: str
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
- name: List every VPC in the prod project
  fardani235.byteplus.byteplus_vpc_info:
    project_name: prod
  register: vpc_info

- name: Look up a specific VPC by name
  fardani235.byteplus.byteplus_vpc_info:
    vpc_name: prod-vpc
    project_name: prod
  register: prod_vpc
'''

RETURN = r'''
vpcs:
  description: VPC records.
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
            vpc_ids=dict(type='list', elements='str'),
            vpc_name=dict(type='str'),
            project_name=dict(type='str'),
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

    filters = {'max_results': module.params['max_results']}
    if module.params.get('vpc_ids'):
        filters['vpc_ids'] = module.params['vpc_ids']
    if module.params.get('vpc_name'):
        filters['vpc_name'] = module.params['vpc_name']
    if module.params.get('project_name'):
        filters['project_name'] = module.params['project_name']

    try:
        vpcs = client.describe_vpcs(**filters)
    except Exception as e:
        module.fail_json(msg=str(e))

    module.exit_json(changed=False, vpcs=vpcs, count=len(vpcs))


if __name__ == '__main__':
    main()
