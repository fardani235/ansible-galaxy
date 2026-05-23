==================================
fardani235.byteplus Release Notes
==================================

.. contents:: Topics

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
