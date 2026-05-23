from __future__ import absolute_import, division, print_function
__metaclass__ = type

import time

from byteplussdkcore.configuration import Configuration
from byteplussdkcore.api_client import ApiClient
from byteplussdkcore.rest import ApiException
from byteplussdkecs.api.ecs_api import ECSApi
from byteplussdkecs.models.run_instances_request import RunInstancesRequest
from byteplussdkecs.models.describe_instances_request import DescribeInstancesRequest
from byteplussdkecs.models.start_instances_request import StartInstancesRequest
from byteplussdkecs.models.stop_instances_request import StopInstancesRequest
from byteplussdkecs.models.reboot_instances_request import RebootInstancesRequest
from byteplussdkecs.models.delete_instances_request import DeleteInstancesRequest
from byteplussdkecs.models.volume_for_run_instances_input import VolumeForRunInstancesInput
from byteplussdkecs.models.network_interface_for_run_instances_input import (
    NetworkInterfaceForRunInstancesInput,
)
from byteplussdkecs.models.tag_for_run_instances_input import TagForRunInstancesInput
from byteplussdkecs.models.eip_address_for_run_instances_input import (
    EipAddressForRunInstancesInput,
)


def _format_api_error(prefix, e, extra=None):
    """Build a verbose ApiException message that includes the response body
    (where BytePlus puts the actual error code/message) and request context.
    The bare e.reason only ever says "Bad Request" / "Forbidden" — useless.
    """
    body = getattr(e, 'body', None)
    try:
        body = body.decode('utf-8') if isinstance(body, bytes) else body
    except Exception:
        pass
    parts = ["{}: {} (status={})".format(prefix, e.reason, e.status)]
    if body:
        parts.append("body={!r}".format(body))
    if extra:
        parts.append("ctx={!r}".format(extra))
    return ' '.join(parts)


# Allowed volume fields the user can pass via the `volumes` parameter.
# Any extra key is rejected — the SDK silently ignores unknown attributes,
# and we'd rather fail loudly than send a stripped payload.
_ALLOWED_VOLUME_FIELDS = frozenset({
    'volume_type', 'size', 'snapshot_id', 'delete_with_instance',
    'extra_performance_type_id', 'extra_performance_iops',
    'extra_performance_throughput_mb',
})

_ALLOWED_NIC_FIELDS = frozenset({
    'subnet_id', 'security_group_ids', 'primary_ip_address',
    'private_ip_addresses', 'ipv6_address_count',
})

_ALLOWED_TAG_FIELDS = frozenset({'key', 'value'})


def _build_volume_models(volumes):
    """Convert a list of dicts into VolumeForRunInstancesInput objects.

    Raw dicts are NOT serialized correctly by the SDK's request interceptor
    (it expects model objects so attribute_map can translate snake_case to
    the API's PascalCase keys).
    """
    if not volumes:
        return None
    out = []
    for i, v in enumerate(volumes):
        if not isinstance(v, dict):
            raise ValueError("volumes[{}] must be a dict".format(i))
        unknown = set(v) - _ALLOWED_VOLUME_FIELDS
        if unknown:
            raise ValueError(
                "volumes[{}] has unknown field(s): {}. Allowed: {}".format(
                    i, sorted(unknown), sorted(_ALLOWED_VOLUME_FIELDS)))
        if 'size' in v and not isinstance(v['size'], int):
            raise ValueError("volumes[{}].size must be an int (GiB)".format(i))
        if 'volume_type' not in v:
            raise ValueError(
                "volumes[{}].volume_type is required (e.g. ESSD_PL0, "
                "ESSD_FlexPL, PTSSD)".format(i))
        out.append(VolumeForRunInstancesInput(**v))
    return out


def _build_nic_models(network_interfaces):
    if not network_interfaces:
        return None
    out = []
    for i, n in enumerate(network_interfaces):
        if not isinstance(n, dict):
            raise ValueError("network_interfaces[{}] must be a dict".format(i))
        unknown = set(n) - _ALLOWED_NIC_FIELDS
        if unknown:
            raise ValueError(
                "network_interfaces[{}] has unknown field(s): {}".format(
                    i, sorted(unknown)))
        out.append(NetworkInterfaceForRunInstancesInput(**n))
    return out


def _build_tag_models(tags):
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
        out.append(TagForRunInstancesInput(**t))
    return out


_ALLOWED_EIP_FIELDS = {
    'bandwidth_mbps', 'bandwidth_package_id', 'charge_type', 'isp',
    'release_with_instance', 'security_protection_instance_id',
    'security_protection_types',
}


def _build_eip_model(eip):
    if not eip:
        return None
    if not isinstance(eip, dict):
        raise ValueError("eip_address must be a dict")
    unknown = set(eip) - _ALLOWED_EIP_FIELDS
    if unknown:
        raise ValueError(
            "eip_address has unknown field(s): {}. Allowed: {}".format(
                sorted(unknown), sorted(_ALLOWED_EIP_FIELDS)))
    # Strip None entries so we don't send explicit nulls.
    cleaned = {k: v for k, v in eip.items() if v is not None}
    return EipAddressForRunInstancesInput(**cleaned)


def build_run_request_models(volumes=None, network_interfaces=None, tags=None,
                             eip_address=None):
    """Public entry point used by the module — returns a dict of converted
    SDK request models, suitable for splatting into RunInstancesRequest kwargs.
    """
    out = {}
    vol_models = _build_volume_models(volumes)
    if vol_models is not None:
        out['volumes'] = vol_models
    nic_models = _build_nic_models(network_interfaces)
    if nic_models is not None:
        out['network_interfaces'] = nic_models
    tag_models = _build_tag_models(tags)
    if tag_models is not None:
        out['tags'] = tag_models
    eip_model = _build_eip_model(eip_address)
    if eip_model is not None:
        out['eip_address'] = eip_model
    return out


# Stable ECS instance lifecycle states from BytePlus ECS API.
# https://docs.byteplus.com/en/docs/ecs/api-reference (Status field)
INSTANCE_STATE_RUNNING = 'RUNNING'
INSTANCE_STATE_STOPPED = 'STOPPED'
INSTANCE_STATE_STARTING = 'STARTING'
INSTANCE_STATE_STOPPING = 'STOPPING'
INSTANCE_STATE_REBOOTING = 'REBOOTING'
INSTANCE_STATE_CREATING = 'CREATING'

# States that should terminate a wait loop: the instance reached a steady
# point and additional polling won't change anything.
_TERMINAL_OK = {INSTANCE_STATE_RUNNING, INSTANCE_STATE_STOPPED}


class ECSClient(object):
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
        # Build a dedicated ApiClient bound to THIS config so concurrent
        # callers don't share credentials via the process-wide default.
        self.api = ECSApi(api_client=ApiClient(configuration=config))

    @staticmethod
    def _to_dict(obj):
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        return obj

    def run_instances(self, **kwargs):
        req = RunInstancesRequest(**kwargs)
        try:
            resp = self.api.run_instances(req)
        except ApiException as e:
            # Strip secrets before echoing kwargs back to the user.
            safe_ctx = {k: v for k, v in kwargs.items()
                        if k not in ('password', 'user_data')}
            raise Exception(_format_api_error("ECS RunInstances failed", e, safe_ctx))
        return self._to_dict(resp)

    def describe_instances(self, **kwargs):
        req = DescribeInstancesRequest(**kwargs)
        try:
            resp = self.api.describe_instances(req)
        except ApiException as e:
            raise Exception("ECS DescribeInstances failed: {}".format(e.reason))
        return self._to_dict(resp)

    def describe_all_instances(self, **filters):
        """Paginated describe_instances. Returns the flat list of Instances."""
        results = []
        next_token = None
        page_size = filters.pop('max_results', 100)
        while True:
            kwargs = dict(filters)
            kwargs['max_results'] = page_size
            if next_token:
                kwargs['next_token'] = next_token
            resp = self.describe_instances(**kwargs)
            page = resp.get('instances') or resp.get('Instances') or []
            results.extend(page)
            next_token = resp.get('next_token') or resp.get('NextToken')
            if not next_token:
                break
        return results

    def find_instance_by_name(self, instance_name, zone_id=None,
                              project_name=None):
        """Look up a single instance by exact name. Returns dict or None.

        Raises if more than one match exists, because name is not unique
        in ECS — the caller must disambiguate with instance_id, or narrow
        the search with project_name / zone_id. The BytePlus project is
        the orthogonal grouping to region, so it's the natural tiebreaker
        when name collides across projects in the same account.
        """
        filters = {'instance_name': instance_name}
        if zone_id:
            filters['zone_id'] = zone_id
        if project_name:
            filters['project_name'] = project_name
        matches = self.describe_all_instances(**filters)
        # API filters by name as a prefix in some regions; enforce exact.
        exact = [
            i for i in matches
            if (i.get('instance_name') or i.get('InstanceName')) == instance_name
        ]
        if len(exact) > 1:
            ids = [i.get('instance_id') or i.get('InstanceId') for i in exact]
            hint = ("Pass instance_id to disambiguate"
                    if project_name
                    else "Pass instance_id, or set project_name to scope "
                         "the lookup to a single BytePlus project")
            raise Exception(
                "Multiple ECS instances match name '{}' ({}). {}.".format(
                    instance_name, ids, hint))
        return exact[0] if exact else None

    def get_instance(self, instance_id):
        resp = self.describe_instances(instance_ids=[instance_id])
        page = resp.get('instances') or resp.get('Instances') or []
        return page[0] if page else None

    def start_instances(self, instance_ids):
        req = StartInstancesRequest(instance_ids=instance_ids)
        try:
            return self._to_dict(self.api.start_instances(req))
        except ApiException as e:
            raise Exception("ECS StartInstances failed: {}".format(e.reason))

    def stop_instances(self, instance_ids, force_stop=False, stopped_mode=None):
        kwargs = {'instance_ids': instance_ids, 'force_stop': force_stop}
        if stopped_mode:
            kwargs['stopped_mode'] = stopped_mode
        req = StopInstancesRequest(**kwargs)
        try:
            return self._to_dict(self.api.stop_instances(req))
        except ApiException as e:
            raise Exception("ECS StopInstances failed: {}".format(e.reason))

    def reboot_instances(self, instance_ids, force_stop=False):
        req = RebootInstancesRequest(instance_ids=instance_ids, force_stop=force_stop)
        try:
            return self._to_dict(self.api.reboot_instances(req))
        except ApiException as e:
            raise Exception("ECS RebootInstances failed: {}".format(e.reason))

    def delete_instances(self, instance_ids, client_token=None):
        kwargs = {'instance_ids': instance_ids}
        if client_token:
            kwargs['client_token'] = client_token
        req = DeleteInstancesRequest(**kwargs)
        try:
            return self._to_dict(self.api.delete_instances(req))
        except ApiException as e:
            raise Exception("ECS DeleteInstances failed: {}".format(e.reason))

    def wait_for_state(self, instance_id, target_state, timeout=600, interval=5):
        """Poll until the instance reaches target_state, or raise on timeout.

        target_state is one of INSTANCE_STATE_RUNNING / INSTANCE_STATE_STOPPED
        (or None to wait until any terminal state).

        For target_state='DELETED', after the instance disappears from
        DescribeInstances we additionally sleep briefly so the underlying NIC
        has time to detach from its subnet/SG. Without this, immediate
        DeleteSubnet/DeleteSecurityGroup calls fail with DependencyViolation.
        """
        deadline = time.time() + timeout
        last_state = None
        while time.time() < deadline:
            inst = self.get_instance(instance_id)
            if inst is None:
                # Vanished — for a delete, that's success.
                if target_state == 'DELETED':
                    # Grace period for the NIC to release subnet/SG references.
                    time.sleep(15)
                    return None
                last_state = 'MISSING'
            else:
                last_state = inst.get('status') or inst.get('Status')
                if target_state is None and last_state in _TERMINAL_OK:
                    return inst
                if last_state == target_state:
                    return inst
            time.sleep(interval)
        raise Exception(
            "Timed out waiting for instance {} to reach state {} "
            "(last state: {})".format(instance_id, target_state, last_state))


def resolve_credentials(module):
    """Pull AK/SK/region from module params with env-var fallback. Fails
    the module cleanly if AK or SK is missing — never silently constructs
    an unauthenticated client.
    """
    import os
    access_key = module.params.get('access_key') or os.environ.get('BYTEPLUS_ACCESS_KEY')
    secret_key = module.params.get('secret_key') or os.environ.get('BYTEPLUS_SECRET_KEY')
    region = module.params.get('region') or os.environ.get('BYTEPLUS_REGION', 'ap-southeast-1')
    session_token = module.params.get('session_token') or os.environ.get('BYTEPLUS_SESSION_TOKEN')

    if not access_key or not secret_key:
        module.fail_json(
            msg="access_key and secret_key are required. Set them as module "
                "params or via BYTEPLUS_ACCESS_KEY / BYTEPLUS_SECRET_KEY env vars.")
    return access_key, secret_key, region, session_token
