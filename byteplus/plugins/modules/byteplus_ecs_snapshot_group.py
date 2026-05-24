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
module: byteplus_ecs_snapshot_group
version_added: "1.1.0"
short_description: Manage BytePlus EBS instance-wide (multi-volume) snapshot groups
description:
  - Create, delete, or roll back a snapshot group — a point-in-time snapshot
    covering every volume attached to a single ECS instance (or an explicit
    subset of those volumes).
  - For snapshots of an individual volume, use
    M(fardani235.byteplus.byteplus_ecs_snapshot) instead.
  - "Rollback semantics: BytePlus requires the target instance to be in the
    C(STOPPED) state before C(RollbackSnapshotGroup) succeeds. This module
    is intentionally strict: if the instance is not already C(STOPPED) when
    O(state=rolled_back) is requested, the module fails fast. It will never
    auto-stop a running workload to make a rollback succeed — orchestrate
    the stop explicitly with M(fardani235.byteplus.byteplus_ecs_instance)."
options:
  state:
    description:
      - C(present) ensures a snapshot group exists; creates it if missing.
      - C(absent) deletes the snapshot group.
      - C(rolled_back) rolls C(instance_id) back to the snapshot group.
        Requires the instance to already be in C(STOPPED) state — the
        module fails otherwise.
    type: str
    default: present
    choices: [present, absent, rolled_back]
  snapshot_group_id:
    description:
      - ID of an existing snapshot group. Required for C(absent) /
        C(rolled_back) if O(name) is not provided.
    type: str
  name:
    description:
      - Human-readable name. Used to look up an existing snapshot group
        when O(snapshot_group_id) is not given, and applied to the new
        snapshot group on create.
    type: str
  instance_id:
    description:
      - ID of the ECS instance to snapshot. Required when creating.
      - Also required for O(state=rolled_back).
    type: str
  description:
    description: Free-form description.
    type: str
  volume_ids:
    description:
      - Optional explicit subset of volumes to include. Omit to have the
        module discover every volume currently attached to the instance
        via C(DescribeInstances) and snapshot all of them.
      - "Note: BytePlus's C(CreateSnapshotGroup) API requires C(VolumeIds)
        even though the SDK contract marks it optional — this module
        always sends a populated list, derived from the instance when
        the caller omits the parameter."
      - Reused on C(rolled_back) to restrict the rollback to a subset of
        the volumes captured in the snapshot group.
    type: list
    elements: str
  snapshot_ids:
    description:
      - For C(rolled_back) only — explicit set of snapshot IDs from the
        group to apply. Omit to use every snapshot in the group.
    type: list
    elements: str
  project_name:
    description: BytePlus project to create the snapshot group in.
    type: str
  tags:
    description: List of C({key, value}) tag dicts to attach at create time.
    type: list
    elements: dict
  client_token:
    description: Idempotency token forwarded to the underlying API calls.
    type: str
  wait:
    description:
      - For C(present), wait until the group reaches C(available).
      - For C(absent), wait until it disappears.
      - For C(rolled_back), the call is asynchronous on the BytePlus side
        but returns once accepted; C(wait) has no effect.
    type: bool
    default: true
  wait_timeout:
    description: Seconds to wait. Large instances can take a while.
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
- name: Take a snapshot of every volume on an instance
  fardani235.byteplus.byteplus_ecs_snapshot_group:
    name: web-01-2026-05-24
    instance_id: i-ybw0lke12345
    description: Pre-deploy snapshot
    tags:
      - key: purpose
        value: pre-deploy
    state: present

- name: Snapshot only specific volumes
  fardani235.byteplus.byteplus_ecs_snapshot_group:
    name: db-01-data-only-2026-05-24
    instance_id: i-ybw0lke12345
    volume_ids:
      - vol-yb1111
      - vol-yb2222
    state: present

- name: Delete a snapshot group
  fardani235.byteplus.byteplus_ecs_snapshot_group:
    snapshot_group_id: snap-grp-yb0123456789
    state: absent

- name: Roll an instance back to a snapshot group
  # Important: this module will refuse if the instance is not already
  # STOPPED. Stop the instance first with byteplus_ecs_instance.
  fardani235.byteplus.byteplus_ecs_instance:
    instance_id: i-ybw0lke12345
    state: stopped

- name: Then perform the rollback
  fardani235.byteplus.byteplus_ecs_snapshot_group:
    snapshot_group_id: snap-grp-yb0123456789
    instance_id: i-ybw0lke12345
    state: rolled_back
'''

RETURN = r'''
snapshot_group:
  description: The (resolved or created) snapshot group description, or null on delete.
  type: dict
  returned: when state != absent or when an existing group was found
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
from ansible_collections.fardani235.byteplus.plugins.module_utils.ecs_common import (
    ECSClient,
    INSTANCE_STATE_STOPPED,
)


def _discover_instance_volume_ids(ecs_client, instance_id):
    """Return every VolumeId currently attached to the instance.

    BytePlus's CreateSnapshotGroup is documented as accepting an optional
    VolumeIds, but the server actually rejects the request with
    `ValidateRequestFailed` / "VolumeIds required" if it's omitted — the
    SDK swagger contract and the wire contract disagree. So when the
    caller doesn't pin a subset, we discover the volume set ourselves
    from DescribeInstances.
    """
    inst = ecs_client.get_instance(instance_id)
    if inst is None:
        return None
    raw = inst.get('volumes') or inst.get('Volumes') or []
    ids = []
    for v in raw:
        if isinstance(v, dict):
            vid = v.get('volume_id') or v.get('VolumeId')
        else:
            vid = getattr(v, 'volume_id', None) or getattr(v, 'VolumeId', None)
        if vid:
            ids.append(vid)
    return ids


def _resolve_group(module, client):
    """Return (group_dict_or_None, group_id_or_None)."""
    group_id = module.params.get('snapshot_group_id')
    name = module.params.get('name')
    if group_id:
        grp = client.get_snapshot_group(group_id)
        return grp, group_id
    if name:
        try:
            grp = client.find_snapshot_group_by_name(
                name, project_name=module.params.get('project_name'))
        except Exception as e:
            module.fail_json(msg=str(e))
            return None, None  # unreachable
        if grp:
            return grp, grp.get('snapshot_group_id') or grp.get('SnapshotGroupId')
    return None, None


def _do_create(module, client, ecs_client):
    instance_id = module.params.get('instance_id')
    if not instance_id:
        module.fail_json(
            msg="instance_id is required to create a snapshot group")
    # Caller can pin a subset of volumes; otherwise we discover all volumes
    # attached to the instance, because the BytePlus server rejects
    # CreateSnapshotGroup with no VolumeIds (despite the SDK marking it
    # optional). See _discover_instance_volume_ids for the full rationale.
    volume_ids = module.params.get('volume_ids')
    if not volume_ids:
        volume_ids = _discover_instance_volume_ids(ecs_client, instance_id)
        if not volume_ids:
            module.fail_json(
                msg=("Could not discover any volumes attached to instance "
                     "{}. Pass volume_ids explicitly or attach at least one "
                     "EBS volume before snapshotting.").format(instance_id))
    if module.check_mode:
        module.exit_json(
            changed=True, snapshot_group=None,
            msg="Would create snapshot group of instance {} ({} volumes)".format(
                instance_id, len(volume_ids)))
    result = None
    try:
        result = client.create_snapshot_group(
            instance_id=instance_id,
            name=module.params.get('name'),
            description=module.params.get('description'),
            volume_ids=volume_ids,
            project_name=module.params.get('project_name'),
            tags=module.params.get('tags'),
            client_token=module.params.get('client_token'),
        )
    except ValueError as e:
        module.fail_json(msg=str(e))
    except Exception as e:
        module.fail_json(msg=str(e))

    group_id = ((result or {}).get('snapshot_group_id')
                or (result or {}).get('SnapshotGroupId'))
    if not group_id:
        module.fail_json(
            msg="CreateSnapshotGroup returned no SnapshotGroupId: {}".format(
                result or {}))

    grp = None
    if module.params['wait']:
        try:
            grp = client.wait_for_snapshot_group_state(
                group_id, SNAPSHOT_STATE_AVAILABLE,
                timeout=module.params['wait_timeout'])
        except Exception as e:
            module.fail_json(msg=str(e), snapshot_group_id=group_id)
    else:
        grp = client.get_snapshot_group(group_id)
    module.exit_json(changed=True, snapshot_group=grp)


def _do_rollback(module, snap_client, ecs_client, grp, group_id):
    """Strict rollback: refuse to proceed unless the instance is STOPPED.

    BytePlus rejects RollbackSnapshotGroup against non-stopped instances
    anyway, but the API error is a generic "invalid state" — surface a
    targeted, actionable error here instead.
    """
    instance_id = module.params.get('instance_id')
    if not instance_id:
        # We can sometimes recover this from the group's metadata, but
        # we'd still need the caller to confirm — stay strict.
        instance_id = (grp.get('instance_id') if grp else None) \
            or (grp.get('InstanceId') if grp else None)
    if not instance_id:
        module.fail_json(
            msg="instance_id is required for state=rolled_back (could not "
                "infer it from the snapshot group either)")

    inst = ecs_client.get_instance(instance_id)
    if inst is None:
        module.fail_json(
            msg="Instance {} not found — cannot roll back".format(instance_id))
    current_state = inst.get('status') or inst.get('Status')
    if current_state != INSTANCE_STATE_STOPPED:
        module.fail_json(
            msg=("Refusing to roll back instance {}: current state is {!r}, "
                 "but BytePlus requires the instance to be {!r}. Stop the "
                 "instance first (e.g. with the byteplus_ecs_instance module, "
                 "state=stopped) and re-run this play.").format(
                     instance_id, current_state, INSTANCE_STATE_STOPPED))

    if module.check_mode:
        module.exit_json(
            changed=True, snapshot_group=grp,
            msg="Would roll back instance {} to snapshot group {}".format(
                instance_id, group_id))

    try:
        snap_client.rollback_snapshot_group(
            snapshot_group_id=group_id,
            instance_id=instance_id,
            snapshot_ids=module.params.get('snapshot_ids'),
            volume_ids=module.params.get('volume_ids'),
            client_token=module.params.get('client_token'),
        )
    except Exception as e:
        module.fail_json(msg=str(e), snapshot_group_id=group_id,
                         instance_id=instance_id)

    # No wait here: the rollback API itself returns once the request is
    # accepted. The user can poll instance state with byteplus_ecs_instance
    # if they need to gate on completion.
    module.exit_json(changed=True, snapshot_group=grp,
                     instance_id=instance_id)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(type='str', default='present',
                       choices=['present', 'absent', 'rolled_back']),
            snapshot_group_id=dict(type='str'),
            name=dict(type='str'),
            instance_id=dict(type='str'),
            description=dict(type='str'),
            volume_ids=dict(type='list', elements='str'),
            snapshot_ids=dict(type='list', elements='str'),
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
        required_one_of=[('snapshot_group_id', 'name', 'instance_id')],
        supports_check_mode=True,
    )

    ak, sk, region, st = resolve_credentials(module)
    try:
        snap_client = SnapshotClient(ak, sk, region, session_token=st)
    except Exception as e:
        module.fail_json(
            msg="Failed to initialize EBS snapshot client: {}".format(str(e)))
    # ECS client is needed both for the strict-rollback state check AND
    # for discovering the instance's attached volumes on create. Construct
    # once up-front so both paths share it.
    try:
        ecs_client = ECSClient(ak, sk, region, session_token=st)
    except Exception as e:
        module.fail_json(
            msg="Failed to initialize ECS client: {}".format(str(e)))

    state = module.params['state']
    grp, group_id = _resolve_group(module, snap_client)

    if state == 'present':
        if grp:
            module.exit_json(changed=False, snapshot_group=grp)
        _do_create(module, snap_client, ecs_client)
        return  # _do_create exits

    if state == 'absent':
        if not grp:
            module.exit_json(changed=False, snapshot_group=None,
                             msg="Snapshot group not found; nothing to delete")
        if module.check_mode:
            module.exit_json(
                changed=True, snapshot_group=grp,
                msg="Would delete snapshot group {}".format(group_id))
        try:
            snap_client.delete_snapshot_group(group_id)
        except Exception as e:
            module.fail_json(msg=str(e), snapshot_group_id=group_id)
        if module.params['wait']:
            try:
                snap_client.wait_for_snapshot_group_state(
                    group_id, 'DELETED',
                    timeout=module.params['wait_timeout'])
            except Exception as e:
                module.fail_json(msg=str(e), snapshot_group_id=group_id)
        module.exit_json(changed=True, snapshot_group=None)

    # state == 'rolled_back'
    if not grp:
        module.fail_json(
            msg="No snapshot group found (looked up by snapshot_group_id={!r} "
                "and name={!r}). Cannot roll back.".format(
                    module.params.get('snapshot_group_id'),
                    module.params.get('name')))
    _do_rollback(module, snap_client, ecs_client, grp, group_id)


if __name__ == '__main__':
    main()
