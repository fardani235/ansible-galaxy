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
from byteplussdkvpc.api.vpc_api import VPCApi

from byteplussdkvpc.models.allocate_eip_address_request import AllocateEipAddressRequest
from byteplussdkvpc.models.associate_eip_address_request import AssociateEipAddressRequest
from byteplussdkvpc.models.disassociate_eip_address_request import (
    DisassociateEipAddressRequest,
)
from byteplussdkvpc.models.release_eip_address_request import ReleaseEipAddressRequest
from byteplussdkvpc.models.describe_eip_addresses_request import (
    DescribeEipAddressesRequest,
)
from byteplussdkvpc.models.modify_eip_address_attributes_request import (
    ModifyEipAddressAttributesRequest,
)
from byteplussdkvpc.models.tag_for_allocate_eip_address_input import (
    TagForAllocateEipAddressInput,
)


# Match the diagnostic style we already use in ecs_common.py / vpc_common.py.
def _format_api_error(prefix, e, ctx=None):
    body = getattr(e, 'body', None)
    try:
        body = body.decode('utf-8') if isinstance(body, bytes) else body
    except Exception:
        pass
    parts = ["{}: {} (status={})".format(prefix, e.reason, e.status)]
    if body:
        parts.append("body={!r}".format(body))
    if ctx:
        parts.append("ctx={!r}".format(ctx))
    return ' '.join(parts)


def _build_eip_tags(tags):
    if not tags:
        return None
    out = []
    for i, t in enumerate(tags):
        if not isinstance(t, dict) or 'key' not in t:
            raise ValueError("tags[{}] must be {{key, value}}".format(i))
        out.append(TagForAllocateEipAddressInput(**t))
    return out


class EIPClient(object):
    """Thin wrapper around byteplussdkvpc's EIP endpoints.

    The EIP API lives inside the VPC service in BytePlus — there is no
    separate eip_api module — so we instantiate VPCApi and call its
    `*_eip_address` methods.
    """

    def __init__(self, access_key, secret_key, region, session_token=None):
        self.config = Configuration()
        self.config.ak = access_key
        self.config.sk = secret_key
        self.config.region = region
        if session_token:
            self.config.session_token = session_token
        self.api = VPCApi(api_client=ApiClient(self.config))

    @staticmethod
    def _to_dict(obj):
        if obj is None:
            return None
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        return obj

    # ---------------------------------------------------------------- allocate
    def allocate_eip(self, **kwargs):
        tags = kwargs.pop('tags', None)
        if tags is not None:
            kwargs['tags'] = _build_eip_tags(tags)
        # Drop None values so we don't ship explicit nulls.
        cleaned = {k: v for k, v in kwargs.items() if v is not None}
        try:
            return self._to_dict(
                self.api.allocate_eip_address(AllocateEipAddressRequest(**cleaned)))
        except ApiException as e:
            raise Exception(_format_api_error(
                "VPC AllocateEipAddress failed", e, cleaned))

    # ----------------------------------------------------------- describe / get
    def describe_eips(self, **filters):
        cleaned = {k: v for k, v in filters.items() if v is not None}
        try:
            resp = self._to_dict(self.api.describe_eip_addresses(
                DescribeEipAddressesRequest(**cleaned)))
        except ApiException as e:
            raise Exception(_format_api_error(
                "VPC DescribeEipAddresses failed", e, cleaned))
        if not resp:
            return []
        return resp.get('eip_addresses') or resp.get('EipAddresses') or []

    def get_eip(self, allocation_id, wait_for_visible=True):
        """Fetch a single EIP by ID. Polls briefly so callers don't see
        spurious None right after AllocateEipAddress (read-after-create).
        """
        deadline = time.time() + 20 if wait_for_visible else 0
        while True:
            matches = self.describe_eips(allocation_ids=[allocation_id])
            if matches:
                return matches[0]
            if time.time() >= deadline:
                return None
            time.sleep(1)

    def find_eip_by_name(self, name):
        matches = self.describe_eips(name=name)
        exact = [e for e in matches
                 if (e.get('name') or e.get('Name')) == name]
        if len(exact) > 1:
            ids = [e.get('allocation_id') or e.get('AllocationId') for e in exact]
            raise Exception(
                "Multiple EIPs named '{}' ({}). Pass allocation_id to disambiguate."
                .format(name, ids))
        return exact[0] if exact else None

    # ---------------------------------------------------------------- modify
    def modify_eip(self, allocation_id, **kwargs):
        kwargs['allocation_id'] = allocation_id
        cleaned = {k: v for k, v in kwargs.items() if v is not None}
        try:
            return self._to_dict(self.api.modify_eip_address_attributes(
                ModifyEipAddressAttributesRequest(**cleaned)))
        except ApiException as e:
            raise Exception(_format_api_error(
                "VPC ModifyEipAddressAttributes failed", e, cleaned))

    # ------------------------------------------------------ associate/disassoc
    def associate_eip(self, allocation_id, instance_id, instance_type,
                      private_ip_address=None, client_token=None):
        kwargs = {
            'allocation_id': allocation_id,
            'instance_id': instance_id,
            'instance_type': instance_type,
        }
        if private_ip_address:
            kwargs['private_ip_address'] = private_ip_address
        if client_token:
            kwargs['client_token'] = client_token
        try:
            return self._to_dict(
                self.api.associate_eip_address(AssociateEipAddressRequest(**kwargs)))
        except ApiException as e:
            raise Exception(_format_api_error(
                "VPC AssociateEipAddress failed", e, kwargs))

    def disassociate_eip(self, allocation_id, instance_id, instance_type,
                         client_token=None):
        kwargs = {
            'allocation_id': allocation_id,
            'instance_id': instance_id,
            'instance_type': instance_type,
        }
        if client_token:
            kwargs['client_token'] = client_token
        try:
            return self._to_dict(self.api.disassociate_eip_address(
                DisassociateEipAddressRequest(**kwargs)))
        except ApiException as e:
            raise Exception(_format_api_error(
                "VPC DisassociateEipAddress failed", e, kwargs))

    # ---------------------------------------------------------------- release
    def release_eip(self, allocation_id, client_token=None):
        kwargs = {'allocation_id': allocation_id}
        if client_token:
            kwargs['client_token'] = client_token
        try:
            return self._to_dict(
                self.api.release_eip_address(ReleaseEipAddressRequest(**kwargs)))
        except ApiException as e:
            raise Exception(_format_api_error(
                "VPC ReleaseEipAddress failed", e, kwargs))

    # --------------------------------------------------------------- wait/poll
    def wait_for_status(self, allocation_id, target, timeout=180, interval=3):
        """Poll DescribeEipAddresses until the EIP reaches `target` (e.g.
        'Available', 'Attached'). Raises on timeout.

        BytePlus EIPs transition through states like Attaching/Detaching
        after associate/disassociate — callers that need a stable state
        should wait for the terminal state before returning.
        """
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            eip = self.get_eip(allocation_id, wait_for_visible=False)
            if eip is None:
                last = 'MISSING'
                if target == 'RELEASED':
                    return None
            else:
                last = eip.get('status') or eip.get('Status')
                if last == target:
                    return eip
            time.sleep(interval)
        raise Exception(
            "Timed out waiting for EIP {} to reach status {} "
            "(last status: {})".format(allocation_id, target, last))
