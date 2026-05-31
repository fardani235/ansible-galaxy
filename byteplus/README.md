# BytePlus Cloud Ansible Collection

Ansible collection for managing BytePlus cloud resources. Currently supports VPC, ECS, DNS record management and TOS (Torch Object Storage) bucket/object management.

## Requirements

- Python 3.6+
- `byteplus-python-sdk-v2` (included as the parent project)
- Ansible >= 2.14.0

## Installation

`ansible-galaxy` installs the collection but does NOT install Python
dependencies. You must install `byteplus-python-sdk-v2` separately into
the same Python interpreter Ansible will use on the controller (and on
remote targets, if running the modules there):

```bash
# 1. Install the Python SDK these modules wrap.
pip install -r collections/ansible_collections/byteplus/cloud/requirements.txt

# 2. Build and install the collection.
ansible-galaxy collection build collections/ansible_collections/byteplus/cloud/
ansible-galaxy collection install byteplus-cloud-*.tar.gz
```

If you see `ModuleNotFoundError: byteplussdkcore` at task runtime, the
SDK is missing from the Python interpreter Ansible chose — check
`ansible_python_interpreter` and `which python3` on the host actually
running the module.

## Authentication

Set credentials as module parameters or environment variables:

| Parameter       | Environment Variable    | Description            |
|-----------------|------------------------|------------------------|
| `access_key`    | `BYTEPLUS_ACCESS_KEY`  | BytePlus access key    |
| `secret_key`    | `BYTEPLUS_SECRET_KEY`  | BytePlus secret key    |
| `region`        | `BYTEPLUS_REGION`      | API region (default: `ap-southeast-1`) |

## Modules

### byteplus_dns_record

Manage DNS records (A, AAAA, CNAME, MX, TXT, NS, SRV, CAA).

| Parameter      | Required | Choices                                                        | Default   |
|----------------|----------|----------------------------------------------------------------|-----------|
| `domain_name`  | yes*     |                                                                |           |
| `zone_id`      | yes*     |                                                                |           |
| `host`         | yes      |                                                                |           |
| `record_type`  | yes      | `A`, `AAAA`, `CNAME`, `MX`, `TXT`, `NS`, `SRV`, `CAA`         |           |
| `value`        | yes      |                                                                |           |
| `state`        | no       | `present`, `absent`                                            | `present` |
| `ttl`          | no       | 1-86400                                                        | `600`     |
| `weight`       | no       | 0-100                                                          |           |
| `line`         | no       |                                                                | `default` |
| `remark`       | no       |                                                                |           |
| `record_id`    | no       |                                                                |           |

\* Exactly one of `domain_name` or `zone_id` is required.

**Playbook examples:**

```yaml
- name: Create an A record
  fardani235.byteplus.byteplus_dns_record:
    domain_name: example.com
    host: www
    record_type: A
    value: 203.0.113.10
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"

- name: Delete a CNAME record
  fardani235.byteplus.byteplus_dns_record:
    domain_name: example.com
    host: api
    record_type: CNAME
    value: backend.example.com
    state: absent
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"

- name: Create MX record with priority
  fardani235.byteplus.byteplus_dns_record:
    domain_name: example.com
    host: @
    record_type: MX
    value: 10 mail.example.com
    ttl: 300
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"

- name: Create a TXT record for SPF
  fardani235.byteplus.byteplus_dns_record:
    domain_name: example.com
    host: @
    record_type: TXT
    value: "v=spf1 include:_spf.example.com ~all"
    ttl: 3600
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"
```

### byteplus_tos_bucket

Manage TOS buckets (create, delete, check existence).

| Parameter     | Required | Choices                                                        | Default   |
|---------------|----------|----------------------------------------------------------------|-----------|
| `bucket_name` | yes      |                                                                |           |
| `state`       | no       | `present`, `absent`                                            | `present` |
| `acl`         | no       | `private`, `public-read`, `public-read-write`, `authenticated-read` |       |

**Playbook examples:**

```yaml
- name: Create a bucket
  fardani235.byteplus.byteplus_tos_bucket:
    bucket_name: my-data-bucket
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"
    region: ap-southeast-1

- name: Delete a bucket
  fardani235.byteplus.byteplus_tos_bucket:
    bucket_name: my-old-bucket
    state: absent
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"
    region: ap-southeast-1
```

### byteplus_tos_object

Manage TOS objects (upload, delete, check existence). Idempotent via MD5/ETag comparison.

| Parameter      | Required     | Choices               | Default   |
|----------------|-------------|------------------------|-----------|
| `bucket_name`  | yes         |                        |           |
| `object_key`   | yes         |                        |           |
| `src`          | see note    |                        |           |
| `content`      | see note    |                        |           |
| `content_type` | no          |                        | auto-detected |
| `state`        | no          | `present`, `absent`    | `present` |

**Note:** When `state=present`, exactly one of `src` (local file path) or `content` (inline string) is required.

**Playbook examples:**

```yaml
- name: Upload a file
  fardani235.byteplus.byteplus_tos_object:
    bucket_name: my-data-bucket
    object_key: configs/app.yaml
    src: ./app.yaml
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"
    region: ap-southeast-1

- name: Upload inline content
  fardani235.byteplus.byteplus_tos_object:
    bucket_name: my-data-bucket
    object_key: configs/settings.json
    content: '{"debug": true, "port": 8080}'
    content_type: application/json
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"
    region: ap-southeast-1

- name: Delete an object
  fardani235.byteplus.byteplus_tos_object:
    bucket_name: my-data-bucket
    object_key: old-file.txt
    state: absent
    access_key: "{{ byteplus_access_key }}"
    secret_key: "{{ byteplus_secret_key }}"
    region: ap-southeast-1
```

### byteplus_ecs_instance

Manage the lifecycle of BytePlus ECS (Elastic Compute Service) instances. An
instance is identified by `instance_id`, or by `instance_name` (which must
be unique — the module fails closed if a name matches multiple instances).

| Parameter             | Required          | Choices                                       | Default      |
|-----------------------|-------------------|-----------------------------------------------|--------------|
| `state`               | no                | `present`, `absent`, `started`, `stopped`, `restarted` | `present` |
| `instance_id`         | for non-create    |                                               |              |
| `instance_name`       | for non-create*   |                                               |              |
| `zone_id`             | when creating     |                                               |              |
| `image_id`            | when creating     |                                               |              |
| `instance_type`       | when creating     |                                               |              |
| `subnet_id`           | when creating     |                                               |              |
| `security_group_ids`  | when creating     | list of str                                   |              |
| `key_pair_name`       | no                |                                               |              |
| `password`            | no                |                                               |              |
| `user_data`           | no                | base64                                        |              |
| `tags`                | no                | list of `{key, value}` dicts                  |              |
| `volumes`             | no                | list of dict (pass-through to RunInstances)   |              |
| `count`               | no                |                                               | `1`          |
| `force`               | no                | for stop/reboot                               | `false`      |
| `stopped_mode`        | no                | e.g. `KeepCharging`                           |              |
| `wait`                | no                |                                               | `true`       |
| `wait_timeout`        | no                | seconds                                       | `600`        |

\* Either `instance_id` or `instance_name` is required when `state` is anything other than `present`.

**Playbook examples:**

```yaml
- name: Launch an instance and wait for it to be running
  fardani235.byteplus.byteplus_ecs_instance:
    instance_name: web-01
    zone_id: ap-southeast-1a
    image_id: image-ybvz29l3da0smmpnfb02
    instance_type: ecs.g1.large
    subnet_id: subnet-abcdefg
    security_group_ids: [sg-1234567]
    key_pair_name: my-keypair
    state: present

- name: Stop an instance
  fardani235.byteplus.byteplus_ecs_instance:
    instance_id: i-ybw0lke12345
    state: stopped

- name: Force-reboot
  fardani235.byteplus.byteplus_ecs_instance:
    instance_id: i-ybw0lke12345
    state: restarted
    force: true

- name: Delete and wait
  fardani235.byteplus.byteplus_ecs_instance:
    instance_id: i-ybw0lke12345
    state: absent
```

### byteplus_ecs_instance_info

Read-only listing/describe with automatic pagination.

| Parameter        | Type        | Notes                                  |
|------------------|-------------|----------------------------------------|
| `instance_ids`   | list of str | Filter to specific IDs                 |
| `instance_name`  | str         | Exact name match                       |
| `zone_id`        | str         |                                        |
| `vpc_id`         | str         |                                        |
| `status`         | str         | e.g. `RUNNING`, `STOPPED`              |
| `project_name`   | str         |                                        |
| `tags`           | list of dict| Each `{key, value}`                    |
| `max_results`    | int         | Page size hint (default `100`)         |

**Playbook example:**

```yaml
- name: List running instances in a zone
  fardani235.byteplus.byteplus_ecs_instance_info:
    zone_id: ap-southeast-1a
    status: RUNNING
  register: ecs_info

- debug:
    msg: "Found {{ ecs_info.count }} running instances"
```

### byteplus_ecs_snapshot / byteplus_ecs_snapshot_group / byteplus_ecs_snapshot_info

Create, delete, and list BytePlus EBS snapshots.

Two flavors are exposed, matching the underlying BytePlus API:

- **`byteplus_ecs_snapshot`** — point-in-time snapshot of a single
  EBS volume. Identified by `snapshot_id` or `snapshot_name`.
- **`byteplus_ecs_snapshot_group`** — atomic snapshot covering every
  volume attached to an ECS instance (the conventional "instance
  snapshot"). Identified by `snapshot_group_id` or `name`. Also
  supports `state: rolled_back` to restore an instance from a group
  snapshot.
- **`byteplus_ecs_snapshot_info`** — read-only listing of either kind,
  selected via the `kind` parameter.

```yaml
- name: Snapshot a single data volume
  fardani235.byteplus.byteplus_ecs_snapshot:
    snapshot_name: db-data-2026-05-24
    volume_id: vol-yb1111
    description: Pre-upgrade snapshot
    retention_days: 7
    state: present

- name: Take a full instance snapshot (every attached volume)
  fardani235.byteplus.byteplus_ecs_snapshot_group:
    name: web-01-2026-05-24
    instance_id: i-ybw0lke12345
    description: Pre-deploy snapshot
    tags:
      - key: purpose
        value: pre-deploy
    state: present

- name: List snapshot groups for an instance
  fardani235.byteplus.byteplus_ecs_snapshot_info:
    kind: snapshot_group
    instance_id: i-ybw0lke12345
  register: groups
```

Rollback is **strict by design**: BytePlus requires the instance to
be in the `STOPPED` state before `RollbackSnapshotGroup` succeeds, and
this module refuses to proceed when the instance is in any other
state rather than silently powering it off. Orchestrate the stop
explicitly:

```yaml
- name: Stop the instance first
  fardani235.byteplus.byteplus_ecs_instance:
    instance_id: i-ybw0lke12345
    state: stopped

- name: Then roll back
  fardani235.byteplus.byteplus_ecs_snapshot_group:
    snapshot_group_id: snap-grp-yb0123456789
    instance_id: i-ybw0lke12345
    state: rolled_back
```

The default `wait_timeout` for snapshot creation is 30 minutes —
large data disks routinely take several minutes to reach
`available`. Override `wait_timeout` if your volumes are small and
you want faster feedback.

### byteplus_vpc / byteplus_subnet / byteplus_security_group

Manage VPC networking primitives. All three share a common pattern:

- **Identification**: by ID (`vpc_id` / `subnet_id` / `security_group_id`), or
  by name. Subnets and security groups must additionally pass `vpc_id` for
  name lookup. Names are not unique server-side, so set `project_name` to
  scope the lookup to one BytePlus project when name collides across projects.
- **State**: `present` creates if missing; `absent` deletes.
- **Drift detection**: mutable fields (name, description, DNS servers for VPC)
  are diffed and pushed through ModifyVpcAttributes / ModifySubnetAttributes /
  ModifySecurityGroupAttributes. Immutable fields (CIDR, zone, IPv6 settings)
  are ignored on update.

```yaml
- name: Stand up a VPC + subnet + SG, then launch an instance into them
  block:
    - fardani235.byteplus.byteplus_vpc:
        vpc_name: prod-vpc
        cidr_block: 172.16.0.0/16
        project_name: prod
      register: vpc

    - fardani235.byteplus.byteplus_subnet:
        subnet_name: web-a
        vpc_id: "{{ vpc.vpc.vpc_id }}"
        zone_id: ap-southeast-1a
        cidr_block: 172.16.1.0/24
      register: subnet

    - fardani235.byteplus.byteplus_security_group:
        security_group_name: web-tier
        vpc_id: "{{ vpc.vpc.vpc_id }}"
        description: HTTPS in
      register: sg

    - fardani235.byteplus.byteplus_ecs_instance:
        instance_name: web-01
        zone_id: ap-southeast-1a
        image_id: image-ybvz29l3da0smmpnfb02
        instance_type: ecs.g1.large
        subnet_id: "{{ subnet.subnet.subnet_id }}"
        security_group_ids:
          - "{{ sg.security_group.security_group_id }}"
        state: started
```

**Important:** VPCs can only be deleted once empty (no subnets, no instances).
Security groups can only be deleted once no NICs reference them. Run teardown
in reverse order; the modules do not auto-cascade.

### byteplus_vpc_info

Read-only listing of BytePlus VPCs. Filters on `vpc_ids`, `vpc_name`, and
`project_name`; pagination is handled automatically. Mirrors the existing
`byteplus_prefix_list_info` and `byteplus_iam_user_info` modules.

```yaml
- name: Find the prod VPC by name
  fardani235.byteplus.byteplus_vpc_info:
    vpc_name: prod-vpc
    project_name: prod
  register: prod_vpc
```

### byteplus_route_table / byteplus_route_table_info / byteplus_route_entry

Manage custom (user-created) VPC route tables and the route entries inside
them. The VPC-provided default route table (`RouteTableType=System`) is
**refused** by `byteplus_route_table` on rename, association changes, and
delete — these are almost always mistakes and BytePlus's own error messages
are unhelpful. Routes can still be added to the default table via
`byteplus_route_entry`.

- **`byteplus_route_table`** — identification by `route_table_id` or by
  `(vpc_id, route_table_name)`. Mutable fields (`route_table_name`,
  `description`) are diffed and pushed through `ModifyRouteTableAttributes`.
  Subnet associations are reconciled when `associated_subnet_ids` is
  supplied — supplying it takes ownership of the full set. **Omitting it
  leaves existing associations untouched**, so partial config updates do
  not accidentally disassociate subnets.
- **`byteplus_route_table_info`** — list / describe route tables. Set
  `include_entries: true` to hydrate each table's route entries inline at
  the cost of one extra `DescribeRouteEntryList` call per table.
- **`byteplus_route_entry`** — manages one route entry per task, identified
  by `(route_table_id, destination_cidr_block)`. Next-hop types are written
  in snake_case (`nat_gateway`, `network_interface`, `ipv6_gateway`,
  `transit_router`, `vpn_gateway`, `ha_vip`, `private_link_vpc_endpoint`,
  `instance`, `ip_address`) and translated to BytePlus's PascalCase
  spelling on the wire. Updates use `ModifyRouteEntry` in place, so
  changing next-hop or description does not interrupt traffic.

```yaml
- name: Custom route table for the app tier
  fardani235.byteplus.byteplus_route_table:
    route_table_name: prod-app
    vpc_id: "{{ vpc.vpc.vpc_id }}"
    associated_subnet_ids:
      - "{{ app_subnet.subnet.subnet_id }}"
  register: app_rt

- name: Default egress via the NAT gateway
  fardani235.byteplus.byteplus_route_entry:
    route_table_id: "{{ app_rt.route_table.route_table_id }}"
    destination_cidr_block: 0.0.0.0/0
    next_hop_type: nat_gateway
    next_hop_id: "{{ nat_gw_id }}"

- name: Inspect the table with its routes
  fardani235.byteplus.byteplus_route_table_info:
    route_table_ids:
      - "{{ app_rt.route_table.route_table_id }}"
    include_entries: true
  register: app_rt_full
```

`byteplus_route_table` refuses to delete a table that still has subnet
associations or non-system entries — BytePlus rejects the API call, and
the modules surface the error rather than silently revoking state.

### byteplus_security_group_rule

Manages individual ingress / egress rules on a security group.

BytePlus does not assign rule IDs, so a rule is identified by the tuple
`(direction, protocol, port_start, port_end, target, policy)` where `target`
is exactly one of `cidr_ip`, `source_group_id`, or `prefix_list_id`.
Description-only changes go through `ModifySecurityGroupRuleDescriptions`
and do **not** revoke + re-authorize — in-flight connections are preserved.
Priority changes cannot be applied in place; the module revokes and
re-authorizes, which briefly disrupts matching traffic.

```yaml
- name: Allow HTTPS in from anywhere
  fardani235.byteplus.byteplus_security_group_rule:
    security_group_id: "{{ sg.security_group.security_group_id }}"
    direction: ingress
    protocol: tcp
    port_start: 443
    port_end: 443
    cidr_ip: 0.0.0.0/0
    policy: accept
    description: Public HTTPS

- name: Allow another SG to talk to us on a private port
  fardani235.byteplus.byteplus_security_group_rule:
    security_group_id: sg-web
    direction: ingress
    protocol: tcp
    port_start: 8080
    port_end: 8080
    source_group_id: sg-bastion
    policy: accept

- name: Revoke an old rule
  fardani235.byteplus.byteplus_security_group_rule:
    security_group_id: "{{ sg.security_group.security_group_id }}"
    direction: ingress
    protocol: tcp
    port_start: 22
    port_end: 22
    cidr_ip: 0.0.0.0/0
    state: absent
```

### byteplus_prefix_list / byteplus_prefix_list_info

Manage BytePlus VPC prefix lists — the reusable IP/CIDR set you can
reference from security group rules instead of pasting the same list
into every rule.

The lifecycle module declares both the prefix list itself and its entries
in one place. By default it only **adds** missing entries; set
`purge_entries: true` to also remove entries on the server that are
absent from your `entries:` list (i.e. reconcile to exactly your set).

```yaml
- name: Create a whitelist prefix list and reference it from an SG rule
  block:
    - fardani235.byteplus.byteplus_prefix_list:
        prefix_list_name: office-egress
        description: Corporate egress IPs
        max_entries: 50
        project_name: prod
        entries:
          - cidr: 203.0.113.0/24
            description: HQ Singapore
          - cidr: 198.51.100.0/24
            description: Branch Tokyo
      register: pl

    - fardani235.byteplus.byteplus_security_group_rule:
        security_group_id: "{{ sg.security_group.security_group_id }}"
        direction: ingress
        protocol: tcp
        port_start: 443
        port_end: 443
        prefix_list_id: "{{ pl.prefix_list.prefix_list_id }}"
        policy: accept
```

**Notes:**
- `ip_version` (IPv4 vs IPv6) and `tags` are only honored at creation; the
  API does not allow changing them afterward.
- `max_entries` can be increased but not decreased.
- Description-only entry changes are merged via `ModifyPrefixList` without
  removing and re-adding the CIDR.

The `byteplus_prefix_list_info` module lists prefix lists with optional
`include_entries: true` to also fetch each list's contents in one call.

### byteplus_iam_user / byteplus_iam_user_info / byteplus_iam_login_profile / byteplus_iam_access_key

Manage BytePlus IAM identities and their console / programmatic access.

| Module                          | Purpose                                                                |
|---------------------------------|------------------------------------------------------------------------|
| `byteplus_iam_user`             | CRUD an IAM user by `user_name`                                        |
| `byteplus_iam_user_info`        | List or describe users; optional `include_access_keys` / `include_attached_policies` |
| `byteplus_iam_login_profile`    | Console login password for a user; rotates only on explicit `force_password_update` |
| `byteplus_iam_access_key`       | Create / deactivate / delete / rotate AKs; secret returned exactly once |

**Playbook examples:**

```yaml
- name: Create an IAM user
  fardani235.byteplus.byteplus_iam_user:
    user_name: alice
    display_name: Alice Example
    email: alice@example.com
    state: present

- name: Give them console access (must rotate on first login)
  fardani235.byteplus.byteplus_iam_login_profile:
    user_name: alice
    password: "{{ lookup('password', '/dev/null length=32') }}"
    password_reset_required: true
    state: present

- name: Ensure alice has an active access key, capture the secret
  fardani235.byteplus.byteplus_iam_access_key:
    user_name: alice
    state: present
  register: ak
  no_log: true   # the response carries the secret

- name: Rotate alice's access keys
  fardani235.byteplus.byteplus_iam_access_key:
    user_name: alice
    rotate: true
  no_log: true
```

**Notes:**

- Re-running `byteplus_iam_login_profile` with a different `password` is a
  **no-op** unless `force_password_update: true` is set. Passwords can't
  be read back, so the module never rotates them implicitly — explicit
  opt-in is required to avoid silent credential churn.
- `byteplus_iam_access_key` returns `secret_access_key` only at create
  time, and the value is registered with `module.no_log_values`. The
  always-returned `keys` field is stripped of any secret-shaped fields.
- `rotate: true` fails before calling `CreateAccessKey` when the user
  already has 2 keys (BytePlus's hard cap). Delete one explicitly first.

### byteplus_iam_policy / byteplus_iam_policy_info / byteplus_iam_policy_attachment

Manage customer-managed IAM policies and their attachments to users / roles.

| Module                            | Purpose                                                |
|-----------------------------------|--------------------------------------------------------|
| `byteplus_iam_policy`             | CRUD a customer-managed policy by `policy_name`        |
| `byteplus_iam_policy_info`        | List or describe policies; optional `include_entities` |
| `byteplus_iam_policy_attachment`  | Attach / detach a policy to a user or role             |

**Playbook examples:**

```yaml
- name: Create a custom read-only policy
  fardani235.byteplus.byteplus_iam_policy:
    policy_name: tos-read-only
    description: "Read TOS buckets and objects only"
    policy_document:
      Statement:
        - Effect: Allow
          Action:
            - tos:GetObject
            - tos:ListBucket
          Resource: "*"
    state: present

- name: Attach a custom policy to a user
  fardani235.byteplus.byteplus_iam_policy_attachment:
    policy_name: tos-read-only
    target_type: user
    target_name: alice
    state: present

- name: Attach a BytePlus system policy to a role
  fardani235.byteplus.byteplus_iam_policy_attachment:
    policy_name: AdministratorAccess
    policy_type: System
    target_type: role
    target_name: deploy-role
    state: present
```

**Notes:**

- `byteplus_iam_policy` refuses to touch system policies. Use
  `byteplus_iam_policy_info` to inspect them and
  `byteplus_iam_policy_attachment` to attach them.
- `policy_document` is canonicalized (parse-then-key-sort) for drift
  detection, so re-running with semantically identical JSON does not
  flip `changed=true` even if the key order differs.
- `policy_type` is part of the attachment identity — the same
  `policy_name` can exist as both `Custom` and `System`. Match on name
  alone would silently no-op when the wrong flavor was attached.

### byteplus_iam_role / byteplus_iam_role_info

Manage IAM roles. Same drift-detection shape as `byteplus_iam_policy`
applied to `trust_policy_document`.

| Parameter                | Required | Default | Notes                                            |
|--------------------------|----------|---------|--------------------------------------------------|
| `role_name`              | yes      |         | Primary key; never renamed by this module        |
| `trust_policy_document`  | when state=present | | Dict or JSON string; canonicalized for diff |
| `description`            | no       |         |                                                  |
| `max_session_duration`   | no       |         | Seconds; 3600 ≤ value ≤ 43200                    |
| `state`                  | no       | present | `present` / `absent`                             |

```yaml
- name: Create a role assumable by ECS instances
  fardani235.byteplus.byteplus_iam_role:
    role_name: ecs-runtime-role
    description: Used by ECS instances at runtime
    max_session_duration: 7200
    trust_policy_document:
      Statement:
        - Effect: Allow
          Principal:
            Service: [ecs]
          Action: sts:AssumeRole
    state: present
```

`byteplus_iam_role_info` lists or describes roles; pass
`include_attached_policies: true` to expand each role's current
attachments in one call.

## Idempotency

- **DNS records**: Matches on host + record_type + value. Updates on diff, noop on match. Refuses to delete more than one match unless `value` narrows it or `delete_all: true` is set.
- **Buckets**: Creates if absent, no-op if present (and vice versa for delete).
- **Objects**: Upload skips if MD5 hash matches remote ETag (multipart-uploaded objects are always re-uploaded because their ETag is not a single MD5).
- **ECS instances**: `state=present` no-ops when an instance with the same `instance_id` or `instance_name` already exists. Lifecycle states (`started`/`stopped`/`restarted`) no-op when already in the target state. `project_name` narrows name-based lookup when the same name exists in multiple BytePlus projects.
- **VPCs / subnets / security groups**: `state=present` no-ops when the resource exists and mutable fields (name, description, DNS servers) match. Drift on mutable fields is pushed via ModifyXAttributes; CIDR/zone/IPv6 are immutable post-create and ignored.
- **IAM users / policies / roles**: `state=present` no-ops when the resource exists and mutable fields match. Policy and trust-policy documents are compared after parse-then-key-sort, so re-running with semantically identical JSON of different key order does not flip `changed`. Delete refuses to auto-cascade — a user with access keys or attachments, a policy with attachments, or a role with attachments must be torn down explicitly.
- **IAM login profiles**: Passwords cannot be read back, so password drift is invisible to the module. Re-running with a different `password` is a no-op unless `force_password_update: true` is set explicitly.
- **IAM access keys**: `state=present` (no `access_key_id`, no `rotate`) ensures the user has at least one Active key. `rotate: true` creates a new one and deactivates the oldest active key, failing fast if the user already has 2 keys.

## Check Mode

All modules support `check_mode: true` to preview changes without executing them.

## Validation

| Module                    | Field          | Validation                                                   |
|---------------------------|----------------|--------------------------------------------------------------|
| `byteplus_dns_record`     | `host`         | Valid hostname or `@`                                        |
| `byteplus_dns_record`     | `domain_name`  | Valid domain name                                            |
| `byteplus_dns_record`     | `value`        | IP/domain/CNAME validation per record type                   |
| `byteplus_dns_record`     | `ttl`          | 1-86400                                                      |
| `byteplus_dns_record`     | `weight`       | 0-100                                                        |
| `byteplus_dns_record`     | `zone_id`      | 1-9999999999                                                  |
| `byteplus_tos_bucket`     | `bucket_name`  | 3-63 chars, lowercase/numbers/hyphens, no leading/trailing hyphen |
| `byteplus_tos_object`     | `src`/`content`| Mutually exclusive; exactly one required when state=present  |

## CI/CD

This collection ships two GitHub Actions workflows at the **monorepo
root** under `.github/workflows/` (one level above the `byteplus/`
collection directory, because GHA only reads workflows from the repo
root):

- **`test.yml`** runs on pull requests to `main` and pushes to `main`,
  paths-filtered to `byteplus/**` so it only fires on changes to this
  collection. It runs `ansible-test sanity` across ansible-core 2.16,
  2.17, and 2.18 in parallel plus a single `pytest tests/unit/` job.
  Failure on any matrix cell does not cancel the others
  (`fail-fast: false`).
- **`release.yml`** runs on `byteplus-v*` tag pushes (the
  `byteplus-` prefix namespaces the tag so future sibling collections
  can use their own prefixes). It verifies the tag matches `galaxy.yml`
  version, verifies no unfolded `changelogs/fragments/*.yml` remain,
  re-runs sanity + unit on the tagged commit, builds the collection
  with `ansible-galaxy collection build`, then publishes to Ansible
  Galaxy. The Galaxy API token is supplied via the repo secret
  `GALAXY_API_KEY` (Settings → Secrets and variables → Actions).

**To cut a release:**

1. Bump `version:` in `byteplus/galaxy.yml`.
2. Run `antsibull-changelog release` from inside `byteplus/` to fold
   pending fragments into the changelog. Commit.
3. (Optional, recommended) Run the local dry-run from
   `byteplus/docs/cicd-local-dryrun.md` to verify the release guards
   pass.
4. From the monorepo root, tag with the version prefixed by
   `byteplus-v` (e.g. `byteplus-v1.2.0`) and push:
   `git tag byteplus-v1.2.0 && git push origin byteplus-v1.2.0`.

If `release.yml` fails partway through, fix the issue and re-tag with
the next patch version — Galaxy rejects re-uploads of the same version
number, so a failed publish never leaves a partial artifact on Galaxy.
