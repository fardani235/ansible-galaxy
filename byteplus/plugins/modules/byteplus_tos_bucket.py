#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: byteplus_tos_bucket
version_added: "1.0.0"
short_description: Manage TOS (Torch Object Storage) buckets
description:
  - Create, delete, and check existence of TOS buckets.
  - This module is idempotent and supports check mode.
  - Uses S3-compatible REST API via the BytePlus Python SDK.
options:
  bucket_name:
    description:
      - Name of the TOS bucket.
      - Must be 3-63 characters, lowercase letters, numbers, and hyphens only.
      - Must start and end with a letter or number.
    required: true
    type: str
  acl:
    description:
      - Access control list for the bucket.
    choices: [ 'private', 'public-read', 'public-read-write', 'authenticated-read' ]
    required: false
    type: str
  state:
    description:
      - Whether the bucket should exist or not.
    choices: [ 'present', 'absent' ]
    default: 'present'
    type: str
  access_key:
    description:
      - BytePlus access key. Can also be set via BYTEPLUS_ACCESS_KEY env var.
    required: false
    type: str
    no_log: true
  secret_key:
    description:
      - BytePlus secret key. Can also be set via BYTEPLUS_SECRET_KEY env var.
    required: false
    type: str
    no_log: true
  region:
    description:
      - TOS region (e.g. ap-southeast-1).
      - Can also be set via BYTEPLUS_REGION env var.
    required: false
    type: str
    default: 'ap-southeast-1'
author:
  - BytePlus
'''

EXAMPLES = r'''
- name: Create a TOS bucket
  byteplus_tos_bucket:
    bucket_name: my-example-bucket
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"
    region: ap-southeast-1

- name: Create a bucket with public-read ACL
  byteplus_tos_bucket:
    bucket_name: my-public-bucket
    acl: public-read
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"
    region: ap-southeast-1

- name: Delete a TOS bucket
  byteplus_tos_bucket:
    bucket_name: my-example-bucket
    state: absent
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"
    region: ap-southeast-1

- name: Check bucket existence (dry run)
  byteplus_tos_bucket:
    bucket_name: my-example-bucket
    state: present
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"
  check_mode: true
'''

RETURN = r'''
bucket:
  description: Name of the bucket.
  type: str
  returned: always
  sample: "my-example-bucket"
changed:
  description: Whether the operation changed the bucket.
  type: bool
  returned: always
message:
  description: Status message.
  type: str
  returned: always
'''

import os
import re

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.fardani235.byteplus.plugins.module_utils.tos_common import TOSClient


def validate_bucket_name(name):
    if not re.match(r'^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$', name):
        raise ValueError(
            "Bucket name must be 3-63 characters, lowercase letters/numbers/hyphens only, "
            "and cannot start or end with a hyphen"
        )


def run_module():
    module_args = dict(
        bucket_name=dict(type='str', required=True),
        acl=dict(type='str', choices=['private', 'public-read', 'public-read-write', 'authenticated-read']),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        access_key=dict(type='str', no_log=True),
        secret_key=dict(type='str', no_log=True),
        region=dict(type='str'),
    )

    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True,
    )

    bucket_name = module.params['bucket_name']
    acl = module.params['acl']
    state = module.params['state']

    try:
        validate_bucket_name(bucket_name)
    except ValueError as e:
        module.fail_json(msg=str(e))

    access_key = module.params['access_key'] or os.environ.get('BYTEPLUS_ACCESS_KEY')
    secret_key = module.params['secret_key'] or os.environ.get('BYTEPLUS_SECRET_KEY')
    region = module.params['region'] or os.environ.get('BYTEPLUS_REGION', 'ap-southeast-1')

    if not access_key or not secret_key:
        module.fail_json(msg="access_key and secret_key are required. Set them as module params or "
                             "via BYTEPLUS_ACCESS_KEY / BYTEPLUS_SECRET_KEY environment variables.")

    client = TOSClient(access_key, secret_key, region)

    try:
        exists = client.head_bucket(bucket_name)
    except Exception as e:
        module.fail_json(msg="Failed to check bucket: {0}".format(str(e)))

    result = dict(bucket=bucket_name)

    if state == 'present':
        if exists:
            module.exit_json(changed=False, **result)
        if module.check_mode:
            module.exit_json(changed=True, **result)
        try:
            client.create_bucket(bucket_name, acl=acl)
            module.exit_json(changed=True, **result)
        except Exception as e:
            module.fail_json(msg="Failed to create bucket: {0}".format(str(e)))

    elif state == 'absent':
        if not exists:
            module.exit_json(changed=False, **result)
        if module.check_mode:
            module.exit_json(changed=True, **result)
        try:
            client.delete_bucket(bucket_name)
            module.exit_json(changed=True, **result)
        except Exception as e:
            module.fail_json(msg="Failed to delete bucket: {0}".format(str(e)))


def main():
    run_module()


if __name__ == '__main__':
    main()
