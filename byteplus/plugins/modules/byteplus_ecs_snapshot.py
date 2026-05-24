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
module: byteplus_ecs_snapshot
version_added: "1.1.0"
short_description: Manage BytePlus EBS single-volume snapshots
description:
  - Create or delete a snapshot of a single BytePlus EBS volume.
  - A snapshot is identified by C(snapshot_id), or by C(snapshot_name)
    (which must be unique — narrow with O(project_name) if collisions exist).
  - For point-in-time snapshots of every volume attached to an instance,
    use M(fardani235.byteplus.byteplus_ecs_snapshot_group) instead.
options:
  state:
    description:
      - C(present) ensures the snapshot exists; creates it if missing.
      - C(absent) deletes the snapshot.
    type: str
    default: present
    choices: [present, absent]
  snapshot_id:
    description:
      - ID of an existing snapshot. Required for C(absent) if
        O(snapshot_name) is not provided.
    type: str
  snapshot_name:
    description:
      - Human-readable name. Used to look up an existing snapshot when
        O(snapshot_id) is not given, and applied to the new snapshot on
        create. Not enforced unique by the API — pair with O(project_name)
        to disambiguate.
    type: str
  volume_id:
    description: ID of the volume to snapshot. Required when creating.
    type: str
  description:
    description: Free-form snapshot description.
    type: str
  retention_days:
    description:
      - Auto-delete the snapshot after this many days. Omit for no
        automatic expiry.
    type: int
  project_name:
    description: BytePlus project to create the snapshot in / scope lookups to.
    type: str
  tags:
    description: List of C({key, value}) tag dicts to attach at create time.
    type: list
    elements: dict
  client_token:
    description: Idempotency token forwarded to CreateSnapshot/DeleteSnapshot.
    type: str
  wait:
    description:
      - Wait for the snapshot to reach the C(available) state before returning.
    type: bool
    default: true
  wait_timeout:
    description:
      - Seconds to wait. Snapshots can take many minutes for large volumes,
        hence the generous default.
    type: int
    default: 1800
  access_key:
    description: BytePlus access key. Falls back to C(BYTEPLUS_ACCESS_KEY).
    type: str
    no_log: true
  secret_key:
    description: BytePlus secret key. Falls back to C(BYTEPLUS_SECRET_KEY).
    type: str
    no_log: true
  session_token:
    description: Optional STS session token. Falls back to C(BYTEPLUS_SESSION_TOKEN).
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
- name: Snapshot a data volume and wait for it to become available
  fardani235.byteplus.byteplus_ecs_snapshot:
    snapshot_name: db-data-2026-05-24
    volume_id: vol-ybcafelovesnapshots
    description: Pre-upgrade snapshot of db-01 data disk
    retention_days: 7
    tags:
      - key: env
        value: prod
    state: present

- name: Delete a snapshot by ID
  fardani235.byteplus.byteplus_ecs_snapshot:
    snapshot_id: snap-yb0123456789
    state: absent

- name: Delete a snapshot by name (scoped to a project)
  fardani235.byteplus.byteplus_ecs_snapshot:
    snapshot_name: db-data-2026-05-24
    project_name: prod
    state: absent
'''

RETURN = r'''
snapshot:
  description: The (resolved or created) snapshot description, or null on delete.
  type: dict
  returned: when state != absent or when an existing snapshot was found
changed:
  description: Whether any change was made.
  type: bool
  returned: always
'''

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.fardani235.byteplus.plugins.module_utils.snapshot_common import (
    SnapshotClient,
    SNAPSHOT_STATE_AVAILABLE,
    resolve_credentials,
)


def _resolve_snapshot(module, client):
    """Return (snapshot_dict_or_None, snapshot_id_or_None)."""
    snapshot_id = module.params.get('snapshot_id')
    name = module.params.get('snapshot_name')
    if snapshot_id:
        snap = client.get_snapshot(snapshot_id)
        return snap, snapshot_id
    if name:
        try:
            snap = client.find_snapshot_by_name(
                name, project_name=module.params.get('project_name'))
        except Exception as e:
            module.fail_json(msg=str(e))
            return None, None  # unreachable
        if snap:
            return snap, snap.get('snapshot_id') or snap.get('SnapshotId')
    return None, None


def _do_create(module, client):
    if not module.params.get('volume_id'):
        module.fail_json(
            msg="volume_id is required to create a snapshot")
    if module.check_mode:
        module.exit_json(changed=True, snapshot=None,
                         msg="Would create snapshot of volume {}".format(
                             module.params['volume_id']))
    result = None
    try:
        result = client.create_snapshot(
            volume_id=module.params['volume_id'],
            snapshot_name=module.params.get('snapshot_name'),
            description=module.params.get('description'),
            retention_days=module.params.get('retention_days'),
            project_name=module.params.get('project_name'),
            tags=module.params.get('tags'),
            client_token=module.params.get('client_token'),
        )
    except ValueError as e:
        # Raised by tag validation in snapshot_common.
        module.fail_json(msg=str(e))
    except Exception as e:
        module.fail_json(msg=str(e))

    snapshot_id = (result or {}).get('snapshot_id') or (result or {}).get('SnapshotId')
    if not snapshot_id:
        module.fail_json(
            msg="CreateSnapshot returned no snapshot ID: {}".format(result or {}))

    snap = None
    if module.params['wait']:
        try:
            snap = client.wait_for_snapshot_state(
                snapshot_id, SNAPSHOT_STATE_AVAILABLE,
                timeout=module.params['wait_timeout'])
        except Exception as e:
            module.fail_json(msg=str(e), snapshot_id=snapshot_id)
    else:
        snap = client.get_snapshot(snapshot_id)
    module.exit_json(changed=True, snapshot=snap)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(type='str', default='present',
                       choices=['present', 'absent']),
            snapshot_id=dict(type='str'),
            snapshot_name=dict(type='str'),
            volume_id=dict(type='str'),
            description=dict(type='str'),
            retention_days=dict(type='int'),
            project_name=dict(type='str'),
            tags=dict(type='list', elements='dict'),
            client_token=dict(type='str'),
            wait=dict(type='bool', default=True),
            wait_timeout=dict(type='int', default=1800),
            access_key=dict(type='str', no_log=True),
            secret_key=dict(type='str', no_log=True),
            session_token=dict(type='str', no_log=True),
            region=dict(type='str'),
        ),
        required_one_of=[('snapshot_id', 'snapshot_name', 'volume_id')],
        supports_check_mode=True,
    )

    ak, sk, region, st = resolve_credentials(module)
    try:
        client = SnapshotClient(ak, sk, region, session_token=st)
    except Exception as e:
        module.fail_json(
            msg="Failed to initialize EBS snapshot client: {}".format(str(e)))

    state = module.params['state']
    snap, snapshot_id = _resolve_snapshot(module, client)

    if state == 'present':
        if snap:
            module.exit_json(changed=False, snapshot=snap)
        _do_create(module, client)
        return  # _do_create exits

    # state == 'absent'
    if not snap:
        module.exit_json(changed=False, snapshot=None,
                         msg="Snapshot not found; nothing to delete")
    if module.check_mode:
        module.exit_json(changed=True, snapshot=snap,
                         msg="Would delete snapshot {}".format(snapshot_id))
    try:
        client.delete_snapshot(snapshot_id,
                               client_token=module.params.get('client_token'))
    except Exception as e:
        module.fail_json(msg=str(e), snapshot_id=snapshot_id)
    if module.params['wait']:
        try:
            client.wait_for_snapshot_state(
                snapshot_id, 'DELETED',
                timeout=module.params['wait_timeout'])
        except Exception as e:
            module.fail_json(msg=str(e), snapshot_id=snapshot_id)
    module.exit_json(changed=True, snapshot=None)


if __name__ == '__main__':
    main()
