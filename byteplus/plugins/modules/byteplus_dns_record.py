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
module: byteplus_dns_record
version_added: 1.0.0
short_description: Manage DNS records in BytePlus DNS
description:
  - Create, update, and delete DNS records (A, AAAA, CNAME, MX, TXT, NS, SRV, CAA) in BytePlus DNS.
  - Supports idempotent operations - only makes changes when necessary.
  - Can identify a zone by zone_id or domain_name.
  - Can identify a record by record_id or by (zone_id/domain_name + host + record_type).
author: BytePlus
options:
  access_key:
    description:
      - BytePlus Access Key.
      - Can also be set via C(BYTEPLUS_ACCESS_KEY) environment variable.
    type: str
    required: false
  secret_key:
    description:
      - BytePlus Secret Key.
      - Can also be set via C(BYTEPLUS_SECRET_KEY) environment variable.
    type: str
    required: false
    no_log: true
  region:
    description:
      - BytePlus region.
    type: str
    default: ap-southeast-1
  zone_id:
    description:
      - The ID of the domain (zone) in BytePlus DNS.
      - Either this or O(domain_name) is required when O(record_id) is not provided.
    type: int
    required: false
  domain_name:
    description:
      - The domain name (e.g. example.com) to look up the zone ID automatically.
      - Either this or O(zone_id) is required when O(record_id) is not provided.
    type: str
    required: false
  state:
    description:
      - Desired state of the DNS record.
      - C(present) ensures the record exists with the specified parameters.
      - C(absent) ensures the record does not exist.
    type: str
    default: present
    choices: [present, absent]
  record_type:
    description:
      - The DNS record type.
      - Required when O(state=present) and O(record_id) is not provided.
    type: str
    required: false
    choices: [A, AAAA, CNAME, MX, TXT, NS, SRV, CAA]
  host:
    description:
      - The host/subdomain prefix (e.g. C(www) for www.example.com).
      - Use C(@) for the root domain.
      - Required when O(state=present) and O(record_id) is not provided.
    type: str
    required: false
  value:
    description:
      - The record value. IP address for A/AAAA records, target domain for CNAME, etc.
      - Required when O(state=present) and O(record_id) is not provided.
    type: str
    required: false
  record_id:
    description:
      - The ID of an existing DNS record.
      - Use this to update or delete a known record directly without specifying zone or host.
    type: str
    required: false
  ttl:
    description:
      - Time-To-Live for the DNS record, in seconds.
      - Must be between 1 and 86400.
    type: int
    default: 600
  line:
    description:
      - The DNS line (e.g. C(default), C(CT), C(CU), C(CM)).
      - When unset on an update-by-record_id, the existing line is preserved.
      - When unset on record creation, C(default) is used.
    type: str
    required: false
  delete_all:
    description:
      - When O(state=absent) and the filter matches multiple records,
        require this to be C(true) to proceed. Prevents accidental
        bulk deletion when multiple records share (host, record_type).
    type: bool
    default: false
  weight:
    description:
      - The weight of the DNS record, used when load balancing is enabled.
      - Must be between 0 and 100.
    type: int
    required: false
  remark:
    description:
      - Remark for the DNS record.
    type: str
    required: false
requirements:
  - byteplus-python-sdk-v2 >= 3.0.44
'''

EXAMPLES = r'''
- name: Create an A record for www.example.com
  fardani235.byteplus.byteplus_dns_record:
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"
    domain_name: example.com
    host: www
    record_type: A
    value: 203.0.113.1
    ttl: 600
    state: present

- name: Create an A record using zone_id
  fardani235.byteplus.byteplus_dns_record:
    zone_id: 454458
    host: "@"
    record_type: A
    value: 203.0.113.10
    state: present

- name: Create a CNAME record
  fardani235.byteplus.byteplus_dns_record:
    domain_name: example.com
    host: blog
    record_type: CNAME
    value: blog.example.com
    ttl: 300
    state: present

- name: Update existing record value
  fardani235.byteplus.byteplus_dns_record:
    record_id: "3170534137672596377"
    host: www
    line: default
    value: 203.0.113.2
    state: present

- name: Delete a record by ID
  fardani235.byteplus.byteplus_dns_record:
    record_id: "3170534137672596377"
    state: absent

- name: Delete records matching host and type
  fardani235.byteplus.byteplus_dns_record:
    domain_name: example.com
    host: blog
    record_type: CNAME
    state: absent
'''

RETURN = r'''
record_id:
  description: The ID of the DNS record (when created or updated).
  type: str
  returned: when state=present
  sample: "3170534137672596377"
record:
  description: Full details of the DNS record.
  type: dict
  returned: when state=present and no change was needed
  sample: {
    "RecordID": "3170534137672596377",
    "Host": "www",
    "Type": "A",
    "Value": "203.0.113.1"
  }
result:
  description: Raw API response result.
  type: dict
  returned: when a change was made
changed:
  description: Whether any change was made.
  type: bool
  returned: always
'''

import ipaddress
import re

from ansible.module_utils.basic import AnsibleModule, env_fallback
from ansible_collections.fardani235.byteplus.plugins.module_utils.byteplus_common import BytePlusClient


_HOST_RE = re.compile(
    r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?'
    r'(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
)
_DOMAIN_RE = re.compile(
    r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+'
    r'[a-zA-Z]{2,}$'
)
_SRV_RE = re.compile(
    r'^\d+ \d+ \d+ [a-zA-Z0-9]([a-zA-Z0-9\-\.]{0,253}[a-zA-Z0-9])?$'
)


def _validate_host(host):
    if host == '@':
        return
    if not host or len(host) > 63:
        raise ValueError("host must be '@' for root domain or a valid subdomain up to 63 characters")
    if not _HOST_RE.match(host):
        raise ValueError(
            "Invalid host '{}': must contain only letters, digits, hyphens, and dots "
            "(e.g. 'www', 'www.sub')".format(host)
        )


def _validate_domain_name(domain):
    if not domain:
        raise ValueError("domain_name must not be empty")
    if len(domain) > 253:
        raise ValueError("domain_name must not exceed 253 characters")
    if not _DOMAIN_RE.match(domain):
        raise ValueError(
            "Invalid domain_name '{}': must be a valid domain format (e.g. example.com)".format(domain)
        )


def _is_ip_literal(value):
    for cls in (ipaddress.IPv4Address, ipaddress.IPv6Address):
        try:
            cls(value)
            return True
        except ValueError:
            continue
    return False


def _validate_record_value(record_type, value):
    if not value or not value.strip():
        raise ValueError("value must not be empty")

    value = value.strip()

    if record_type == 'A':
        try:
            ipaddress.IPv4Address(value)
        except ValueError:
            raise ValueError(
                "Invalid value for A record '{}': must be a valid IPv4 address (e.g. 203.0.113.1)".format(value)
            )

    elif record_type == 'AAAA':
        try:
            ipaddress.IPv6Address(value)
        except ValueError:
            raise ValueError(
                "Invalid value for AAAA record '{}': must be a valid IPv6 address (e.g. 2001:db8::1)".format(value)
            )

    elif record_type == 'CNAME':
        if _is_ip_literal(value):
            raise ValueError("Value for CNAME record must be a domain name, not an IP address")
        if len(value) > 253:
            raise ValueError("CNAME target must not exceed 253 characters")
        if not _DOMAIN_RE.match(value):
            raise ValueError(
                "Invalid value for CNAME record '{}': must be a valid domain name "
                "(e.g. target.example.com)".format(value)
            )

    elif record_type == 'MX':
        if not _DOMAIN_RE.match(value):
            raise ValueError(
                "Invalid value for MX record '{}': must be a valid mail exchange domain "
                "(e.g. mail.example.com)".format(value)
            )

    elif record_type == 'NS':
        if not _DOMAIN_RE.match(value):
            raise ValueError(
                "Invalid value for NS record '{}': must be a valid name server domain "
                "(e.g. ns1.example.com)".format(value)
            )

    elif record_type == 'SRV':
        if not _SRV_RE.match(value):
            raise ValueError(
                "Invalid value for SRV record '{}': must follow format "
                "'priority weight port target' (e.g. '10 5 5060 sip.example.com')".format(value)
            )


def _validate_numeric_range(name, value, minimum, maximum):
    if value is not None:
        if value < minimum or value > maximum:
            raise ValueError(
                "{} must be between {} and {}, got {}".format(name, minimum, maximum, value)
            )


def _normalize_params(module):
    p = module.params

    if p['state'] == 'present' and not p['record_id']:
        missing = []
        if not p['host']:
            missing.append('host')
        if not p['value']:
            missing.append('value')
        if not p['record_type']:
            missing.append('record_type')
        if missing:
            module.fail_json(
                msg="The following parameters are required when state=present and record_id is not given: {}"
                    .format(', '.join(missing))
            )

    if not p['zone_id'] and not p['domain_name'] and not p['record_id']:
        module.fail_json(
            msg="Either zone_id or domain_name is required when record_id is not provided"
        )


def _validate_params(module):
    p = module.params

    if p['zone_id'] is not None:
        _validate_numeric_range('zone_id', p['zone_id'], 1, 2147483647)

    if p['domain_name']:
        _validate_domain_name(p['domain_name'])

    _validate_numeric_range('ttl', p['ttl'], 1, 86400)

    if p['weight'] is not None:
        _validate_numeric_range('weight', p['weight'], 0, 100)

    if p['state'] == 'present':
        if p['host']:
            _validate_host(p['host'])
        if p['value'] and p['record_type']:
            _validate_record_value(p['record_type'], p['value'])


def _find_matching_records(records, host, record_type, value=None):
    matched = []
    for r in (records or []):
        if r.get('Host') == host and r.get('Type') == record_type:
            if value is None or r.get('Value') == value:
                matched.append(r)
    return matched


def _ensure_present(module, client):
    p = module.params
    record_id = p['record_id']

    if record_id:
        update_kwargs = {'record_id': record_id}
        if p['host'] is not None:
            update_kwargs['host'] = p['host']
        # Only pass `line` if the user actually set it; otherwise we'd
        # clobber a non-default line (e.g. CT, CU) back to 'default'.
        if p['line'] is not None:
            update_kwargs['line'] = p['line']
        if p['record_type']:
            update_kwargs['record_type'] = p['record_type']
        if p['value']:
            update_kwargs['value'] = p['value']
        if p['ttl'] is not None:
            update_kwargs['ttl'] = p['ttl']
        if p['weight'] is not None:
            update_kwargs['weight'] = p['weight']
        if p['remark'] is not None:
            update_kwargs['remark'] = p['remark']

        if module.check_mode:
            module.exit_json(changed=True, msg="Would update DNS record {}".format(record_id))
        result = client.update_record(**update_kwargs)
        module.exit_json(changed=True, record_id=record_id, result=result)

    zone_id = client.resolve_zone_id(p['zone_id'], p['domain_name'])
    host = p['host']
    record_type = p['record_type']
    value = p['value']

    resp = client.list_records(zone_id, host=host, record_type=record_type)
    records = resp.get('Records', []) if resp else []

    # Exact (host, type, value) match: that's the record we're managing.
    exact = _find_matching_records(records, host, record_type, value=value)
    same_host_type = _find_matching_records(records, host, record_type)

    if exact:
        existing = exact[0]
        needs_update = (
            existing.get('TTL') != p['ttl'] or
            (p['weight'] is not None and existing.get('Weight') != p['weight']) or
            (p['remark'] is not None and existing.get('Remark') != p['remark'])
        )
        if not needs_update:
            module.exit_json(changed=False, record=existing)

        # `Line` is required by UpdateRecord — when the caller didn't set it,
        # preserve the existing record's line rather than omitting it (which
        # would yield "Bad Request") or defaulting to 'default' (which would
        # silently move a non-default-line record back to default).
        update_kwargs = {
            'record_id': existing['RecordID'],
            'host': host,
            'value': value,
            'record_type': record_type,
            'ttl': p['ttl'],
            'line': p['line'] if p['line'] is not None else (existing.get('Line') or 'default'),
        }
        if p['weight'] is not None:
            update_kwargs['weight'] = p['weight']
        if p['remark'] is not None:
            update_kwargs['remark'] = p['remark']

        if module.check_mode:
            module.exit_json(changed=True, msg="Would update DNS record {}".format(existing['RecordID']))
        result = client.update_record(**update_kwargs)
        module.exit_json(changed=True, record_id=existing['RecordID'], result=result)

    # No exact match. If there's exactly one record at this (host, type),
    # treat as an in-place value change. If there are several, refuse —
    # the caller must pass record_id to disambiguate.
    if len(same_host_type) == 1:
        existing = same_host_type[0]
        update_kwargs = {
            'record_id': existing['RecordID'],
            'host': host,
            'value': value,
            'record_type': record_type,
            'ttl': p['ttl'],
            'line': p['line'] if p['line'] is not None else (existing.get('Line') or 'default'),
        }
        if p['weight'] is not None:
            update_kwargs['weight'] = p['weight']
        if p['remark'] is not None:
            update_kwargs['remark'] = p['remark']

        if module.check_mode:
            module.exit_json(changed=True, msg="Would update DNS record {}".format(existing['RecordID']))
        result = client.update_record(**update_kwargs)
        module.exit_json(changed=True, record_id=existing['RecordID'], result=result)

    if len(same_host_type) > 1:
        module.fail_json(
            msg=("Multiple records exist for host={} type={} ({} found). "
                 "Pass record_id to target a specific record.").format(
                host, record_type, len(same_host_type))
        )

    if module.check_mode:
        module.exit_json(changed=True, msg="Would create DNS record")
    result = client.create_record(
        zone_id=zone_id, host=host, record_type=record_type, value=value,
        ttl=p['ttl'], line=p['line'] or 'default',
        weight=p['weight'], remark=p['remark'],
    )
    new_id = result.get('RecordID') if result else None
    module.exit_json(changed=True, record_id=new_id, result=result)


def _ensure_absent(module, client):
    p = module.params
    record_id = p['record_id']

    if record_id:
        if module.check_mode:
            module.exit_json(changed=True, msg="Would delete DNS record {}".format(record_id))
        client.delete_record(record_id)
        module.exit_json(changed=True, record_id=record_id)

    zone_id = client.resolve_zone_id(p['zone_id'], p['domain_name'])
    host = p.get('host')
    record_type = p.get('record_type')
    value = p.get('value')
    delete_all = p.get('delete_all', False)

    if not host and not record_type:
        module.fail_json(
            msg="At least one of host or record_type is needed to identify records for deletion"
        )

    resp = client.list_records(zone_id, host=host, record_type=record_type)
    records = resp.get('Records', []) if resp else []

    if host and record_type and value:
        matched = _find_matching_records(records, host, record_type, value=value)
    elif host and record_type:
        matched = _find_matching_records(records, host, record_type)
    elif host:
        matched = [r for r in records if r.get('Host') == host]
    else:
        matched = [r for r in records if r.get('Type') == record_type]

    if not matched:
        module.exit_json(changed=False, msg="No matching DNS records found to delete")

    # Safety: refuse to bulk-delete multiple records unless the caller
    # opts in explicitly or has narrowed by value. Prevents accidentally
    # wiping multiple A records sharing a host.
    if len(matched) > 1 and not value and not delete_all:
        ids = [r.get('RecordID') for r in matched]
        module.fail_json(
            msg=("Refusing to delete multiple records ({} matched: {}). "
                 "Set value to target a specific record, pass record_id, "
                 "or set delete_all=true to override.").format(len(matched), ids)
        )

    if module.check_mode:
        ids = [r['RecordID'] for r in matched]
        module.exit_json(changed=True, msg="Would delete DNS records: {}".format(ids))

    for record in matched:
        client.delete_record(record['RecordID'])

    module.exit_json(changed=True, deleted_count=len(matched))


def main():
    module = AnsibleModule(
        argument_spec=dict(
            access_key=dict(type='str', required=False, fallback=(env_fallback, ['BYTEPLUS_ACCESS_KEY'])),
            secret_key=dict(type='str', required=False, no_log=True, fallback=(env_fallback, ['BYTEPLUS_SECRET_KEY'])),
            region=dict(type='str', default='ap-southeast-1'),
            zone_id=dict(type='int', required=False),
            domain_name=dict(type='str', required=False),
            state=dict(type='str', default='present', choices=['present', 'absent']),
            record_type=dict(type='str', required=False, choices=['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS', 'SRV', 'CAA']),
            host=dict(type='str', required=False),
            value=dict(type='str', required=False),
            record_id=dict(type='str', required=False),
            ttl=dict(type='int', default=600),
            # No default: a missing `line` on update-by-record_id must NOT
            # clobber an existing non-default line. Defaulting to 'default'
            # is applied only when creating a new record (see _ensure_present).
            line=dict(type='str', required=False),
            weight=dict(type='int', required=False),
            remark=dict(type='str', required=False),
            delete_all=dict(type='bool', default=False),
        ),
        supports_check_mode=True,
    )

    _normalize_params(module)

    try:
        _validate_params(module)
    except ValueError as e:
        module.fail_json(msg=str(e))

    try:
        client = BytePlusClient(
            access_key=module.params['access_key'],
            secret_key=module.params['secret_key'],
            region=module.params['region'],
        )
    except Exception as e:
        module.fail_json(msg="Failed to initialize BytePlus client: {}".format(str(e)))

    if module.params['state'] == 'present':
        _ensure_present(module, client)
    else:
        _ensure_absent(module, client)


if __name__ == '__main__':
    main()
