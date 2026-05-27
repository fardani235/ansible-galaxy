# BytePlus IAM modules — design (v1.2.0)

**Status:** approved for implementation planning
**Author:** brainstormed with the maintainer, 2026-05-27
**Target release:** `fardani235.byteplus` 1.2.0
**Supersedes:** none

## Why

The collection currently has no identity surface. "Codify who can do what
in BytePlus" is the next thing the maintainer wants to be able to do from
Ansible, and the gap blocks every higher-level security and governance
workflow (KMS grants, WAF account separation, audit-trail role, etc.).

The installed BytePlus Python SDK (`byteplus-python-sdk-v2` 3.0.45) ships
only the *Projects* slice of IAM (`byteplussdkiam20210801`) — no user,
policy, role, or access-key APIs. The full IAM surface does exist on the
BytePlus public HTTP API (`iam.byteplusapi.com`), and the collection's
existing modules already drive it via `byteplussdkcore.UniversalApi`
(see `plugins/module_utils/byteplus_common.py`). Adding IAM is therefore
a matter of one new `module_utils` plus a per-object module set — no new
dependency, no new signing code.

## Scope of v1.2.0

Nine new modules, one new `module_utils`, one new smoke playbook.

| Module | Purpose |
|---|---|
| `byteplus_iam_user` | CRUD an IAM user |
| `byteplus_iam_user_info` | List/describe users (optional access-key and attached-policy expansion) |
| `byteplus_iam_login_profile` | Console-login password for a user |
| `byteplus_iam_access_key` | Create/activate/deactivate/delete/rotate AKs |
| `byteplus_iam_policy` | CRUD a customer-managed policy |
| `byteplus_iam_policy_info` | List/describe policies (optional entity expansion) |
| `byteplus_iam_policy_attachment` | Attach/detach a policy to a user or role |
| `byteplus_iam_role` | CRUD an IAM role |
| `byteplus_iam_role_info` | List/describe roles |

Plus:

- `plugins/module_utils/iam_common.py` — `IAMClient` and helpers
- `playbooks/smoke_iam.yml` — full lifecycle smoke (excluded from tarball)
- README and CHANGELOG entries
- `galaxy.yml` version bump to `1.2.0`

## Explicitly out of scope

Deferred to a later release with its own design:

- **STS / `AssumeRole`** — not a CRUD resource; will be a `byteplus_sts_session`
  action plugin returning short-lived credentials. Different shape.
- **MFA management** — BytePlus's MFA API is under-documented and
  lockout-prone. Needs its own design including a recovery playbook.
- **Service-linked roles** — niche; defer until requested.
- **Project-scoped attachments** (`AttachPolicyInProject`) — belongs with a
  `byteplus_iam_project` module set, separate design.
- **User groups** — BytePlus IAM has no first-class groups distinct from
  attaching one policy to many users; no module needed.

## Architecture

```
plugins/
  module_utils/
    iam_common.py              # NEW — IAMClient over UniversalApi
  modules/
    byteplus_iam_user.py
    byteplus_iam_user_info.py
    byteplus_iam_login_profile.py
    byteplus_iam_access_key.py
    byteplus_iam_policy.py
    byteplus_iam_policy_info.py
    byteplus_iam_policy_attachment.py
    byteplus_iam_role.py
    byteplus_iam_role_info.py
playbooks/
  smoke_iam.yml                # NEW — live-account smoke, build-ignored
```

### `IAMClient`

`iam_common.IAMClient` wraps `byteplussdkcore.UniversalApi` with
`service='iam'`, `version='2018-01-01'`, mirroring how
`byteplus_common.BytePlusClient` wraps the DNS API. One Python method per
BytePlus IAM verb; no generic `do(action, params)` pass-through, because
the surface is small enough that the explicit verbs are reviewable and
mockable.

Methods, grouped by object:

- **Users:** `create_user`, `get_user`, `update_user`, `delete_user`,
  `list_users`
- **Login profiles:** `get_login_profile`, `create_login_profile`,
  `update_login_profile`, `delete_login_profile`
- **Access keys:** `create_access_key`, `update_access_key`,
  `delete_access_key`, `list_access_keys`
- **Policies:** `create_policy`, `get_policy`, `update_policy`,
  `delete_policy`, `list_policies`
- **Attachments:** `attach_user_policy`, `detach_user_policy`,
  `list_attached_user_policies`, `attach_role_policy`,
  `detach_role_policy`, `list_attached_role_policies`,
  `list_entities_for_policy`
- **Roles:** `create_role`, `get_role`, `update_role`, `delete_role`,
  `list_roles`

**Conventions:**

- `get_*` returns the resource dict, or `None` on NotFound. Every
  idempotency check starts "does this exist?", and `None`-vs-dict at the
  call site is cleaner than try/except in each module.
- `list_*` is an iterator that handles pagination internally. BytePlus
  IAM uses `Limit` / `Offset` and reports `IsTruncated`; the iterator
  walks the offset chain at `Limit=100` until exhausted.
- All write methods raise on failure; the request ID returned by
  BytePlus is captured and included in the raised exception message.

### Error mapping

All HTTP calls funnel through `_make_request`, analogous to the one in
`byteplus_common.py`. It classifies BytePlus error codes into three
families:

| BytePlus code family | `IAMClient` behavior |
|---|---|
| `EntityDoesNotExist*` (404-ish) | `get_*` returns `None`; other verbs raise `IAMNotFound` |
| `EntityAlreadyExists*` | Raises `IAMAlreadyExists`; modules re-`get_*` to converge |
| Anything else | Raises `IAMClientError(action, code, message, request_id)` |

Modules call `module.fail_json(msg=str(err))`. The `request_id` is
embedded in the message so a maintainer can hand it to BytePlus support
without re-running the failing playbook with `-vvv`.

### Pagination

`Limit=100`, walk `Offset` until `IsTruncated=False`. Follows the
"iterator with internal pagination" pattern from
`snapshot_common.describe_all_snapshots`.

### Check mode

Every module supports check mode using the existing collection pattern:
compute the would-be action via `get_*` and diff helpers, set `changed`,
return before any write call. No new infrastructure.

### Secret handling

- `password`, `policy_document`, and `trust_policy_document` are declared
  `no_log=True` in module argspec.
- `byteplus_iam_access_key` returns `secret_access_key` only at create
  time, only once. The return dict is registered via
  `module.no_log_values` so callbacks redact it.
- `_make_request` must not log rendered request bodies. A comment in
  `iam_common.py` calls this out so future contributors don't add
  `module.debug(params)` and silently leak secrets.

## Per-module surface

### `byteplus_iam_user`

| Parameter | Required | Mutable | Notes |
|---|---|---|---|
| `user_name` | yes | no | Primary key |
| `display_name` | no | yes | |
| `description` | no | yes | |
| `email` | no | yes | |
| `mobile_phone` | no | yes | Country-code-prefixed |
| `state` | no | n/a | `present` (default) or `absent` |

**Idempotency.** `get_user` by `user_name`. If absent and
`state=present` → `CreateUser`. If present and any mutable field drifts
→ `UpdateUser`. If `state=absent` → `DeleteUser`. Server-side delete
fails when the user still has AKs or attachments; the error is surfaced
verbatim rather than auto-cascaded — same posture as `byteplus_vpc`.

### `byteplus_iam_user_info`

| Parameter | Notes |
|---|---|
| `user_name` | If set, describe one; otherwise list all |
| `include_access_keys` | When true, add `access_keys: [{id, status, create_date}]` (never the secret) |
| `include_attached_policies` | When true, add `attached_policies` |

### `byteplus_iam_login_profile`

| Parameter | Required | Notes |
|---|---|---|
| `user_name` | yes | |
| `password` | when `state=present` | `no_log: true` |
| `password_reset_required` | no | Default `true` |
| `login_allowed` | no | Default `true` |
| `force_password_update` | no | Default `false` — without this, re-running with a different `password` is ignored |
| `state` | no | `present` (default) or `absent` |

**Idempotency.** `GetLoginProfile`. If exists and `state=present`,
`UpdateLoginProfile` runs when `password_reset_required` or
`login_allowed` drift. Passwords cannot be read back, so the module
never rotates one implicitly; `force_password_update: true` is the
explicit opt-in for pushing a new password into an existing profile.

### `byteplus_iam_access_key`

| Parameter | Required | Notes |
|---|---|---|
| `user_name` | no | Omit to manage the admin account's own keys |
| `access_key_id` | no | If supplied, addresses one specific key |
| `status` | no | `active` / `inactive` |
| `rotate` | no | See below; mutually exclusive with `access_key_id` |
| `state` | no | `present` (default) or `absent` |

**Idempotency rules:**

- `state=present` without `access_key_id`: ensure the user has at least
  one `Active` key. If none, create one and return `secret_access_key`.
  If one already exists, no-op.
- `state=present` with `access_key_id` + `status`: toggle status; no
  create.
- `state=absent` with `access_key_id`: delete that specific key.
- `rotate: true`: create a new key and return its secret. If the user
  already has any `Active` keys, deactivate the oldest one (by
  `CreateDate`); the others are left untouched. Deletion is always a
  separate explicit run. If the user already has two keys (BytePlus
  max), `rotate` fails before calling `CreateAccessKey` and tells the
  caller to delete one first — silently overwriting a key the operator
  may still be using would be unsafe.

The returned `byteplus_iam_access_key` fact is wrapped in
`module.no_log_values` so it doesn't print to Ansible logs.

### `byteplus_iam_policy`

| Parameter | Required | Mutable | Notes |
|---|---|---|---|
| `policy_name` | yes | no | Primary key |
| `policy_document` | when `state=present` | yes | JSON dict or string; canonicalized for diff |
| `description` | no | yes | |
| `state` | no | n/a | `present` (default) or `absent` |

**Customer-managed policies only.** Attempting to manage a system policy
fails with a clear error rather than silently no-opping.

**Idempotency.** Documents are compared after parse-then-key-sort, never
by raw string — the server reformats documents on the round trip.

### `byteplus_iam_policy_info`

| Parameter | Notes |
|---|---|
| `policy_name` | If set, describe one; otherwise list |
| `scope` | `Custom` / `System` / `All` (default `All`) |
| `include_entities` | When true, populate `attached_users` and `attached_roles` via `ListEntitiesForPolicy` |

### `byteplus_iam_policy_attachment`

| Parameter | Required | Notes |
|---|---|---|
| `policy_name` | yes | |
| `policy_type` | no | `Custom` (default) or `System` |
| `target_type` | yes | `user` or `role` |
| `target_name` | yes | The user name or role name |
| `state` | no | `present` (default) or `absent` |

**One module, both target kinds.** The underlying API has four verbs
(`AttachUserPolicy`, `DetachUserPolicy`, `AttachRolePolicy`,
`DetachRolePolicy`); the module dispatches by `target_type`.
Idempotency pre-checks membership via the matching `List*` verb so
`changed` is honest.

### `byteplus_iam_role`

| Parameter | Required | Mutable | Notes |
|---|---|---|---|
| `role_name` | yes | no | Primary key |
| `trust_policy_document` | when `state=present` | yes | JSON dict or string; canonicalized for diff |
| `description` | no | yes | |
| `max_session_duration` | no | yes | Seconds; BytePlus default 3600, max 43200 |
| `state` | no | n/a | `present` (default) or `absent` |

**Idempotency.** `get_role`; `UpdateRole` on drift of trust policy,
description, or max session duration. Delete fails if the role still
has attached policies; surfaced verbatim.

### `byteplus_iam_role_info`

| Parameter | Notes |
|---|---|
| `role_name` | If set, describe one; otherwise list |
| `include_attached_policies` | When true, add `attached_policies` |

## Testing

Three tiers, matching the rest of the collection:

- **`tests/sanity/`** — `ansible-test sanity` against every new module.
  No new infrastructure; existing CI already runs this.
- **`tests/unit/`** — unit tests for `iam_common.py`, covering: the
  paginator, the error-family classification, and the JSON
  canonicalization helper used by `byteplus_iam_policy` and
  `byteplus_iam_role`. Modules themselves are thin enough to skip
  dedicated unit coverage.
- **`playbooks/smoke_iam.yml`** — full lifecycle smoke against a live
  BytePlus account: user → login profile → AK → policy → attachment →
  role → cleanup. Excluded from the tarball via `galaxy.yml`
  `build_ignore`, matching `smoke_dns.yml` and `smoke_snapshot.yml`.

## Implementation order

Order matters because each step's smoke partial depends on the
previous step's module.

1. `iam_common.py` skeleton — `_make_request`, error families,
   paginator, JSON canonicalizer. Unit tests here.
2. `byteplus_iam_user` + `byteplus_iam_user_info` — simplest CRUD;
   exercises every architectural decision.
3. `byteplus_iam_policy` + `byteplus_iam_policy_info` — introduces JSON
   canonicalization.
4. `byteplus_iam_policy_attachment` — first cross-object module;
   validates the `target_type` switch.
5. `byteplus_iam_role` + `byteplus_iam_role_info` — reuses the JSON
   canonicalization from step 3.
6. `byteplus_iam_login_profile` — small surface; introduces the
   "can't read it back" pattern.
7. `byteplus_iam_access_key` — last because of the one-shot secret
   return and rotate-flag dance.
8. `playbooks/smoke_iam.yml` — full lifecycle integration test.
9. README, CHANGELOG, `galaxy.yml` 1.2.0 bump.

## Non-goals (callouts)

- **No auto-cascade on delete.** Deleting a user with active AKs errors;
  users orchestrate teardown explicitly. Same posture as
  `byteplus_vpc`.
- **No password generation.** Passwords are caller-supplied or the
  module fails. Generating inside the module makes the rotated value
  invisible and non-idempotent.
- **No policy-document linting beyond JSON parse.** Server errors on
  malformed documents are clear enough.

## Open questions

None at sign-off. STS, MFA, service-linked roles, and project-scoped
attachments are explicitly deferred and will get their own designs.
