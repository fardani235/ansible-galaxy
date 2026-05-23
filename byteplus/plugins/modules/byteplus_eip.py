#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright BytePlus Inc.
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type


DOCUMENTATION = r'''
---
module: byteplus_eip
version_added: "1.1.0"
short_description: Manage BytePlus Elastic IP addresses
description:
  - Allocate and release Elastic IPs.
  - Optionally associate the EIP to / disassociate it from an ECS instance
    in the same call. Use this when you need a public IP on an existing VM,
    or when you need to manage the EIP across the VM's lifecycle (the
    C(eip_address) sub-option on C(byteplus_ecs_instance) only handles
    allocate-at-launch).
  - Identified by C(allocation_id) or C(name) (uniqueness within the account
    is enforced by the module).
options:
  state:
    description:
      - C(present) ensures an EIP exists. Creates one if neither
        C(allocation_id) nor a matching C(name) is found.
      - When C(instance_id) is also set, additionally associates the EIP to
        that instance (idempotent).
      - C(absent) disassociates (if attached) and releases the EIP.
    type: str
    default: present
    choices: [present, absent]
  allocation_id:
    description: ID of an existing EIP. If set, used as the primary lookup key.
    type: str
  name:
    description: Display name. Used to look up an existing EIP when
                 C(allocation_id) is not given.
    type: str
  description:
    description: Free-form description (set on allocate / modify).
    type: str
  bandwidth_mbps:
    description: Peak bandwidth in Mbps.
    type: int
  bandwidth_package_id:
    description: Bind to an existing shared bandwidth package.
    type: str
  billing_type:
    description:
      - Billing model.
      - C(1) PostPaid by bandwidth, C(2) PostPaid by traffic, C(3) PrePaid.
      - BytePlus expects an integer; we surface the same int.
    type: int
    choices: [1, 2, 3]
  isp:
    description: ISP / carrier line, e.g. C(BGP).
    type: str
  ip_address:
    description: Specific IP to request from the pool.
    type: str
  ip_address_pool_id:
    description: EIP address pool to allocate from.
    type: str
  project_name:
    description: BytePlus project to place the EIP in.
    type: str
  tags:
    description: Tag list as C({key, value}) dicts.
    type: list
    elements: dict
  release_with_instance:
    description:
      - Set the EIP's release-with-instance flag.
      - When true, the EIP is automatically released when the instance it's
        attached to is deleted.
    type: bool
  instance_id:
    description:
      - When C(state=present), also associate the EIP to this instance.
      - When C(state=absent), the EIP is disassociated from this instance
        (if attached) before release.
    type: str
  instance_type:
    description: Instance kind to associate to.
    type: str
    default: EcsInstance
    choices: [EcsInstance, NetworkInterface, NatGW, ClbInstance, HaVip]
  client_token:
    description: Idempotency token.
    type: str
  wait:
    description: Wait for terminal state after allocate/associate/release.
    type: bool
    default: true
  wait_timeout:
    description: How long to wait, in seconds.
    type: int
    default: 180
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
  - fardani235
'''

EXAMPLES = r'''
- name: Allocate a new pay-by-traffic EIP
  fardani235.byteplus.byteplus_eip:
    name: web-eip
    billing_type: 2          # PostPaid by traffic
    bandwidth_mbps: 5
    isp: BGP
    state: present
  register: eip

- name: Allocate AND associate to an instance in one call
  fardani235.byteplus.byteplus_eip:
    name: web-eip
    billing_type: 2
    bandwidth_mbps: 5
    instance_id: i-abcd1234efgh
    state: present
  register: eip

- name: Disassociate and release
  fardani235.byteplus.byteplus_eip:
    allocation_id: "{{ eip.eip.allocation_id }}"
    instance_id: i-abcd1234efgh
    state: absent
'''

RETURN = r'''
eip:
  description: The EIP object as returned by DescribeEipAddresses.
  type: dict
  returned: when state=present
changed:
  description: Whether the operation made any change.
  type: bool
  returned: always
'''

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.fardani235.byteplus.plugins.module_utils.eip_common import (
    EIPClient,
)
from ansible_collections.fardani235.byteplus.plugins.module_utils.vpc_common import (
    resolve_credentials,
)


# Stable EIP statuses we may need to wait for.
_STATUS_AVAILABLE = 'Available'
_STATUS_ATTACHED = 'Attached'


# Fields we forward to AllocateEipAddress. Everything not in here is either
# handled separately (state, instance_*, credentials, wait_*) or unsupported.
_ALLOCATE_FIELDS = (
    'name', 'description', 'bandwidth_package_id', 'billing_type', 'isp',
    'ip_address', 'ip_address_pool_id', 'project_name', 'tags',
    'client_token',
)


def _allocate_kwargs(p):
    kwargs = {}
    for k in _ALLOCATE_FIELDS:
        v = p.get(k)
        if v is not None:
            kwargs[k] = v
    # AllocateEipAddress uses `bandwidth`, not `bandwidth_mbps`.
    bw = p.get('bandwidth_mbps')
    if bw is not None:
        kwargs['bandwidth'] = bw
    return kwargs


def _resolve_eip(module, client):
    aid = module.params.get('allocation_id')
    if aid:
        return client.get_eip(aid), aid
    name = module.params.get('name')
    if name:
        try:
            e = client.find_eip_by_name(name)
        except Exception as ex:
            module.fail_json(msg=str(ex))
            return None, None  # unreachable
        if e:
            return e, (e.get('allocation_id') or e.get('AllocationId'))
    return None, None


def _is_attached_to(eip, instance_id):
    if not instance_id:
        return False
    cur = (eip.get('instance_id') or eip.get('InstanceId') or '')
    return cur == instance_id


def _do_associate(module, client, allocation_id, eip):
    instance_id = module.params['instance_id']
    if _is_attached_to(eip, instance_id):
        return False, eip
    if module.check_mode:
        return True, eip
    try:
        client.associate_eip(
            allocation_id=allocation_id,
            instance_id=instance_id,
            instance_type=module.params['instance_type'],
            client_token=module.params.get('client_token'),
        )
    except Exception as e:
        module.fail_json(msg=str(e), allocation_id=allocation_id)
    if module.params['wait']:
        try:
            eip = client.wait_for_status(
                allocation_id, _STATUS_ATTACHED,
                timeout=module.params['wait_timeout'])
        except Exception as e:
            module.fail_json(msg=str(e), allocation_id=allocation_id)
    else:
        eip = client.get_eip(allocation_id)
    return True, eip


def _do_disassociate(module, client, allocation_id, eip):
    instance_id = module.params.get('instance_id')
    cur_instance = eip.get('instance_id') or eip.get('InstanceId')
    if not cur_instance:
        return False
    # If the caller passed an instance_id, only disassociate if it matches.
    # Otherwise, disassociate whatever is currently attached.
    if instance_id and cur_instance != instance_id:
        return False
    target = instance_id or cur_instance
    if module.check_mode:
        return True
    try:
        client.disassociate_eip(
            allocation_id=allocation_id,
            instance_id=target,
            instance_type=module.params['instance_type'],
            client_token=module.params.get('client_token'),
        )
    except Exception as e:
        module.fail_json(msg=str(e), allocation_id=allocation_id)
    if module.params['wait']:
        try:
            client.wait_for_status(
                allocation_id, _STATUS_AVAILABLE,
                timeout=module.params['wait_timeout'])
        except Exception as e:
            module.fail_json(msg=str(e), allocation_id=allocation_id)
    return True


def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(type='str', default='present', choices=['present', 'absent']),
            allocation_id=dict(type='str'),
            name=dict(type='str'),
            description=dict(type='str'),
            bandwidth_mbps=dict(type='int'),
            bandwidth_package_id=dict(type='str'),
            billing_type=dict(type='int', choices=[1, 2, 3]),
            isp=dict(type='str'),
            ip_address=dict(type='str'),
            ip_address_pool_id=dict(type='str'),
            project_name=dict(type='str'),
            tags=dict(type='list', elements='dict'),
            release_with_instance=dict(type='bool'),
            instance_id=dict(type='str'),
            instance_type=dict(type='str', default='EcsInstance',
                               choices=['EcsInstance', 'NetworkInterface',
                                        'NatGW', 'ClbInstance', 'HaVip']),
            client_token=dict(type='str'),
            wait=dict(type='bool', default=True),
            wait_timeout=dict(type='int', default=180),
            access_key=dict(type='str', no_log=True),
            secret_key=dict(type='str', no_log=True),
            session_token=dict(type='str', no_log=True),
            region=dict(type='str'),
        ),
        supports_check_mode=True,
    )

    ak, sk, region, st = resolve_credentials(module)
    try:
        client = EIPClient(ak, sk, region, session_token=st)
    except Exception as e:
        module.fail_json(msg="Failed to initialize EIP client: {}".format(str(e)))

    state = module.params['state']
    eip, allocation_id = _resolve_eip(module, client)
    changed = False

    if state == 'absent':
        if eip is None:
            module.exit_json(changed=False, eip=None,
                             msg="EIP not found; nothing to release")
        # Disassociate first if attached.
        if (eip.get('instance_id') or eip.get('InstanceId')):
            if _do_disassociate(module, client, allocation_id, eip):
                changed = True
        if module.check_mode:
            module.exit_json(changed=True, eip=eip)
        try:
            client.release_eip(allocation_id,
                               client_token=module.params.get('client_token'))
        except Exception as e:
            module.fail_json(msg=str(e), allocation_id=allocation_id)
        module.exit_json(changed=True, eip=None)

    # state == 'present'
    if eip is None:
        if module.check_mode:
            module.exit_json(changed=True, eip=None, msg="Would allocate EIP")
        try:
            result = client.allocate_eip(**_allocate_kwargs(module.params))
        except Exception as e:
            module.fail_json(msg=str(e))
            return  # unreachable
        allocation_id = result.get('allocation_id') or result.get('AllocationId')
        if not allocation_id:
            module.fail_json(
                msg="AllocateEipAddress returned no AllocationId: {!r}".format(result))
        # Wait for the EIP to be Available before any follow-on associate.
        if module.params['wait']:
            try:
                eip = client.wait_for_status(
                    allocation_id, _STATUS_AVAILABLE,
                    timeout=module.params['wait_timeout'])
            except Exception as e:
                module.fail_json(msg=str(e), allocation_id=allocation_id)
        else:
            eip = client.get_eip(allocation_id)
        changed = True

    # Apply release_with_instance / description / name drift if asked.
    modify_kwargs = {}
    rwi = module.params.get('release_with_instance')
    if rwi is not None and rwi != (
            eip.get('release_with_instance')
            if eip else None):
        modify_kwargs['release_with_instance'] = rwi
    new_desc = module.params.get('description')
    if new_desc is not None and new_desc != (
            (eip.get('description') if eip else '') or ''):
        modify_kwargs['description'] = new_desc
    new_name = module.params.get('name')
    if new_name is not None and eip and new_name != (
            eip.get('name') or ''):
        modify_kwargs['name'] = new_name
    new_bw = module.params.get('bandwidth_mbps')
    if new_bw is not None and eip and new_bw != (
            eip.get('bandwidth')):
        modify_kwargs['bandwidth'] = new_bw

    if modify_kwargs:
        if not module.check_mode:
            try:
                client.modify_eip(allocation_id, **modify_kwargs)
            except Exception as e:
                module.fail_json(msg=str(e), allocation_id=allocation_id)
            eip = client.get_eip(allocation_id)
        changed = True

    # Optional associate step.
    if module.params.get('instance_id'):
        did, eip = _do_associate(module, client, allocation_id, eip)
        if did:
            changed = True

    module.exit_json(changed=changed, eip=eip)


if __name__ == '__main__':
    main()
