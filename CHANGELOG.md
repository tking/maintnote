# Changelog

All notable changes to `maintnote` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-24

### Added
- RFC 5545 content-line parser and serializer (`maintnote.ical`) with 75-octet UTF-8-safe line folding, unfolding, TEXT escaping, RFC 6868 parameter escaping, UTC/IANA/custom-`VTIMEZONE` DATE-TIME & `VALUE=DATE` handling, and subcomponent (`VTIMEZONE`/`VALARM`) round-trip preservation.
- Typed domain models (`maintnote.models`) for all `X-MAINTNOTE-*` properties, Section 2.5.5 `OUTAGE` fallback for unknown impact values, Section 2.5.6 extensible statuses, `ServiceObject` with `ALTREP` and provider-scoped keys, `Organizer`, `LocalizationStrings`, and multi-event `CalendarDocument`.
- Strict and lenient parser/validator (`maintnote.parser`) covering all Section 4 examples, Table 2 `X-MAINTENOTE-*` lenient compatibility, RFC 5546 iTIP `METHOD`/`ATTENDEE` checks, RFC 5545 §3.8.7.2 UTC `DTSTAMP` check, `ALTREP` URI validation, `DISALLOWED_LANGUAGE_PARAM` on impact/status, `DUPLICATE_OBJECT_ID`, and RFC 5545 `STATUS` conflict detection (`CONFLICTING_ICAL_STATUS`).
- Serializer (`maintnote.serializer`) honoring Section 2.3.1 `METHOD` policy (omitted by default, opt-in per recipient) and preserving extra properties & subcomponents.
- Complete Section 3 Provider & Consumer workflow engine (`maintnote.workflow`) implementing Initial, Updated, Cancelled, Open (`IN-PROCESS`), and Closed (`COMPLETED`) workflows, stateful provider batch fan-out (`update_batch`, `confirm_batch`, `cancel_batch`, `open_batch`, `close_batch`), cross-provider `(provider, uid)` keying in `InMemoryStateStore` & `SQLiteStateStore`, monotonic `SEQUENCE` tracking, Section 3.2.2 `NO_OP_UPDATE` filtering, `InMemoryTicketHandler`, `LocalizationStrings`, and `OutOfBandVerifier`.
- Email/MIME helpers, `strip_method_from_ical`, email-level `strip_method_from_email`, and RFC 3156 OpenPGP signing (`OpenPGPSigner`, `sign_notification_email`) & raw-byte boundary verification (`OpenPGPVerifier`, `verify_email_signature`).
- Hardened HTTPS `ALTREP` metadata fetcher (redirect downgrade guard, SSRF private/loopback IP blocking, response size cap) and TLS-enforced RFC 4791 CalDAV client (`PROPFIND`, `REPORT` with `X-MAINTNOTE-*` `prop-filter`s & `ETag`, `GET`, `PUT`/`DELETE` with `If-Match`/`If-None-Match`).
- Command-line interface (`maintnote.cli`) for `validate`, `parse`, `generate`, `strip-method`, `strip-email-method`, and `extract-email`.
- Full test suite (54 tests, 93% branch coverage), strict mypy/ruff configuration, GitHub Actions CI, runnable examples, and MkDocs documentation.
