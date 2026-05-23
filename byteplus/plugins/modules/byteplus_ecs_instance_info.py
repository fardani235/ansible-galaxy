#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright BytePlus Inc.
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type


DOCUMENTATION = r'''
---
module: byteplus_ecs_instance_info
version_added: "1.0.0"
short_description: Describe BytePlus ECS instances
description:
  - Read-only listing/describe of ECS instances. Handles pagination automatically.
options:
  instance_ids:
    description: List of instance IDs to fetch. Mutually compatible with the filters below.
    type: list
    elements: str
  instance_name:
    description: Filter by exact instance name.
    type: str
  zone_id:
    description: Filter to a single availability zone.
    type: str
  vpc_id:
    description: Filter by VPC.
    type: str
  status:
    description: Filter by lifecycle status (e.g. C(RUNNING), C(STOPPED)).
    type: str
  project_name:
    description: Filter by project.
    type: str
  tags:
    description:
      - Filter by tag. Pass as a list of C({key, value}) dicts; the API
        will return instances matching ANY of the supplied tag filters.
    type: list
    elements: dict
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
- name: List all running instances in a zone
  byteplus.cloud.byteplus_ecs_instance_info:
    zone_id: ap-southeast-1a
    status: RUNNING
  register: ecs_info

- name: Look up specific instances
  byteplus.cloud.byteplus_ecs_instance_info:
    instance_ids:
      - i-ybw0lke12345
      - i-ybw0lkeabcdef
'''

RETURN = r'''
instances:
  description: List of instance descriptions matching the filters.
  type: list
  elements: dict
  returned: always
count:
  description: Number of instances returned.
  type: int
  returned: always
'''

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.fardani235.byteplus.plugins.module_utils.ecs_common import (
    ECSClient,
    resolve_credentials,
)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            instance_ids=dict(type='list', elements='str'),
            instance_name=dict(type='str'),
            zone_id=dict(type='str'),
            vpc_id=dict(type='str'),
            status=dict(type='str'),
            project_name=dict(type='str'),
            tags=dict(type='list', elements='dict'),
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
        client = ECSClient(ak, sk, region, session_token=st)
    except Exception as e:
        module.fail_json(msg="Failed to initialize ECS client: {}".format(str(e)))

    filters = {}
    for k in ('instance_ids', 'instance_name', 'zone_id', 'vpc_id',
              'status', 'project_name', 'max_results'):
        v = module.params.get(k)
        if v is not None:
            filters[k] = v
    if module.params.get('tags'):
        filters['tag_filters'] = module.params['tags']

    try:
        instances = client.describe_all_instances(**filters)
    except Exception as e:
        module.fail_json(msg=str(e))
        return  # unreachable

    module.exit_json(changed=False, instances=instances, count=len(instances))


if __name__ == '__main__':
    main()
