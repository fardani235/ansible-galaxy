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


def _format_api_error(prefix, e, ctx=None):
    """Build an ApiException message that includes status, response body,
    and request context. e.reason alone is "Bad Request"/"Forbidden" —
    useless for diagnosing BytePlus rejections.
    """
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
from byteplussdkcore.api_client import ApiClient
from byteplussdkcore.rest import ApiException
from byteplussdkvpc.api.vpc_api import VPCApi

from byteplussdkvpc.models.create_vpc_request import CreateVpcRequest
from byteplussdkvpc.models.delete_vpc_request import DeleteVpcRequest
from byteplussdkvpc.models.describe_vpcs_request import DescribeVpcsRequest
from byteplussdkvpc.models.modify_vpc_attributes_request import ModifyVpcAttributesRequest

from byteplussdkvpc.models.create_subnet_request import CreateSubnetRequest
from byteplussdkvpc.models.delete_subnet_request import DeleteSubnetRequest
from byteplussdkvpc.models.describe_subnets_request import DescribeSubnetsRequest
from byteplussdkvpc.models.modify_subnet_attributes_request import ModifySubnetAttributesRequest

from byteplussdkvpc.models.create_security_group_request import CreateSecurityGroupRequest
from byteplussdkvpc.models.delete_security_group_request import DeleteSecurityGroupRequest
from byteplussdkvpc.models.describe_security_groups_request import DescribeSecurityGroupsRequest
from byteplussdkvpc.models.modify_security_group_attributes_request import (
    ModifySecurityGroupAttributesRequest,
)

from byteplussdkvpc.models.tag_for_create_vpc_input import TagForCreateVpcInput
from byteplussdkvpc.models.tag_for_create_subnet_input import TagForCreateSubnetInput
from byteplussdkvpc.models.tag_for_create_security_group_input import (
    TagForCreateSecurityGroupInput,
)

from byteplussdkvpc.models.authorize_security_group_ingress_request import (
    AuthorizeSecurityGroupIngressRequest,
)
from byteplussdkvpc.models.authorize_security_group_egress_request import (
    AuthorizeSecurityGroupEgressRequest,
)
from byteplussdkvpc.models.revoke_security_group_ingress_request import (
    RevokeSecurityGroupIngressRequest,
)
from byteplussdkvpc.models.revoke_security_group_egress_request import (
    RevokeSecurityGroupEgressRequest,
)
from byteplussdkvpc.models.describe_security_group_attributes_request import (
    DescribeSecurityGroupAttributesRequest,
)
from byteplussdkvpc.models.modify_security_group_rule_descriptions_ingress_request import (
    ModifySecurityGroupRuleDescriptionsIngressRequest,
)
from byteplussdkvpc.models.modify_security_group_rule_descriptions_egress_request import (
    ModifySecurityGroupRuleDescriptionsEgressRequest,
)

from byteplussdkvpc.models.create_prefix_list_request import CreatePrefixListRequest
from byteplussdkvpc.models.delete_prefix_list_request import DeletePrefixListRequest
from byteplussdkvpc.models.describe_prefix_lists_request import DescribePrefixListsRequest
from byteplussdkvpc.models.describe_prefix_list_entries_request import (
    DescribePrefixListEntriesRequest,
)
from byteplussdkvpc.models.modify_prefix_list_request import ModifyPrefixListRequest
from byteplussdkvpc.models.prefix_list_entry_for_create_prefix_list_input import (
    PrefixListEntryForCreatePrefixListInput,
)
from byteplussdkvpc.models.add_prefix_list_entry_for_modify_prefix_list_input import (
    AddPrefixListEntryForModifyPrefixListInput,
)
from byteplussdkvpc.models.remove_prefix_list_entry_for_modify_prefix_list_input import (
    RemovePrefixListEntryForModifyPrefixListInput,
)
from byteplussdkvpc.models.tag_for_create_prefix_list_input import (
    TagForCreatePrefixListInput,
)

from byteplussdkvpc.models.create_route_table_request import CreateRouteTableRequest
from byteplussdkvpc.models.delete_route_table_request import DeleteRouteTableRequest
from byteplussdkvpc.models.describe_route_table_list_request import (
    DescribeRouteTableListRequest,
)
from byteplussdkvpc.models.modify_route_table_attributes_request import (
    ModifyRouteTableAttributesRequest,
)
from byteplussdkvpc.models.associate_route_table_request import AssociateRouteTableRequest
from byteplussdkvpc.models.disassociate_route_table_request import (
    DisassociateRouteTableRequest,
)
from byteplussdkvpc.models.tag_for_create_route_table_input import (
    TagForCreateRouteTableInput,
)

from byteplussdkvpc.models.create_route_entry_request import CreateRouteEntryRequest
from byteplussdkvpc.models.delete_route_entry_request import DeleteRouteEntryRequest
from byteplussdkvpc.models.describe_route_entry_list_request import (
    DescribeRouteEntryListRequest,
)
from byteplussdkvpc.models.modify_route_entry_request import ModifyRouteEntryRequest


# Route-entry next_hop_type translation. Users write snake_case in playbooks;
# BytePlus accepts a specific PascalCase set on the wire. We translate at the
# module boundary so the API spelling never leaks into playbooks.
NEXT_HOP_TYPE_MAP = {
    'instance': 'Instance',
    'network_interface': 'NetworkInterface',
    'nat_gateway': 'NatGW',
    'vpn_gateway': 'VpnGW',
    'transit_router': 'TransitRouter',
    'ipv6_gateway': 'IPv6Gateway',
    'ha_vip': 'HaVip',
    'private_link_vpc_endpoint': 'PrivateLinkVpcEndpoint',
    'ip_address': 'IpAddress',
}
NEXT_HOP_TYPE_REVERSE = {v: k for k, v in NEXT_HOP_TYPE_MAP.items()}


_ALLOWED_ENTRY_FIELDS = frozenset({'cidr', 'description'})


def _build_entries(entries, cls):
    """Wrap a list of {cidr, description} dicts into SDK input objects."""
    if not entries:
        return None
    out = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise ValueError("entries[{}] must be a dict".format(i))
        unknown = set(e) - _ALLOWED_ENTRY_FIELDS
        if unknown:
            raise ValueError(
                "entries[{}] has unknown field(s): {}. Allowed: cidr, description"
                .format(i, sorted(unknown)))
        if 'cidr' not in e:
            raise ValueError("entries[{}].cidr is required".format(i))
        out.append(cls(**e))
    return out


def diff_prefix_list_entries(existing, desired, purge=True):
    """Compute (add, remove, description_updates) given two lists of entry dicts.

    `existing`: list of {cidr, description} dicts read from
        DescribePrefixListEntries (snake_case or PascalCase).
    `desired`: list of user-supplied entry dicts.
    `purge`: when False, entries present in `existing` but missing from
        `desired` are kept untouched. When True (default), they're scheduled
        for removal so the prefix list converges to exactly `desired`.

    Returns (to_add, to_remove, to_update_description). Each is a list of
    entry dicts. `to_update_description` is the subset of CIDRs already
    present but with a different description — handled by listing them in
    `add_prefix_list_entries` since BytePlus's modify-prefix-list API
    treats re-adding an existing CIDR with a new description as an update.
    """
    def _norm(e):
        cidr = e.get('cidr') or e.get('Cidr')
        desc = e.get('description') or e.get('Description') or ''
        return cidr, desc

    existing_map = dict(_norm(e) for e in (existing or []))
    desired_map = dict(_norm(e) for e in (desired or []))

    to_add = []
    to_update_desc = []
    for cidr, desc in desired_map.items():
        if cidr not in existing_map:
            entry = {'cidr': cidr}
            if desc:
                entry['description'] = desc
            to_add.append(entry)
        elif existing_map[cidr] != desc:
            entry = {'cidr': cidr}
            if desc:
                entry['description'] = desc
            to_update_desc.append(entry)

    to_remove = []
    if purge:
        for cidr in existing_map:
            if cidr not in desired_map:
                to_remove.append({'cidr': cidr})

    return to_add, to_remove, to_update_desc


# Rule identity fields. BytePlus does not return a RuleId, so we compare
# the field tuple. Description is intentionally excluded from identity:
# changing only the description is handled via ModifyRuleDescriptions
# rather than revoke+authorize, which would lose the connection-tracking
# state and briefly drop in-flight traffic.
_RULE_IDENTITY_FIELDS = (
    'protocol', 'port_start', 'port_end',
    'cidr_ip', 'source_group_id', 'prefix_list_id',
    'policy',
)


def _normalize_rule_field(v):
    """Treat None and '' as the same absence, since BytePlus describes
    unset rule targets inconsistently across regions.
    """
    if v is None or v == '':
        return None
    return v


def rule_matches(existing, candidate):
    """Tuple-equality on identity fields. `existing` is a rule dict from
    DescribeSecurityGroupAttributes; `candidate` is the user's input as a dict.
    Both may use snake_case or PascalCase — we read snake_case first.
    """
    def _g(d, k):
        return _normalize_rule_field(d.get(k) or d.get(_snake_to_pascal(k)))

    for field in _RULE_IDENTITY_FIELDS:
        if _g(existing, field) != _normalize_rule_field(candidate.get(field)):
            return False
    return True


def _snake_to_pascal(s):
    return ''.join(p.capitalize() for p in s.split('_'))


_ALLOWED_TAG_FIELDS = frozenset({'key', 'value'})


def _build_tags(tags, tag_cls):
    """Wrap a list of {key, value} dicts into the appropriate Tag model class."""
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
        out.append(tag_cls(**t))
    return out


class VPCClient(object):
    """Wraps byteplussdkvpc.VPCApi with per-instance credentials.

    Uses a dedicated ApiClient bound to a local Configuration so concurrent
    callers don't share credentials via the process-wide default.
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
        self.api = VPCApi(api_client=ApiClient(configuration=config))

    @staticmethod
    def _to_dict(obj):
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        return obj

    # ----- Generic pagination -------------------------------------------------

    def _paginate(self, describe_fn, request_cls, **filters):
        """Pages through a describe API. Returns the flat list of resources.

        The BytePlus VPC APIs return both PascalCase and snake_case keys
        depending on serializer state; accept either.
        """
        results = []
        next_token = None
        page_size = filters.pop('max_results', 100)
        list_key_candidates = None  # determined from first response

        while True:
            kwargs = dict(filters)
            kwargs['max_results'] = page_size
            if next_token:
                kwargs['next_token'] = next_token

            req = request_cls(**kwargs)
            try:
                resp = self._to_dict(describe_fn(req))
            except ApiException as e:
                raise Exception("VPC describe failed: {}".format(e.reason))

            if list_key_candidates is None:
                list_key_candidates = [
                    k for k in resp
                    if isinstance(resp.get(k), list) and k.lower() != 'tag_filters'
                ]
            page = []
            for k in list_key_candidates:
                v = resp.get(k)
                if isinstance(v, list):
                    page = v
                    break
            results.extend(page)
            next_token = resp.get('next_token') or resp.get('NextToken')
            if not next_token:
                break
        return results

    # ----- VPC ---------------------------------------------------------------

    def create_vpc(self, **kwargs):
        tags = kwargs.pop('tags', None)
        if tags is not None:
            kwargs['tags'] = _build_tags(tags, TagForCreateVpcInput)
        try:
            return self._to_dict(self.api.create_vpc(CreateVpcRequest(**kwargs)))
        except ApiException as e:
            raise Exception("VPC CreateVpc failed: {}".format(e.reason))

    def delete_vpc(self, vpc_id):
        try:
            return self._to_dict(self.api.delete_vpc(DeleteVpcRequest(vpc_id=vpc_id)))
        except ApiException as e:
            raise Exception(_format_api_error("VPC DeleteVpc failed", e))

    def describe_vpcs(self, **filters):
        return self._paginate(self.api.describe_vpcs, DescribeVpcsRequest, **filters)

    def find_vpc_by_name(self, vpc_name, project_name=None):
        """Single-result name lookup, fail-closed on duplicates.

        VPC names aren't unique server-side; same disambiguation pattern as
        ECS — project_name narrows the search when name collides across
        BytePlus projects.
        """
        filters = {'vpc_name': vpc_name}
        if project_name:
            filters['project_name'] = project_name
        matches = self.describe_vpcs(**filters)
        # describe_vpcs filters by prefix in some regions — enforce exact.
        exact = [v for v in matches
                 if (v.get('vpc_name') or v.get('VpcName')) == vpc_name]
        if len(exact) > 1:
            ids = [v.get('vpc_id') or v.get('VpcId') for v in exact]
            hint = ("Pass vpc_id to disambiguate" if project_name
                    else "Pass vpc_id, or set project_name to scope the lookup")
            raise Exception(
                "Multiple VPCs match name '{}' ({}). {}.".format(vpc_name, ids, hint))
        return exact[0] if exact else None

    def get_vpc(self, vpc_id, wait_for_visible=True):
        deadline = time.time() + 20 if wait_for_visible else 0
        while True:
            matches = self.describe_vpcs(vpc_ids=[vpc_id])
            if matches:
                return matches[0]
            if time.time() >= deadline:
                return None
            time.sleep(1)

    def modify_vpc(self, vpc_id, **kwargs):
        kwargs['vpc_id'] = vpc_id
        try:
            return self._to_dict(
                self.api.modify_vpc_attributes(ModifyVpcAttributesRequest(**kwargs)))
        except ApiException as e:
            raise Exception("VPC ModifyVpcAttributes failed: {}".format(e.reason))

    # ----- Subnet ------------------------------------------------------------

    def create_subnet(self, **kwargs):
        tags = kwargs.pop('tags', None)
        if tags is not None:
            kwargs['tags'] = _build_tags(tags, TagForCreateSubnetInput)
        try:
            return self._to_dict(self.api.create_subnet(CreateSubnetRequest(**kwargs)))
        except ApiException as e:
            raise Exception("VPC CreateSubnet failed: {}".format(e.reason))

    def delete_subnet(self, subnet_id):
        try:
            return self._to_dict(
                self.api.delete_subnet(DeleteSubnetRequest(subnet_id=subnet_id)))
        except ApiException as e:
            raise Exception(_format_api_error("VPC DeleteSubnet failed", e))

    def describe_subnets(self, **filters):
        return self._paginate(
            self.api.describe_subnets, DescribeSubnetsRequest, **filters)

    def get_subnet(self, subnet_id, wait_for_visible=True):
        """Fetch a subnet by ID. Newly-created subnets can take a few seconds
        to appear in DescribeSubnets — poll briefly so callers don't see
        spurious None results right after create_subnet().
        """
        deadline = time.time() + 20 if wait_for_visible else 0
        while True:
            matches = self.describe_subnets(subnet_ids=[subnet_id])
            if matches:
                return matches[0]
            if time.time() >= deadline:
                return None
            time.sleep(1)

    def find_subnet_by_name(self, subnet_name, vpc_id, project_name=None):
        """Subnets are scoped to a VPC, so vpc_id is required. Names need
        not be unique across VPCs; within a VPC we still enforce uniqueness
        because nothing else in the API does.
        """
        if not vpc_id:
            raise ValueError("vpc_id is required when looking up a subnet by name")
        filters = {'vpc_id': vpc_id, 'subnet_name': subnet_name}
        if project_name:
            filters['project_name'] = project_name
        matches = self.describe_subnets(**filters)
        exact = [s for s in matches
                 if (s.get('subnet_name') or s.get('SubnetName')) == subnet_name]
        if len(exact) > 1:
            ids = [s.get('subnet_id') or s.get('SubnetId') for s in exact]
            raise Exception(
                "Multiple subnets named '{}' in VPC {} ({}). "
                "Pass subnet_id to disambiguate.".format(subnet_name, vpc_id, ids))
        return exact[0] if exact else None

    def modify_subnet(self, subnet_id, **kwargs):
        kwargs['subnet_id'] = subnet_id
        try:
            return self._to_dict(
                self.api.modify_subnet_attributes(ModifySubnetAttributesRequest(**kwargs)))
        except ApiException as e:
            raise Exception("VPC ModifySubnetAttributes failed: {}".format(e.reason))

    # ----- Security group ----------------------------------------------------

    def create_security_group(self, **kwargs):
        tags = kwargs.pop('tags', None)
        if tags is not None:
            kwargs['tags'] = _build_tags(tags, TagForCreateSecurityGroupInput)
        try:
            return self._to_dict(
                self.api.create_security_group(CreateSecurityGroupRequest(**kwargs)))
        except ApiException as e:
            raise Exception("VPC CreateSecurityGroup failed: {}".format(e.reason))

    def delete_security_group(self, security_group_id):
        try:
            return self._to_dict(self.api.delete_security_group(
                DeleteSecurityGroupRequest(security_group_id=security_group_id)))
        except ApiException as e:
            raise Exception(_format_api_error("VPC DeleteSecurityGroup failed", e))

    def describe_security_groups(self, **filters):
        return self._paginate(
            self.api.describe_security_groups,
            DescribeSecurityGroupsRequest, **filters)

    def get_security_group(self, security_group_id, wait_for_visible=True):
        deadline = time.time() + 20 if wait_for_visible else 0
        while True:
            matches = self.describe_security_groups(security_group_ids=[security_group_id])
            if matches:
                return matches[0]
            if time.time() >= deadline:
                return None
            time.sleep(1)

    def find_security_group_by_name(self, security_group_name, vpc_id,
                                    project_name=None):
        if not vpc_id:
            raise ValueError(
                "vpc_id is required when looking up a security group by name")
        filters = {
            'vpc_id': vpc_id,
            'security_group_names': [security_group_name],
        }
        if project_name:
            filters['project_name'] = project_name
        matches = self.describe_security_groups(**filters)
        exact = [g for g in matches
                 if (g.get('security_group_name') or g.get('SecurityGroupName'))
                 == security_group_name]
        if len(exact) > 1:
            ids = [g.get('security_group_id') or g.get('SecurityGroupId') for g in exact]
            raise Exception(
                "Multiple security groups named '{}' in VPC {} ({}). "
                "Pass security_group_id to disambiguate.".format(
                    security_group_name, vpc_id, ids))
        return exact[0] if exact else None

    def modify_security_group(self, security_group_id, **kwargs):
        kwargs['security_group_id'] = security_group_id
        try:
            return self._to_dict(self.api.modify_security_group_attributes(
                ModifySecurityGroupAttributesRequest(**kwargs)))
        except ApiException as e:
            raise Exception("VPC ModifySecurityGroupAttributes failed: {}".format(e.reason))

    # ----- Security group rules ----------------------------------------------

    def describe_security_group_rules(self, security_group_id, direction=None):
        """Return the list of rules attached to a security group.

        BytePlus's DescribeSecurityGroupAttributes returns the SG metadata
        plus a `permissions` list — each entry is a rule, with a `direction`
        field. We re-key to snake_case so downstream code can rely on it.
        """
        kwargs = {'security_group_id': security_group_id}
        if direction:
            kwargs['direction'] = direction
        try:
            resp = self._to_dict(self.api.describe_security_group_attributes(
                DescribeSecurityGroupAttributesRequest(**kwargs)))
        except ApiException as e:
            raise Exception(
                "VPC DescribeSecurityGroupAttributes failed: {}".format(e.reason))
        perms = resp.get('permissions') or resp.get('Permissions') or []
        return perms

    def authorize_rule(self, direction, security_group_id, **rule):
        rule['security_group_id'] = security_group_id
        if direction == 'ingress':
            req_cls = AuthorizeSecurityGroupIngressRequest
            fn = self.api.authorize_security_group_ingress
        elif direction == 'egress':
            req_cls = AuthorizeSecurityGroupEgressRequest
            fn = self.api.authorize_security_group_egress
        else:
            raise ValueError("direction must be 'ingress' or 'egress'")
        try:
            return self._to_dict(fn(req_cls(**rule)))
        except ApiException as e:
            body = getattr(e, 'body', None)
            try:
                body = body.decode('utf-8') if isinstance(body, bytes) else body
            except Exception:
                pass
            raise Exception(
                "VPC AuthorizeSecurityGroup{} failed: {} (status={}, body={!r}, rule={!r})".format(
                    direction.capitalize(), e.reason, e.status, body, rule))

    def revoke_rule(self, direction, security_group_id, **rule):
        rule['security_group_id'] = security_group_id
        # Revoke requests don't accept client_token, but they DO use the
        # same identity fields as Authorize. Strip anything the API rejects.
        rule.pop('client_token', None)
        if direction == 'ingress':
            req_cls = RevokeSecurityGroupIngressRequest
            fn = self.api.revoke_security_group_ingress
        elif direction == 'egress':
            req_cls = RevokeSecurityGroupEgressRequest
            fn = self.api.revoke_security_group_egress
        else:
            raise ValueError("direction must be 'ingress' or 'egress'")
        try:
            return self._to_dict(fn(req_cls(**rule)))
        except ApiException as e:
            raise Exception(
                "VPC RevokeSecurityGroup{} failed: {}".format(
                    direction.capitalize(), e.reason))

    def modify_rule_description(self, direction, security_group_id, **rule):
        """Update only the description of an existing rule, without revoke+
        authorize. The identity fields in `rule` must match an existing rule
        exactly; otherwise the API returns a not-found error.
        """
        rule['security_group_id'] = security_group_id
        if direction == 'ingress':
            req_cls = ModifySecurityGroupRuleDescriptionsIngressRequest
            fn = self.api.modify_security_group_rule_descriptions_ingress
        elif direction == 'egress':
            req_cls = ModifySecurityGroupRuleDescriptionsEgressRequest
            fn = self.api.modify_security_group_rule_descriptions_egress
        else:
            raise ValueError("direction must be 'ingress' or 'egress'")
        try:
            return self._to_dict(fn(req_cls(**rule)))
        except ApiException as e:
            raise Exception(
                "VPC ModifySecurityGroupRuleDescriptions{} failed: {}".format(
                    direction.capitalize(), e.reason))


    # ----- Prefix lists ------------------------------------------------------

    def create_prefix_list(self, **kwargs):
        tags = kwargs.pop('tags', None)
        if tags is not None:
            kwargs['tags'] = _build_tags(tags, TagForCreatePrefixListInput)
        entries = kwargs.pop('prefix_list_entries', None)
        if entries is not None:
            kwargs['prefix_list_entries'] = _build_entries(
                entries, PrefixListEntryForCreatePrefixListInput)
        try:
            return self._to_dict(
                self.api.create_prefix_list(CreatePrefixListRequest(**kwargs)))
        except ApiException as e:
            raise Exception("VPC CreatePrefixList failed: {}".format(e.reason))

    def delete_prefix_list(self, prefix_list_id):
        try:
            return self._to_dict(self.api.delete_prefix_list(
                DeletePrefixListRequest(prefix_list_id=prefix_list_id)))
        except ApiException as e:
            raise Exception("VPC DeletePrefixList failed: {}".format(e.reason))

    def describe_prefix_lists(self, **filters):
        return self._paginate(
            self.api.describe_prefix_lists, DescribePrefixListsRequest, **filters)

    def describe_prefix_list_entries(self, prefix_list_id):
        return self._paginate(
            self.api.describe_prefix_list_entries,
            DescribePrefixListEntriesRequest,
            prefix_list_id=prefix_list_id)

    def get_prefix_list(self, prefix_list_id):
        matches = self.describe_prefix_lists(prefix_list_ids=[prefix_list_id])
        return matches[0] if matches else None

    def find_prefix_list_by_name(self, prefix_list_name, project_name=None):
        filters = {'prefix_list_name': prefix_list_name}
        if project_name:
            filters['project_name'] = project_name
        matches = self.describe_prefix_lists(**filters)
        exact = [p for p in matches
                 if (p.get('prefix_list_name') or p.get('PrefixListName'))
                 == prefix_list_name]
        if len(exact) > 1:
            ids = [p.get('prefix_list_id') or p.get('PrefixListId') for p in exact]
            hint = ("Pass prefix_list_id to disambiguate" if project_name
                    else "Pass prefix_list_id, or set project_name to scope the lookup")
            raise Exception(
                "Multiple prefix lists match name '{}' ({}). {}.".format(
                    prefix_list_name, ids, hint))
        return exact[0] if exact else None

    def modify_prefix_list(self, prefix_list_id, prefix_list_name=None,
                           description=None, max_entries=None,
                           add_entries=None, remove_entries=None):
        kwargs = {'prefix_list_id': prefix_list_id}
        if prefix_list_name is not None:
            kwargs['prefix_list_name'] = prefix_list_name
        if description is not None:
            kwargs['description'] = description
        if max_entries is not None:
            kwargs['max_entries'] = max_entries
        if add_entries:
            kwargs['add_prefix_list_entries'] = _build_entries(
                add_entries, AddPrefixListEntryForModifyPrefixListInput)
        if remove_entries:
            # Remove entries only take a CIDR — drop any description sneaked in.
            cleaned = [{'cidr': e.get('cidr')} for e in remove_entries
                       if e.get('cidr')]
            kwargs['remove_prefix_list_entries'] = [
                RemovePrefixListEntryForModifyPrefixListInput(**e) for e in cleaned
            ]
        try:
            return self._to_dict(
                self.api.modify_prefix_list(ModifyPrefixListRequest(**kwargs)))
        except ApiException as e:
            raise Exception("VPC ModifyPrefixList failed: {}".format(e.reason))


    # ----- Route tables ------------------------------------------------------

    def create_route_table(self, **kwargs):
        tags = kwargs.pop('tags', None)
        if tags is not None:
            kwargs['tags'] = _build_tags(tags, TagForCreateRouteTableInput)
        try:
            return self._to_dict(
                self.api.create_route_table(CreateRouteTableRequest(**kwargs)))
        except ApiException as e:
            raise Exception(_format_api_error("VPC CreateRouteTable failed", e))

    def delete_route_table(self, route_table_id):
        try:
            return self._to_dict(self.api.delete_route_table(
                DeleteRouteTableRequest(route_table_id=route_table_id)))
        except ApiException as e:
            raise Exception(_format_api_error(
                "VPC DeleteRouteTable failed", e, ctx={'route_table_id': route_table_id}))

    def describe_route_tables(self, **filters):
        return self._paginate(
            self.api.describe_route_table_list,
            DescribeRouteTableListRequest, **filters)

    def get_route_table(self, route_table_id, wait_for_visible=True):
        deadline = time.time() + 20 if wait_for_visible else 0
        while True:
            # DescribeRouteTableList takes a single route_table_id, not a list.
            matches = self.describe_route_tables(route_table_id=route_table_id)
            if matches:
                return matches[0]
            if time.time() >= deadline:
                return None
            time.sleep(1)

    def find_route_table_by_name(self, route_table_name, vpc_id,
                                 project_name=None):
        """Route table names need not be unique across VPCs, so vpc_id is
        required. Within a VPC we still enforce uniqueness (BytePlus does
        not), matching how the rest of this client handles by-name lookup.
        """
        if not vpc_id:
            raise ValueError(
                "vpc_id is required when looking up a route table by name")
        filters = {'vpc_id': vpc_id, 'route_table_name': route_table_name}
        if project_name:
            filters['project_name'] = project_name
        matches = self.describe_route_tables(**filters)
        exact = [r for r in matches
                 if (r.get('route_table_name') or r.get('RouteTableName'))
                 == route_table_name]
        if len(exact) > 1:
            ids = [r.get('route_table_id') or r.get('RouteTableId') for r in exact]
            raise Exception(
                "Multiple route tables named '{}' in VPC {} ({}). "
                "Pass route_table_id to disambiguate.".format(
                    route_table_name, vpc_id, ids))
        return exact[0] if exact else None

    def modify_route_table(self, route_table_id, **kwargs):
        kwargs['route_table_id'] = route_table_id
        try:
            return self._to_dict(self.api.modify_route_table_attributes(
                ModifyRouteTableAttributesRequest(**kwargs)))
        except ApiException as e:
            raise Exception(
                "VPC ModifyRouteTableAttributes failed: {}".format(e.reason))

    def associate_route_table(self, route_table_id, subnet_id,
                              client_token=None):
        kwargs = {'route_table_id': route_table_id, 'subnet_id': subnet_id}
        if client_token:
            kwargs['client_token'] = client_token
        try:
            return self._to_dict(self.api.associate_route_table(
                AssociateRouteTableRequest(**kwargs)))
        except ApiException as e:
            raise Exception(_format_api_error(
                "VPC AssociateRouteTable failed", e,
                ctx={'route_table_id': route_table_id, 'subnet_id': subnet_id}))

    def disassociate_route_table(self, route_table_id, subnet_id):
        try:
            return self._to_dict(self.api.disassociate_route_table(
                DisassociateRouteTableRequest(
                    route_table_id=route_table_id, subnet_id=subnet_id)))
        except ApiException as e:
            raise Exception(_format_api_error(
                "VPC DisassociateRouteTable failed", e,
                ctx={'route_table_id': route_table_id, 'subnet_id': subnet_id}))

    # ----- Route entries -----------------------------------------------------

    def create_route_entry(self, **kwargs):
        try:
            return self._to_dict(
                self.api.create_route_entry(CreateRouteEntryRequest(**kwargs)))
        except ApiException as e:
            raise Exception(_format_api_error(
                "VPC CreateRouteEntry failed", e, ctx=kwargs))

    def delete_route_entry(self, route_entry_id):
        try:
            return self._to_dict(self.api.delete_route_entry(
                DeleteRouteEntryRequest(route_entry_id=route_entry_id)))
        except ApiException as e:
            raise Exception(_format_api_error(
                "VPC DeleteRouteEntry failed", e,
                ctx={'route_entry_id': route_entry_id}))

    def describe_route_entries(self, **filters):
        return self._paginate(
            self.api.describe_route_entry_list,
            DescribeRouteEntryListRequest, **filters)

    def modify_route_entry(self, route_entry_id, **kwargs):
        kwargs['route_entry_id'] = route_entry_id
        try:
            return self._to_dict(
                self.api.modify_route_entry(ModifyRouteEntryRequest(**kwargs)))
        except ApiException as e:
            raise Exception(
                "VPC ModifyRouteEntry failed: {}".format(e.reason))


def associated_subnet_ids(route_table):
    """Extract subnet IDs currently associated with a route table dict, in any
    of the case/shape variants BytePlus returns across regions. Public so
    modules can read associations without re-deriving the case-handling.
    """
    raw = (route_table.get('subnet_ids')
           or route_table.get('SubnetIds')
           or route_table.get('subnet_id')  # singular fallback some regions use
           or route_table.get('SubnetId')
           or [])
    if isinstance(raw, str):
        return [raw] if raw else []
    return list(raw)


def diff_route_table_associations(current, desired):
    """Return (to_associate, to_disassociate) given two iterables of subnet IDs.

    Order-independent set diff. Used by byteplus_route_table when the user
    supplies associated_subnet_ids and we need to converge from `current`
    (read from BytePlus) to `desired` (the playbook). When `desired` is None,
    the caller should skip association management entirely — that's not this
    helper's job to enforce.
    """
    cur = set(current or [])
    des = set(desired or [])
    return sorted(des - cur), sorted(cur - des)


def is_system_route_table(route_table):
    """True iff `route_table` (a dict from DescribeRouteTableList) is the
    VPC-provided default. BytePlus marks this as RouteTableType='System'.
    """
    t = (route_table.get('route_table_type')
         or route_table.get('RouteTableType'))
    return t == 'System'


def find_route_entry_match(entries, destination_cidr_block):
    """Return the entry dict matching the given CIDR, or None.

    BytePlus identifies a route entry uniquely within its table by
    destination_cidr_block (you cannot have two routes for the same CIDR
    in the same table). Accepts either case for the field key.
    """
    for e in entries or []:
        cidr = e.get('destination_cidr_block') or e.get('DestinationCidrBlock')
        if cidr == destination_cidr_block:
            return e
    return None


def resolve_credentials(module):
    """Shared credential resolver — mirrors ecs_common.resolve_credentials.
    Module-local copy so the two module_utils files have no inter-dependency.
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
