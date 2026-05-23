#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright BytePlus Inc.
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type


DOCUMENTATION = r'''
---
module: byteplus_ecs_instance
version_added: "1.0.0"
short_description: Manage BytePlus ECS instances
description:
  - Create, delete, start, stop, and reboot BytePlus ECS (Elastic Compute Service) instances.
  - Supports check mode and waits for the target lifecycle state.
  - An instance is identified by C(instance_id), or by C(instance_name) (which must be unique).
options:
  state:
    description:
      - Desired state.
      - C(present) ensures the instance exists; creates it if missing. Does not change power state.
      - C(absent) deletes the instance.
      - C(started) ensures the instance exists AND is running.
      - C(stopped) ensures the instance exists AND is stopped.
      - C(restarted) reboots a running instance (no-op if not running unless force=true).
    type: str
    default: present
    choices: [present, absent, started, stopped, restarted]
  instance_id:
    description:
      - ID of an existing instance. Required for C(absent)/C(started)/C(stopped)/C(restarted)
        if O(instance_name) is not provided.
    type: str
  instance_name:
    description:
      - Human-readable name. Used to look up an existing instance when O(instance_id)
        is not given. Must be unique within the zone for the lookup to succeed.
    type: str
  zone_id:
    description: Availability zone. Required when creating.
    type: str
  image_id:
    description: Image ID to launch from. Required when creating.
    type: str
  instance_type:
    description: Instance type spec (e.g. C(ecs.g1.large)). Required when creating.
    type: str
  password:
    description: Login password for the instance. Marked C(no_log).
    type: str
  key_pair_name:
    description: Name of an SSH key pair to inject at launch.
    type: str
  security_group_ids:
    description: Security group IDs to attach via the primary network interface.
    type: list
    elements: str
  subnet_id:
    description: Subnet (vSwitch) ID for the primary network interface.
    type: str
  user_data:
    description: Base64-encoded cloud-init / user data.
    type: str
  description:
    description: Free-form instance description.
    type: str
  host_name:
    description: OS hostname to set inside the guest.
    type: str
  project_name:
    description: BytePlus project to launch into.
    type: str
  tags:
    description: List of C({key, value}) tag dicts to attach at launch.
    type: list
    elements: dict
  volumes:
    description:
      - Positional list of volume specifications. The first entry is the
        system disk; subsequent entries are additional data disks.
      - Mutually exclusive with O(system_volume) and O(data_volumes) —
        use one form or the other, not both.
      - Volumes are validated client-side; unknown fields are rejected.
    type: list
    elements: dict
    suboptions:
      volume_type:
        description:
          - Storage class. Common values C(ESSD_PL0), C(ESSD_PL1), C(ESSD_PL2),
            C(ESSD_FlexPL), C(PTSSD). Required.
        type: str
        required: true
      size:
        description: Volume size in GiB.
        type: int
      snapshot_id:
        description: Snapshot to clone the volume from.
        type: str
      delete_with_instance:
        description: If C(true), the volume is deleted when the instance is deleted.
        type: bool
      extra_performance_type_id:
        description: For elastic-perf ESSDs, the perf upgrade tier.
        type: str
      extra_performance_iops:
        description: Provisioned IOPS uplift on top of the base tier.
        type: int
      extra_performance_throughput_mb:
        description: Provisioned throughput uplift (MB/s).
        type: int
  system_volume:
    description:
      - System disk specification. Cleaner alternative to passing the first
        element of O(volumes).
      - Mutually exclusive with O(volumes).
      - Same field schema as a single entry in O(volumes).
    type: dict
  data_volumes:
    description:
      - List of data disk specifications (everything other than the system disk).
      - Mutually exclusive with O(volumes).
      - Same field schema as entries in O(volumes).
    type: list
    elements: dict
  network_interfaces:
    description:
      - Explicit list of network interface specs. If you also set
        O(subnet_id)/O(security_group_ids), they are used to build the
        primary NIC only when this is not provided.
    type: list
    elements: dict
    suboptions:
      subnet_id:
        description: Subnet ID for this NIC.
        type: str
      security_group_ids:
        description: Security group IDs to attach to this NIC.
        type: list
        elements: str
      primary_ip_address:
        description: Fixed primary private IP.
        type: str
      private_ip_addresses:
        description: Additional private IPs.
        type: list
        elements: str
      ipv6_address_count:
        description: Number of IPv6 addresses to auto-allocate.
        type: int
  eip_address:
    description:
      - Atomically allocate and attach an Elastic IP at launch time.
      - Only honored on initial create; ignored when the instance already exists.
      - "Set C(release_with_instance: true) to have the EIP automatically released
        when the instance is deleted (recommended for smoke tests / ephemeral VMs)."
    type: dict
    suboptions:
      charge_type:
        description: EIP billing model.
        type: str
        choices: [PostPaidByBandwidth, PostPaidByTraffic, PrePaid]
      bandwidth_mbps:
        description: Bandwidth peak in Mbps.
        type: int
      bandwidth_package_id:
        description: Existing shared bandwidth package to bind to.
        type: str
      isp:
        description: ISP / carrier line, e.g. C(BGP).
        type: str
      release_with_instance:
        description: Release the EIP when the instance is deleted.
        type: bool
      security_protection_instance_id:
        description: Anti-DDoS instance ID to attach.
        type: int
      security_protection_types:
        description: Anti-DDoS protection tiers (list of strings).
        type: list
        elements: str
  instance_charge_type:
    description: Charge type. C(PostPaid) (default) or C(PrePaid).
    type: str
    choices: [PostPaid, PrePaid]
  count:
    description: Number of instances to launch (only honored on create when no instance_id/name match).
    type: int
    default: 1
  client_token:
    description: Idempotency token forwarded to RunInstances/DeleteInstances.
    type: str
  force:
    description:
      - For C(stopped)/C(restarted), pass C(true) to force-stop a running instance.
    type: bool
    default: false
  stopped_mode:
    description: Optional stopped_mode passed through to StopInstances (e.g. C(KeepCharging), C(StopCharging)).
    type: str
  wait:
    description: Wait for the target lifecycle state before returning.
    type: bool
    default: true
  wait_timeout:
    description: How long to wait, in seconds.
    type: int
    default: 600
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
- name: Launch a single ECS instance
  fardani235.byteplus.byteplus_ecs_instance:
    instance_name: web-01
    zone_id: ap-southeast-1a
    image_id: image-ybvz29l3da0smmpnfb02
    instance_type: ecs.g1.large
    subnet_id: subnet-abcdefg
    security_group_ids:
      - sg-1234567
    key_pair_name: my-keypair
    state: started

- name: Launch with a 100 GiB system disk and a 500 GiB data disk
  fardani235.byteplus.byteplus_ecs_instance:
    instance_name: db-01
    zone_id: ap-southeast-1a
    image_id: image-ybvz29l3da0smmpnfb02
    instance_type: ecs.g1.xlarge
    subnet_id: subnet-abcdefg
    security_group_ids: [sg-1234567]
    volumes:
      - volume_type: ESSD_PL0
        size: 100
        delete_with_instance: true
      - volume_type: ESSD_PL1
        size: 500
        delete_with_instance: false
    tags:
      - key: env
        value: prod
    state: started

- name: Same shape, using the system_volume/data_volumes split form
  fardani235.byteplus.byteplus_ecs_instance:
    instance_name: db-02
    zone_id: ap-southeast-1a
    image_id: image-ybvz29l3da0smmpnfb02
    instance_type: ecs.g1.xlarge
    subnet_id: subnet-abcdefg
    security_group_ids: [sg-1234567]
    system_volume:
      volume_type: ESSD_PL0
      size: 100
      delete_with_instance: true
    data_volumes:
      - volume_type: ESSD_PL1
        size: 500
        delete_with_instance: false
    state: started

- name: Stop an instance
  fardani235.byteplus.byteplus_ecs_instance:
    instance_id: i-ybw0lke12345
    state: stopped

- name: Force-reboot
  fardani235.byteplus.byteplus_ecs_instance:
    instance_id: i-ybw0lke12345
    state: restarted
    force: true

- name: Delete an instance and wait
  fardani235.byteplus.byteplus_ecs_instance:
    instance_id: i-ybw0lke12345
    state: absent
    wait: true
'''

RETURN = r'''
instance:
  description: Full description of the (resolved or created) instance, or null on delete.
  type: dict
  returned: when state != absent
changed:
  description: Whether any change was made.
  type: bool
  returned: always
'''

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.fardani235.byteplus.plugins.module_utils.ecs_common import (
    ECSClient,
    INSTANCE_STATE_RUNNING,
    INSTANCE_STATE_STOPPED,
    build_run_request_models,
    resolve_credentials,
)


def _resolve_instance(module, client):
    """Return (instance_dict_or_None, instance_id_or_None)."""
    instance_id = module.params.get('instance_id')
    name = module.params.get('instance_name')
    zone_id = module.params.get('zone_id')

    if instance_id:
        inst = client.get_instance(instance_id)
        return inst, instance_id
    if name:
        try:
            inst = client.find_instance_by_name(
                name,
                zone_id=zone_id,
                project_name=module.params.get('project_name'),
            )
        except Exception as e:
            module.fail_json(msg=str(e))
            return None, None  # unreachable; fail_json exits
        if inst:
            return inst, inst.get('instance_id') or inst.get('InstanceId')
    return None, None


def _state_of(inst):
    return inst.get('status') or inst.get('Status') if inst else None


def _resolve_volumes(volumes, system_volume, data_volumes):
    """Merge volume inputs into a single positional list.

    The argument_spec marks `volumes` mutually exclusive with the split form,
    so at most one branch fires. Returns None when neither was provided.
    """
    if volumes:
        return volumes
    if not system_volume and not data_volumes:
        return None
    out = []
    if system_volume:
        out.append(system_volume)
    if data_volumes:
        out.extend(data_volumes)
    return out


def _build_run_kwargs(module):
    p = module.params
    required_for_create = ('zone_id', 'image_id', 'instance_type')
    missing = [k for k in required_for_create if not p.get(k)]
    if missing:
        module.fail_json(
            msg="Missing required params for creating an ECS instance: {}"
                .format(', '.join(missing)))

    kwargs = {
        'zone_id': p['zone_id'],
        'image_id': p['image_id'],
        'instance_type': p['instance_type'],
        'count': p['count'],
        'min_count': p['count'],
    }
    optional_passthrough = (
        'instance_name', 'host_name', 'password', 'key_pair_name',
        'user_data', 'description', 'project_name',
        'instance_charge_type', 'client_token',
    )
    for k in optional_passthrough:
        v = p.get(k)
        if v is not None:
            kwargs[k] = v

    # Map our flat security_group_ids/subnet_id into a network_interfaces
    # entry — but only if the user didn't already supply explicit NICs.
    network_interfaces = p.get('network_interfaces')
    if not network_interfaces:
        nic_spec = {}
        if p.get('subnet_id'):
            nic_spec['subnet_id'] = p['subnet_id']
        if p.get('security_group_ids'):
            nic_spec['security_group_ids'] = p['security_group_ids']
        if nic_spec:
            network_interfaces = [nic_spec]

    volumes = _resolve_volumes(p.get('volumes'),
                               p.get('system_volume'),
                               p.get('data_volumes'))

    # Convert volumes / NICs / tags from plain dicts to the SDK's typed
    # request models. This is required: the SDK serializes raw dicts with
    # snake_case keys (wire format is PascalCase), so unwrapped dicts get
    # silently dropped by the server. Validate fields here too — clearer
    # errors than the server's "unknown parameter" replies.
    try:
        kwargs.update(build_run_request_models(
            volumes=volumes,
            network_interfaces=network_interfaces,
            tags=p.get('tags'),
            eip_address=p.get('eip_address'),
        ))
    except ValueError as e:
        module.fail_json(msg=str(e))

    return kwargs


def _do_create(module, client, _exit=True):
    """Launch a new ECS instance.

    Normally exits the module with the result. Pass _exit=False to return
    the new instance_id so the caller can chain a follow-on action
    (e.g. state=stopped needs to create THEN stop).
    """
    if module.check_mode:
        if _exit:
            module.exit_json(changed=True, instance=None, msg="Would create ECS instance")
        return None
    kwargs = _build_run_kwargs(module)
    result = client.run_instances(**kwargs)
    ids = result.get('instance_ids') or result.get('InstanceIds') or []
    if not ids:
        module.fail_json(msg="RunInstances returned no instance IDs: {}".format(result))
    instance_id = ids[0]
    inst = None
    if module.params['wait']:
        try:
            inst = client.wait_for_state(
                instance_id, INSTANCE_STATE_RUNNING,
                timeout=module.params['wait_timeout'])
        except Exception as e:
            module.fail_json(msg=str(e), instance_id=instance_id)
    else:
        inst = client.get_instance(instance_id)
    if _exit:
        module.exit_json(changed=True, instance=inst)
    return instance_id


def _transition(module, client, instance_id, current_state, target_action):
    """target_action is 'start' | 'stop' | 'reboot'."""
    if target_action == 'start':
        if current_state == INSTANCE_STATE_RUNNING:
            return False
        if module.check_mode:
            return True
        client.start_instances([instance_id])
        if module.params['wait']:
            client.wait_for_state(instance_id, INSTANCE_STATE_RUNNING,
                                  timeout=module.params['wait_timeout'])
        return True
    if target_action == 'stop':
        if current_state == INSTANCE_STATE_STOPPED:
            return False
        if module.check_mode:
            return True
        client.stop_instances([instance_id], force_stop=module.params['force'],
                              stopped_mode=module.params.get('stopped_mode'))
        if module.params['wait']:
            client.wait_for_state(instance_id, INSTANCE_STATE_STOPPED,
                                  timeout=module.params['wait_timeout'])
        return True
    if target_action == 'reboot':
        # Only meaningful from RUNNING. From STOPPED, a reboot is undefined;
        # require force to mean "stop-then-start" semantically — but the
        # underlying API rejects reboot-on-stopped, so we surface that.
        if current_state != INSTANCE_STATE_RUNNING and not module.params['force']:
            module.fail_json(
                msg="Cannot reboot instance in state {}; pass force=true to "
                    "force, or start it first.".format(current_state))
        if module.check_mode:
            return True
        client.reboot_instances([instance_id], force_stop=module.params['force'])
        if module.params['wait']:
            client.wait_for_state(instance_id, INSTANCE_STATE_RUNNING,
                                  timeout=module.params['wait_timeout'])
        return True
    raise AssertionError("unreachable target_action: {}".format(target_action))


def main():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(type='str', default='present',
                       choices=['present', 'absent', 'started', 'stopped', 'restarted']),
            instance_id=dict(type='str'),
            instance_name=dict(type='str'),
            zone_id=dict(type='str'),
            image_id=dict(type='str'),
            instance_type=dict(type='str'),
            password=dict(type='str', no_log=True),
            key_pair_name=dict(type='str'),
            security_group_ids=dict(type='list', elements='str'),
            subnet_id=dict(type='str'),
            user_data=dict(type='str'),
            description=dict(type='str'),
            host_name=dict(type='str'),
            project_name=dict(type='str'),
            tags=dict(type='list', elements='dict'),
            volumes=dict(type='list', elements='dict'),
            system_volume=dict(type='dict'),
            data_volumes=dict(type='list', elements='dict'),
            network_interfaces=dict(type='list', elements='dict'),
            eip_address=dict(type='dict', options=dict(
                bandwidth_mbps=dict(type='int'),
                bandwidth_package_id=dict(type='str'),
                charge_type=dict(type='str',
                                 choices=['PostPaidByBandwidth',
                                          'PostPaidByTraffic',
                                          'PrePaid']),
                isp=dict(type='str'),
                release_with_instance=dict(type='bool'),
                security_protection_instance_id=dict(type='int'),
                security_protection_types=dict(type='list', elements='str'),
            )),
            instance_charge_type=dict(type='str', choices=['PostPaid', 'PrePaid']),
            count=dict(type='int', default=1),
            client_token=dict(type='str'),
            force=dict(type='bool', default=False),
            stopped_mode=dict(type='str'),
            wait=dict(type='bool', default=True),
            wait_timeout=dict(type='int', default=600),
            access_key=dict(type='str', no_log=True),
            secret_key=dict(type='str', no_log=True),
            session_token=dict(type='str', no_log=True),
            region=dict(type='str'),
        ),
        mutually_exclusive=[
            # Pick one volume-input style — combining them is ambiguous
            # (does data_volumes append to volumes? prepend? replace?).
            ('volumes', 'system_volume'),
            ('volumes', 'data_volumes'),
        ],
        supports_check_mode=True,
    )

    ak, sk, region, st = resolve_credentials(module)
    try:
        client = ECSClient(ak, sk, region, session_token=st)
    except Exception as e:
        module.fail_json(msg="Failed to initialize ECS client: {}".format(str(e)))

    state = module.params['state']
    inst, instance_id = _resolve_instance(module, client)

    if state == 'present':
        if inst:
            module.exit_json(changed=False, instance=inst)
        _do_create(module, client)
        return  # _do_create exits

    # For all non-present states, we need an existing instance.
    if state == 'absent':
        if not inst:
            module.exit_json(changed=False, instance=None,
                             msg="Instance not found; nothing to delete")
        if module.check_mode:
            module.exit_json(changed=True, instance=inst,
                             msg="Would delete instance {}".format(instance_id))
        try:
            client.delete_instances([instance_id],
                                    client_token=module.params.get('client_token'))
        except Exception as e:
            module.fail_json(msg=str(e), instance_id=instance_id)
        if module.params['wait']:
            try:
                client.wait_for_state(instance_id, 'DELETED',
                                      timeout=module.params['wait_timeout'])
            except Exception as e:
                module.fail_json(msg=str(e), instance_id=instance_id)
        module.exit_json(changed=True, instance=None)

    # started/stopped/restarted: create-if-missing (matches the module's
    # documented "ensures the instance exists AND is running/stopped"
    # contract), then transition to the requested power state.
    if not inst:
        if state == 'restarted':
            # Restarting a non-existent instance has no sensible meaning.
            module.fail_json(
                msg="No instance found for state=restarted; provide "
                    "instance_id or an existing instance_name.")
        # _do_create exits the module on success — but only after the
        # instance is in RUNNING state, which is fine for state=started.
        # For state=stopped we still need to stop it afterwards, so we
        # can't let _do_create exit. Inline the create here and then
        # fall through.
        if state == 'started':
            _do_create(module, client)
            return  # _do_create exits

        # state == 'stopped': create, then stop.
        new_id = _do_create(module, client, _exit=False)
        inst = client.get_instance(new_id)
        instance_id = new_id

    action_map = {'started': 'start', 'stopped': 'stop', 'restarted': 'reboot'}
    changed = _transition(module, client, instance_id, _state_of(inst),
                          action_map[state])
    inst_after = client.get_instance(instance_id) if not module.check_mode else inst
    module.exit_json(changed=changed, instance=inst_after)


if __name__ == '__main__':
    main()
