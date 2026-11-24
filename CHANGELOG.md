# Changelog

All notable changes to `maintnote` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-24

### Added
- RFC 5545 content-line parser and serializer (`maintnote.ical`) with 75-octet UTF-8-safe line folding, unfolding, TEXT escaping, RFC 6868 parameter escaping, and UTC/TZID DATE-TIME handling.
- Typed domain models (`maintnote.models`) for all `X-MAINTNOTE-*` properties, Section 2.5.5 `OUTAGE` fallback for unknown impact values, Section 2.5.6 extensible statuses, `ServiceObject` with `ALTREP` and provider-scoped keys, `Organizer`, and multi-event `CalendarDocument`.
- Strict and lenient parser/validator (`maintnote.parser`) covering all Section 4 examples, Table 2 `X-MAINTENOTE-*` lenient compatibility, and structured `ValidationIssue` diagnostics.
- Serializer (`maintnote.serializer`) honoring Section 2.3.1 `METHOD` policy (omitted by default, opt-in per recipient).
- Complete Section 3 Provider & Consumer workflow engine (`maintnote.workflow`) implementing Initial, Updated, Cancelled, Open (`IN-PROCESS`), and Closed (`COMPLETED`) workflows, monotonic `SEQUENCE` tracking, `InMemoryStateStore`, `SQLiteStateStore`, `InMemoryTicketHandler`, and `OutOfBandVerifier`.
- Email/MIME helpers, `METHOD` pre-processing stripper, and RFC 3156 OpenPGP verification hook (`maintnote.email_utils`).
- HTTPS `ALTREP` metadata fetcher and TLS-enforced RFC 4791 CalDAV client (`maintnote.transport`).
- Command-line interface (`maintnote.cli`) for validating, parsing, generating, stripping `METHOD`, and extracting notifications from `.eml` messages.
- Full test suite, strict mypy/ruff configuration, GitHub Actions CI, and MkDocs documentation.
