#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright BytePlus Inc.
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type


DOCUMENTATION = r'''
---
module: byteplus_security_group_rule
version_added: "1.0.0"
short_description: Manage individual rules on a BytePlus security group
description:
  - Authorize or revoke a single ingress or egress rule on a BytePlus VPC
    security group.
  - BytePlus does not assign rule IDs. A rule is identified by the tuple
    (direction, protocol, port_start, port_end, target, policy), where
    target is exactly one of cidr_ip, source_group_id, or prefix_list_id.
  - Description-only changes are pushed via ModifySecurityGroupRuleDescriptions
    so they do not interrupt in-flight traffic. Any other diff is a
    revoke + authorize cycle.
options:
  state:
    description: Desired state of the rule.
    type: str
    default: present
    choices: [present, absent]
  security_group_id:
    description: Target security group. Required.
    type: str
    required: true
  direction:
    description: Ingress (traffic into the SG) or egress (traffic out).
    type: str
    required: true
    choices: [ingress, egress]
  protocol:
    description:
      - Layer-4 protocol, or C(all) for any. Required.
    type: str
    required: true
    choices: [tcp, udp, icmp, icmpv6, all]
  port_start:
    description:
      - Start of the port range. Required for tcp/udp.
      - Use C(-1) for ICMP (any), or for protocol C(all).
    type: int
  port_end:
    description: End of the port range. Required for tcp/udp.
    type: int
  cidr_ip:
    description:
      - Source/destination CIDR (e.g. C(10.0.0.0/16) or C(::/0)).
      - Mutually exclusive with O(source_group_id) and O(prefix_list_id);
        exactly one is required.
    type: str
  source_group_id:
    description:
      - Reference another security group as the source/destination.
      - Mutually exclusive with O(cidr_ip) and O(prefix_list_id).
    type: str
  prefix_list_id:
    description:
      - Reference a prefix list.
      - Mutually exclusive with O(cidr_ip) and O(source_group_id).
    type: str
  policy:
    description: Whether the rule accepts or drops matching traffic.
    type: str
    default: accept
    choices: [accept, drop]
  priority:
    description: Rule priority (1=highest). BytePlus default is 1.
    type: int
  description:
    description: Free-form description. Changes are applied without revoke+authorize.
    type: str
  client_token:
    description: Idempotency token forwarded to AuthorizeSecurityGroup{Ingress,Egress}.
    type: str
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
- name: Allow HTTPS in from anywhere
  byteplus.cloud.byteplus_security_group_rule:
    security_group_id: sg-2d6jskeu1exxw58ozfd5xyz
    direction: ingress
    protocol: tcp
    port_start: 443
    port_end: 443
    cidr_ip: 0.0.0.0/0
    policy: accept
    description: Public HTTPS

- name: Allow internal traffic from another SG
  byteplus.cloud.byteplus_security_group_rule:
    security_group_id: sg-web
    direction: ingress
    protocol: tcp
    port_start: 8080
    port_end: 8080
    source_group_id: sg-bastion
    policy: accept

- name: Block one specific CIDR from talking to anything
  byteplus.cloud.byteplus_security_group_rule:
    security_group_id: sg-2d6jskeu1exxw58ozfd5xyz
    direction: ingress
    protocol: all
    port_start: -1
    port_end: -1
    cidr_ip: 198.51.100.0/24
    policy: drop
    priority: 1

- name: Revoke a rule
  byteplus.cloud.byteplus_security_group_rule:
    security_group_id: sg-2d6jskeu1exxw58ozfd5xyz
    direction: ingress
    protocol: tcp
    port_start: 22
    port_end: 22
    cidr_ip: 0.0.0.0/0
    state: absent
'''

RETURN = r'''
rule:
  description:
    - The matched rule, after the requested change is applied.
    - When state=absent and the rule existed, this is the rule before revocation.
  type: dict
  returned: when a matching rule exists
changed:
  description: Whether any change was made.
  type: bool
  returned: always
'''

import re

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.fardani235.byteplus.plugins.module_utils.vpc_common import (
    VPCClient,
    rule_matches,
    resolve_credentials,
)


# BytePlus VPC accepts a narrow charset for security-group-rule descriptions.
# Empirically: ASCII letters/digits, space, and the punctuation set below.
# Parentheses, brackets, colons, etc. yield "InvalidDescription.Malformed".
_DESCRIPTION_RE = re.compile(r'^[A-Za-z0-9 _./\-一-鿿]{1,255}$')


def _validate_description(p, module):
    desc = p.get('description')
    if desc is None or desc == '':
        return
    if not _DESCRIPTION_RE.match(desc):
        module.fail_json(
            msg=(
                "description {!r} contains characters BytePlus rejects. "
                "Allowed: letters, digits, spaces, underscore, dot, slash, "
                "hyphen, and Chinese chars. Length 1-255."
            ).format(desc))


# Fields forwarded to the SDK request. Everything else (state, direction,
# credentials) is handled separately in main().
_RULE_REQUEST_FIELDS = (
    'protocol', 'port_start', 'port_end',
    'cidr_ip', 'source_group_id', 'prefix_list_id',
    'policy', 'priority', 'description',
)


def _build_rule_dict(p, include_description=True):
    """Pull the rule fields out of module.params into a dict suitable for
    passing to authorize/revoke/modify_rule_description.
    """
    rule = {}
    for k in _RULE_REQUEST_FIELDS:
        if not include_description and k == 'description':
            continue
        v = p.get(k)
        if v is not None:
            rule[k] = v
    return rule


def _validate_target(p, module):
    targets = [t for t in ('cidr_ip', 'source_group_id', 'prefix_list_id')
               if p.get(t)]
    if len(targets) == 0:
        module.fail_json(
            msg="Exactly one of cidr_ip, source_group_id, prefix_list_id "
                "is required.")
    if len(targets) > 1:
        module.fail_json(
            msg="cidr_ip, source_group_id, and prefix_list_id are mutually "
                "exclusive (got: {}).".format(', '.join(targets)))


def _validate_ports(p, module):
    protocol = p.get('protocol')
    port_start, port_end = p.get('port_start'), p.get('port_end')
    if protocol not in ('tcp', 'udp'):
        return
    if port_start is None or port_end is None:
        module.fail_json(
            msg="port_start and port_end are required for protocol {}."
                .format(protocol))
        return  # unreachable; fail_json exits
    if port_start > port_end:
        module.fail_json(
            msg="port_start ({}) cannot exceed port_end ({}).".format(
                port_start, port_end))


def _find_existing(client, security_group_id, direction, candidate):
    """Return the matching rule dict from the live SG, or None."""
    existing_rules = client.describe_security_group_rules(
        security_group_id, direction=direction)
    for r in existing_rules:
        if rule_matches(r, candidate):
            return r
    return None


def _description_only_diff(existing, candidate):
    """True iff the candidate matches existing on identity fields AND the
    description differs. Avoids a revoke+authorize cycle for a no-traffic-
    impact change.
    """
    new_desc = candidate.get('description')
    if new_desc is None:
        return False
    cur_desc = existing.get('description') or existing.get('Description') or ''
    return new_desc != cur_desc


def _priority_drifted(existing, candidate):
    new_prio = candidate.get('priority')
    if new_prio is None:
        return False
    cur_prio = existing.get('priority') or existing.get('Priority')
    return new_prio != cur_prio


def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(type='str', default='present', choices=['present', 'absent']),
            security_group_id=dict(type='str', required=True),
            direction=dict(type='str', required=True, choices=['ingress', 'egress']),
            protocol=dict(type='str', required=True,
                          choices=['tcp', 'udp', 'icmp', 'icmpv6', 'all']),
            port_start=dict(type='int'),
            port_end=dict(type='int'),
            cidr_ip=dict(type='str'),
            source_group_id=dict(type='str'),
            prefix_list_id=dict(type='str'),
            policy=dict(type='str', default='accept', choices=['accept', 'drop']),
            priority=dict(type='int'),
            description=dict(type='str'),
            client_token=dict(type='str'),
            access_key=dict(type='str', no_log=True),
            secret_key=dict(type='str', no_log=True),
            session_token=dict(type='str', no_log=True),
            region=dict(type='str'),
        ),
        mutually_exclusive=[
            ('cidr_ip', 'source_group_id'),
            ('cidr_ip', 'prefix_list_id'),
            ('source_group_id', 'prefix_list_id'),
        ],
        supports_check_mode=True,
    )

    _validate_target(module.params, module)
    _validate_ports(module.params, module)
    _validate_description(module.params, module)

    ak, sk, region, st = resolve_credentials(module)
    try:
        client = VPCClient(ak, sk, region, session_token=st)
    except Exception as e:
        module.fail_json(msg="Failed to initialize VPC client: {}".format(str(e)))

    state = module.params['state']
    direction = module.params['direction']
    sg_id = module.params['security_group_id']

    candidate = _build_rule_dict(module.params)
    try:
        existing = _find_existing(client, sg_id, direction, candidate)
    except Exception as e:
        module.fail_json(msg=str(e))
        return  # unreachable

    if state == 'present':
        if existing:
            # Identity fields already match. Check for diffs we can apply
            # in place (description) versus diffs that need a re-authorize
            # (priority — BytePlus does not provide an in-place update).
            desc_diff = _description_only_diff(existing, candidate)
            prio_diff = _priority_drifted(existing, candidate)

            if not desc_diff and not prio_diff:
                module.exit_json(changed=False, rule=existing)

            if module.check_mode:
                module.exit_json(
                    changed=True, rule=existing,
                    msg="Would update rule (description_diff={}, priority_diff={})"
                        .format(desc_diff, prio_diff))

            if desc_diff and not prio_diff:
                # Update description in place — no traffic interruption.
                desc_payload = _build_rule_dict(module.params)
                try:
                    client.modify_rule_description(direction, sg_id, **desc_payload)
                except Exception as e:
                    module.fail_json(msg=str(e))
                    return  # unreachable
                module.exit_json(changed=True, rule={**existing,
                                                     'description': candidate['description']})

            # Priority changed: revoke then authorize. Description, if also
            # changed, rides along on the new authorize.
            try:
                revoke_payload = _build_rule_dict(module.params,
                                                  include_description=False)
                revoke_payload.pop('priority', None)  # not part of identity
                client.revoke_rule(direction, sg_id, **revoke_payload)
                client.authorize_rule(direction, sg_id, **candidate)
            except Exception as e:
                module.fail_json(msg=str(e))
                return  # unreachable
            module.exit_json(changed=True, rule=candidate)

        # No existing rule — authorize.
        if module.check_mode:
            module.exit_json(changed=True, rule=None, msg="Would authorize rule")
        try:
            client.authorize_rule(direction, sg_id, **candidate)
        except Exception as e:
            module.fail_json(msg=str(e))
            return  # unreachable
        module.exit_json(changed=True, rule=candidate)

    # state == 'absent'
    if not existing:
        module.exit_json(changed=False, rule=None,
                         msg="No matching rule; nothing to revoke")
    if module.check_mode:
        module.exit_json(changed=True, rule=existing, msg="Would revoke rule")
    revoke_payload = _build_rule_dict(module.params, include_description=False)
    revoke_payload.pop('priority', None)
    try:
        client.revoke_rule(direction, sg_id, **revoke_payload)
    except Exception as e:
        module.fail_json(msg=str(e))
        return  # unreachable
    module.exit_json(changed=True, rule=existing)


if __name__ == '__main__':
    main()
