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
module: byteplus_tos_object
version_added: "1.0.0"
short_description: Manage TOS (Torch Object Storage) objects
description:
  - Upload, delete, and check existence of objects in TOS buckets.
  - This module is idempotent and supports check mode.
  - Idempotency is determined by comparing the MD5 hash (ETag) of the
    local file or content with the remote object.
  - Uses S3-compatible REST API via the BytePlus Python SDK.
options:
  bucket_name:
    description:
      - Name of the TOS bucket.
    required: true
    type: str
  object_key:
    description:
      - Key (path) of the object in the bucket.
    required: true
    type: str
  src:
    description:
      - Local file path to upload. Mutually exclusive with I(content).
    required: false
    type: path
  content:
    description:
      - Inline content to upload as the object body. Mutually exclusive with I(src).
    required: false
    type: str
  content_type:
    description:
      - MIME content type of the object.
      - Auto-detected from file extension if not specified.
    required: false
    type: str
  state:
    description:
      - Whether the object should exist or not.
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
- name: Upload a file to TOS
  byteplus_tos_object:
    bucket_name: my-example-bucket
    object_key: path/to/remote/file.txt
    src: /local/path/file.txt
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"
    region: ap-southeast-1

- name: Upload inline content
  byteplus_tos_object:
    bucket_name: my-example-bucket
    object_key: config/app.json
    content: '{"key": "value"}'
    content_type: application/json
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"
    region: ap-southeast-1

- name: Upload with explicit content type
  byteplus_tos_object:
    bucket_name: my-example-bucket
    object_key: index.html
    src: /local/index.html
    content_type: text/html
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"
    region: ap-southeast-1

- name: Delete an object
  byteplus_tos_object:
    bucket_name: my-example-bucket
    object_key: path/to/remote/file.txt
    state: absent
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"
    region: ap-southeast-1
'''

RETURN = r'''
bucket_name:
  description: Name of the bucket.
  type: str
  returned: always
  sample: "my-example-bucket"
object_key:
  description: Key of the object.
  type: str
  returned: always
  sample: "path/to/file.txt"
changed:
  description: Whether the operation changed the object.
  type: bool
  returned: always
message:
  description: Status message.
  type: str
  returned: always
'''

import hashlib
import mimetypes
import os

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.fardani235.byteplus.plugins.module_utils.tos_common import TOSClient


def _etag_to_md5(etag):
    if not etag:
        return None
    return etag.strip('" ')


def run_module():
    module_args = dict(
        bucket_name=dict(type='str', required=True),
        object_key=dict(type='str', required=True),
        src=dict(type='path'),
        content=dict(type='str'),
        content_type=dict(type='str'),
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
    object_key = module.params['object_key']
    src = module.params['src']
    content = module.params['content']
    content_type = module.params['content_type']
    state = module.params['state']

    if state == 'present':
        if src and content:
            module.fail_json(msg="Only one of 'src' or 'content' may be specified")
        if not src and not content:
            module.fail_json(msg="Either 'src' or 'content' is required when state=present")

    if src and not os.path.isfile(src):
        module.fail_json(msg="Source file '{0}' does not exist".format(src))

    if not content_type and src:
        guessed, _ = mimetypes.guess_type(src)
        if guessed:
            content_type = guessed

    access_key = module.params['access_key'] or os.environ.get('BYTEPLUS_ACCESS_KEY')
    secret_key = module.params['secret_key'] or os.environ.get('BYTEPLUS_SECRET_KEY')
    region = module.params['region'] or os.environ.get('BYTEPLUS_REGION', 'ap-southeast-1')

    if not access_key or not secret_key:
        module.fail_json(msg="access_key and secret_key are required. Set them as module params or "
                             "via BYTEPLUS_ACCESS_KEY / BYTEPLUS_SECRET_KEY environment variables.")

    client = TOSClient(access_key, secret_key, region)

    result = dict(
        bucket_name=bucket_name,
        object_key=object_key,
    )

    if state == 'present':
        if src:
            with open(src, 'rb') as f:
                body_bytes = f.read()
        else:
            body_bytes = content.encode('utf-8')
        local_md5 = hashlib.md5(body_bytes).hexdigest()

        try:
            exists, headers = client.head_object(bucket_name, object_key)
        except Exception as e:
            module.fail_json(msg="Failed to check object: {0}".format(str(e)))

        if exists:
            remote_etag = headers.get('etag') or headers.get('ETag')
            remote_md5 = _etag_to_md5(remote_etag)
            # ETag equals MD5 only for single-PUT, non-SSE-KMS objects.
            # Multipart uploads return "<md5>-<n>"; treat those as "unknown,
            # re-upload to be safe" rather than risking a false no-op.
            is_multipart = bool(remote_md5 and '-' in remote_md5)
            if not is_multipart and remote_md5 == local_md5:
                module.exit_json(changed=False, message="Object content is identical", **result)

        if module.check_mode:
            module.exit_json(changed=True, message="Object would be uploaded", **result)

        try:
            client.put_object(bucket_name, object_key, body_bytes, content_type=content_type)
            if exists:
                module.exit_json(changed=True, message="Object updated", **result)
            else:
                module.exit_json(changed=True, message="Object created", **result)
        except Exception as e:
            module.fail_json(msg="Failed to upload object: {0}".format(str(e)))

    elif state == 'absent':
        try:
            exists, _ = client.head_object(bucket_name, object_key)
        except Exception as e:
            module.fail_json(msg="Failed to check object: {0}".format(str(e)))

        if not exists:
            module.exit_json(changed=False, message="Object does not exist", **result)

        if module.check_mode:
            module.exit_json(changed=True, message="Object would be deleted", **result)

        try:
            client.delete_object(bucket_name, object_key)
            module.exit_json(changed=True, message="Object deleted", **result)
        except Exception as e:
            module.fail_json(msg="Failed to delete object: {0}".format(str(e)))


def main():
    run_module()


if __name__ == '__main__':
    main()
