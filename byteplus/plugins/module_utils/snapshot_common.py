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

import time

from byteplussdkcore.configuration import Configuration
from byteplussdkcore.api_client import ApiClient
from byteplussdkcore.rest import ApiException
from byteplussdkstorageebs.api.storage_ebs_api import STORAGEEBSApi
from byteplussdkstorageebs.models.create_snapshot_request import CreateSnapshotRequest
from byteplussdkstorageebs.models.create_snapshot_group_request import (
    CreateSnapshotGroupRequest,
)
from byteplussdkstorageebs.models.delete_snapshot_request import DeleteSnapshotRequest
from byteplussdkstorageebs.models.delete_snapshot_group_request import (
    DeleteSnapshotGroupRequest,
)
from byteplussdkstorageebs.models.describe_snapshots_request import (
    DescribeSnapshotsRequest,
)
from byteplussdkstorageebs.models.describe_snapshot_groups_request import (
    DescribeSnapshotGroupsRequest,
)
from byteplussdkstorageebs.models.rollback_snapshot_group_request import (
    RollbackSnapshotGroupRequest,
)
from byteplussdkstorageebs.models.tag_for_create_snapshot_input import (
    TagForCreateSnapshotInput,
)
from byteplussdkstorageebs.models.tag_for_create_snapshot_group_input import (
    TagForCreateSnapshotGroupInput,
)

# Re-use the verbose API-error formatter and credential resolver from
# ecs_common — there's no value in forking another copy.
from ansible_collections.fardani235.byteplus.plugins.module_utils.ecs_common import (
    _format_api_error,
    resolve_credentials,  # noqa: F401  re-exported for module convenience
)


# BytePlus EBS snapshot lifecycle status values.
# https://docs.byteplus.com/en/docs/Volcengine/storage-ebs-api-reference
SNAPSHOT_STATE_CREATING = 'creating'
SNAPSHOT_STATE_AVAILABLE = 'available'
SNAPSHOT_STATE_FAILED = 'failed'
SNAPSHOT_STATE_DELETING = 'deleting'

# Terminal states for create-flow waits: once a snapshot reaches one of these
# additional polling can't change anything.
_TERMINAL_CREATE = {SNAPSHOT_STATE_AVAILABLE, SNAPSHOT_STATE_FAILED}


_ALLOWED_TAG_FIELDS = frozenset({'key', 'value'})


def _build_tags(tags, tag_model):
    """Convert a list of {key, value} dicts into the SDK's typed tag models.

    Raw dicts are not serialized correctly (the SDK relies on attribute_map
    to translate snake_case → PascalCase wire fields), so we mirror the
    validation pattern used by ecs_common.
    """
    if not tags:
        return None
    out = []
    for i, t in enumerate(tags):
        if not isinstance(t, dict):
            raise ValueError("tags[{}] must be a dict".format(i))
        unknown = set(t) - _ALLOWED_TAG_FIELDS
        if unknown:
            raise ValueError(
                "tags[{}] has unknown field(s): {}. Allowed: key, value"
                .format(i, sorted(unknown)))
        if 'key' not in t:
            raise ValueError("tags[{}].key is required".format(i))
        out.append(tag_model(**t))
    return out


def _status_of(snapshot):
    """Snapshot status field has several casings depending on whether it
    came back from a list call vs a get call; normalize the lookup."""
    if not snapshot:
        return None
    return (snapshot.get('status')
            or snapshot.get('Status')
            or snapshot.get('snapshot_status')
            or snapshot.get('SnapshotStatus'))


class SnapshotClient(object):
    """Thin wrapper over byteplussdkstorageebs.StorageEbsApi.

    Constructor mirrors ECSClient — same AK/SK/region/session_token/endpoint
    signature — so the module-level boilerplate is identical to the ECS
    modules.
    """

    def __init__(self, access_key, secret_key, region, session_token=None,
                 endpoint=None):
        config = Configuration()
        config.ak = access_key
        config.sk = secret_key
        config.region = region
        if session_token:
            config.session_token = session_token
        if endpoint:
            config.host = endpoint
        # Dedicated ApiClient bound to this config — never share credentials
        # via Configuration.set_default().
        self.api = STORAGEEBSApi(api_client=ApiClient(configuration=config))

    @staticmethod
    def _to_dict(obj):
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        return obj

    # ----- single-volume snapshots -----

    def create_snapshot(self, volume_id, snapshot_name=None, description=None,
                        retention_days=None, project_name=None, tags=None,
                        client_token=None):
        kwargs = {'volume_id': volume_id}
        if snapshot_name is not None:
            kwargs['snapshot_name'] = snapshot_name
        if description is not None:
            kwargs['description'] = description
        if retention_days is not None:
            kwargs['retention_days'] = retention_days
        if project_name is not None:
            kwargs['project_name'] = project_name
        if client_token is not None:
            kwargs['client_token'] = client_token
        tag_models = _build_tags(tags, TagForCreateSnapshotInput)
        if tag_models is not None:
            kwargs['tags'] = tag_models
        req = CreateSnapshotRequest(**kwargs)
        try:
            return self._to_dict(self.api.create_snapshot(req))
        except ApiException as e:
            raise Exception(_format_api_error(
                "EBS CreateSnapshot failed", e, {'volume_id': volume_id}))

    def describe_snapshots(self, **kwargs):
        req = DescribeSnapshotsRequest(**kwargs)
        try:
            return self._to_dict(self.api.describe_snapshots(req))
        except ApiException as e:
            raise Exception("EBS DescribeSnapshots failed: {}".format(e.reason))

    def describe_all_snapshots(self, **filters):
        """Paginated describe_snapshots — returns flat list. Snapshots use
        next_token-style cursoring (unlike snapshot groups, which use
        page_number)."""
        results = []
        next_token = None
        page_size = filters.pop('max_results', 100)
        while True:
            kwargs = dict(filters)
            kwargs['max_results'] = page_size
            if next_token:
                kwargs['next_token'] = next_token
            resp = self.describe_snapshots(**kwargs)
            page = resp.get('snapshots') or resp.get('Snapshots') or []
            results.extend(page)
            next_token = resp.get('next_token') or resp.get('NextToken')
            if not next_token:
                break
        return results

    def find_snapshot_by_name(self, snapshot_name, project_name=None):
        """Lookup by exact name. Returns dict or None.

        Raises on multiple matches — snapshot_name is not unique in EBS,
        so the caller must disambiguate with snapshot_id or narrow by
        project_name.
        """
        filters = {'snapshot_name': snapshot_name}
        if project_name:
            filters['project_name'] = project_name
        matches = self.describe_all_snapshots(**filters)
        exact = [
            s for s in matches
            if (s.get('snapshot_name') or s.get('SnapshotName')) == snapshot_name
        ]
        if len(exact) > 1:
            ids = [s.get('snapshot_id') or s.get('SnapshotId') for s in exact]
            hint = ("Pass snapshot_id to disambiguate"
                    if project_name
                    else "Pass snapshot_id, or set project_name to scope "
                         "the lookup to a single BytePlus project")
            raise Exception(
                "Multiple EBS snapshots match name '{}' ({}). {}.".format(
                    snapshot_name, ids, hint))
        return exact[0] if exact else None

    def get_snapshot(self, snapshot_id):
        resp = self.describe_snapshots(snapshot_ids=[snapshot_id])
        page = resp.get('snapshots') or resp.get('Snapshots') or []
        return page[0] if page else None

    def delete_snapshot(self, snapshot_id, client_token=None):
        kwargs = {'snapshot_id': snapshot_id}
        if client_token is not None:
            kwargs['client_token'] = client_token
        req = DeleteSnapshotRequest(**kwargs)
        try:
            return self._to_dict(self.api.delete_snapshot(req))
        except ApiException as e:
            raise Exception(_format_api_error(
                "EBS DeleteSnapshot failed", e, {'snapshot_id': snapshot_id}))

    def wait_for_snapshot_state(self, snapshot_id, target_state=SNAPSHOT_STATE_AVAILABLE,
                                timeout=1800, interval=10):
        """Poll until snapshot reaches target_state, vanishes (DELETED), or
        we time out.

        Default timeout is 30 minutes — large data disks routinely take
        ~minutes to reach 'available'; a 10-minute cap would falsely fail
        legitimate workflows. Callers can override.
        """
        deadline = time.time() + timeout
        last_state = None
        while time.time() < deadline:
            snap = self.get_snapshot(snapshot_id)
            if snap is None:
                if target_state == 'DELETED':
                    return None
                last_state = 'MISSING'
            else:
                last_state = _status_of(snap)
                if target_state == SNAPSHOT_STATE_AVAILABLE and last_state == SNAPSHOT_STATE_FAILED:
                    # Don't keep polling — the snapshot won't recover on its own.
                    raise Exception(
                        "Snapshot {} reached terminal state 'failed' while "
                        "waiting for 'available'".format(snapshot_id))
                if last_state == target_state:
                    return snap
                if target_state is None and last_state in _TERMINAL_CREATE:
                    return snap
            time.sleep(interval)
        raise Exception(
            "Timed out waiting for snapshot {} to reach state {} "
            "(last state: {})".format(snapshot_id, target_state, last_state))

    # ----- multi-volume / instance snapshot groups -----

    def create_snapshot_group(self, instance_id, name=None, description=None,
                              volume_ids=None, project_name=None, tags=None,
                              client_token=None):
        kwargs = {'instance_id': instance_id}
        if name is not None:
            kwargs['name'] = name
        if description is not None:
            kwargs['description'] = description
        if volume_ids:
            kwargs['volume_ids'] = volume_ids
        if project_name is not None:
            kwargs['project_name'] = project_name
        if client_token is not None:
            kwargs['client_token'] = client_token
        tag_models = _build_tags(tags, TagForCreateSnapshotGroupInput)
        if tag_models is not None:
            kwargs['tags'] = tag_models
        req = CreateSnapshotGroupRequest(**kwargs)
        try:
            return self._to_dict(self.api.create_snapshot_group(req))
        except ApiException as e:
            raise Exception(_format_api_error(
                "EBS CreateSnapshotGroup failed", e,
                {'instance_id': instance_id}))

    def describe_snapshot_groups(self, **kwargs):
        req = DescribeSnapshotGroupsRequest(**kwargs)
        try:
            return self._to_dict(self.api.describe_snapshot_groups(req))
        except ApiException as e:
            raise Exception(
                "EBS DescribeSnapshotGroups failed: {}".format(e.reason))

    def describe_all_snapshot_groups(self, **filters):
        """Paginated describe_snapshot_groups — returns flat list.

        Unlike DescribeSnapshots, this endpoint uses page_number/page_size
        cursoring, not next_token. We page until we get back fewer rows
        than page_size.
        """
        results = []
        page_size = filters.pop('page_size', 100)
        page_number = filters.pop('page_number', 1)
        while True:
            kwargs = dict(filters)
            kwargs['page_size'] = page_size
            kwargs['page_number'] = page_number
            resp = self.describe_snapshot_groups(**kwargs)
            page = (resp.get('snapshot_groups')
                    or resp.get('SnapshotGroups') or [])
            results.extend(page)
            if len(page) < page_size:
                break
            page_number += 1
        return results

    def find_snapshot_group_by_name(self, name, project_name=None):
        """Lookup snapshot group by exact name. Raises on multiple matches —
        Name is not enforced unique by the API."""
        filters = {'name': name}
        if project_name:
            filters['project_name'] = project_name
        matches = self.describe_all_snapshot_groups(**filters)
        exact = [
            g for g in matches
            if (g.get('name') or g.get('Name')) == name
        ]
        if len(exact) > 1:
            ids = [g.get('snapshot_group_id') or g.get('SnapshotGroupId')
                   for g in exact]
            hint = ("Pass snapshot_group_id to disambiguate"
                    if project_name
                    else "Pass snapshot_group_id, or set project_name to "
                         "scope the lookup")
            raise Exception(
                "Multiple snapshot groups match name '{}' ({}). {}.".format(
                    name, ids, hint))
        return exact[0] if exact else None

    def get_snapshot_group(self, snapshot_group_id):
        resp = self.describe_snapshot_groups(
            snapshot_group_ids=[snapshot_group_id])
        page = (resp.get('snapshot_groups')
                or resp.get('SnapshotGroups') or [])
        return page[0] if page else None

    def delete_snapshot_group(self, snapshot_group_id):
        req = DeleteSnapshotGroupRequest(snapshot_group_id=snapshot_group_id)
        try:
            return self._to_dict(self.api.delete_snapshot_group(req))
        except ApiException as e:
            raise Exception(_format_api_error(
                "EBS DeleteSnapshotGroup failed", e,
                {'snapshot_group_id': snapshot_group_id}))

    def rollback_snapshot_group(self, snapshot_group_id, instance_id=None,
                                snapshot_ids=None, volume_ids=None,
                                client_token=None):
        """Roll an instance back to a snapshot group.

        BytePlus requires the target instance to already be in STOPPED state
        for this call to succeed; callers are responsible for that check.
        We never auto-stop a running instance from inside this SDK helper —
        a snapshot rollback rewrites disks under the kernel, and silently
        powering off a running workload to do that is exactly the kind of
        surprise we don't want.
        """
        kwargs = {'snapshot_group_id': snapshot_group_id}
        if instance_id is not None:
            kwargs['instance_id'] = instance_id
        if snapshot_ids:
            kwargs['snapshot_ids'] = snapshot_ids
        if volume_ids:
            kwargs['volume_ids'] = volume_ids
        if client_token is not None:
            kwargs['client_token'] = client_token
        req = RollbackSnapshotGroupRequest(**kwargs)
        try:
            return self._to_dict(self.api.rollback_snapshot_group(req))
        except ApiException as e:
            raise Exception(_format_api_error(
                "EBS RollbackSnapshotGroup failed", e,
                {'snapshot_group_id': snapshot_group_id,
                 'instance_id': instance_id}))

    def wait_for_snapshot_group_state(self, snapshot_group_id,
                                      target_state=SNAPSHOT_STATE_AVAILABLE,
                                      timeout=1800, interval=10):
        """Same shape as wait_for_snapshot_state but for groups."""
        deadline = time.time() + timeout
        last_state = None
        while time.time() < deadline:
            grp = self.get_snapshot_group(snapshot_group_id)
            if grp is None:
                if target_state == 'DELETED':
                    return None
                last_state = 'MISSING'
            else:
                last_state = _status_of(grp)
                if target_state == SNAPSHOT_STATE_AVAILABLE and last_state == SNAPSHOT_STATE_FAILED:
                    raise Exception(
                        "Snapshot group {} reached terminal state 'failed' "
                        "while waiting for 'available'".format(snapshot_group_id))
                if last_state == target_state:
                    return grp
                if target_state is None and last_state in _TERMINAL_CREATE:
                    return grp
            time.sleep(interval)
        raise Exception(
            "Timed out waiting for snapshot group {} to reach state {} "
            "(last state: {})".format(
                snapshot_group_id, target_state, last_state))
