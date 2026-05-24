==================================
fardani235.byteplus Release Notes
==================================

.. contents:: Topics

v1.1.0
======

Minor Changes
-------------

- Add ``byteplus_ecs_snapshot`` module - create/delete a snapshot of a
  single BytePlus EBS volume. Supports check mode, idempotent lookup
  by ``snapshot_id`` or ``snapshot_name``, retention days, project
  scoping, tags, and wait-for-available.
- Add ``byteplus_ecs_snapshot_group`` module - manage instance-wide,
  multi-volume snapshot groups (the canonical "instance snapshot"
  flow). Supports ``state=present``, ``absent``, and ``rolled_back``.
  Rollback is strict: it fails fast if the target instance is not
  already in the ``STOPPED`` state, rather than silently powering off
  a running workload. When ``volume_ids`` is omitted, the module
  discovers every volume attached to the instance and includes them
  all, because the BytePlus ``CreateSnapshotGroup`` server rejects
  requests without a populated ``VolumeIds`` (despite the SDK marking
  the field optional).
- Add ``byteplus_ecs_snapshot_info`` module - read-only listing of EBS
  snapshots and snapshot groups, with ``kind`` selecting which
  endpoint to query. Pagination is handled automatically.
- Add ``snapshot_common`` module_utils with ``SnapshotClient`` wrapping
  ``byteplussdkstorageebs.STORAGEEBSApi``, plus paginated describe
  helpers (``describe_all_snapshots`` follows ``NextToken``,
  ``describe_all_snapshot_groups`` follows ``PageNumber``) and
  wait-for-state polling tuned for the long create times typical of
  large EBS volumes.

v1.0.2
======

Bugfixes
--------

- byteplus_dns_record - Fix ``UpdateRecord`` calls failing with an opaque
  ``Bad Request`` when the caller did not specify ``line``. The BytePlus
  DNS ``UpdateRecord`` API requires ``Line`` in the request body, so the
  module now preserves the existing record's line on update rather than
  omitting the field. Defaults to ``default`` only if the existing record
  has no line set.
- byteplus_dns_record - Fix idempotency lookups silently missing records
  whose host matched as a substring of a different host (or vice versa).
  The module now passes ``SearchMode=exact`` to the BytePlus
  ``ListRecords`` API, which defaults to fuzzy (``like``) matching on the
  Host filter. This makes the ``state: present`` duplicate-detection path
  deterministic across hosts that share prefixes (e.g. ``www`` vs
  ``www2``).

v1.0.1
======

Release Summary
---------------

Initial public release.
