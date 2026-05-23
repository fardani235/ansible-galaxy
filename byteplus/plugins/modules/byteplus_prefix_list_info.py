#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright BytePlus Inc.
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type


DOCUMENTATION = r'''
---
module: byteplus_prefix_list_info
version_added: "1.0.0"
short_description: Describe BytePlus VPC prefix lists
description:
  - Read-only listing of BytePlus VPC prefix lists with optional entry hydration.
  - Pagination is handled automatically.
options:
  prefix_list_ids:
    description: List of prefix list IDs to fetch.
    type: list
    elements: str
  prefix_list_name:
    description: Filter by exact name.
    type: str
  project_name:
    description: Filter by project.
    type: str
  ip_version:
    description: Filter by address family.
    type: str
    choices: [IPv4, IPv6]
  include_entries:
    description:
      - When C(true), each prefix list in the result has its C(entries)
        populated via DescribePrefixListEntries. Costs one extra API call
        per prefix list, so leave off unless you need it.
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
- name: List all prefix lists in a project
  fardani235.byteplus.byteplus_prefix_list_info:
    project_name: prod
  register: pl_info

- name: Get one prefix list with its entries
  fardani235.byteplus.byteplus_prefix_list_info:
    prefix_list_name: office-egress
    project_name: prod
    include_entries: true
  register: office_pl
'''

RETURN = r'''
prefix_lists:
  description: Prefix list records (with C(entries) populated when O(include_entries=true)).
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
            prefix_list_ids=dict(type='list', elements='str'),
            prefix_list_name=dict(type='str'),
            project_name=dict(type='str'),
            ip_version=dict(type='str', choices=['IPv4', 'IPv6']),
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

    filters = {}
    for k in ('prefix_list_ids', 'prefix_list_name', 'project_name',
              'ip_version', 'max_results'):
        v = module.params.get(k)
        if v is not None:
            filters[k] = v

    try:
        prefix_lists = client.describe_prefix_lists(**filters)
    except Exception as e:
        module.fail_json(msg=str(e))
        return  # unreachable

    if module.params.get('include_entries'):
        for pl in prefix_lists:
            pl_id = pl.get('prefix_list_id') or pl.get('PrefixListId')
            if pl_id:
                try:
                    pl['entries'] = client.describe_prefix_list_entries(pl_id)
                except Exception as e:
                    module.fail_json(msg=str(e), prefix_list_id=pl_id)
                    return  # unreachable

    module.exit_json(changed=False, prefix_lists=prefix_lists,
                     count=len(prefix_lists))


if __name__ == '__main__':
    main()
