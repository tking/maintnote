# maintnote

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](pyproject.toml)
[![Typed: PEP 561](https://img.shields.io/badge/typing-strict-brightgreen.svg)](src/maintnote/py.typed)

**`maintnote`** is a pure-Python 3.10+ library and CLI implementing the IETF Internet-Draft
[**`draft-gunter-calext-maintenance-notifications-00`**](https://datatracker.ietf.org/doc/html/draft-gunter-calext-maintenance-notifications-00)
(*Maintenance Notification Improvements Using iCalendar*, originating from the NANOG BCOP standard).

It has **zero mandatory runtime dependencies**, is strictly typed (`mypy --strict`, PEP 561 `py.typed`), and covers every property, workflow, transport, and security consideration described in the specification.

---

## Features

- **Full RFC 5545 & `X-MAINTNOTE-*` Support**
  - Strict and lenient parsing & validation of all required and optional properties:
    `X-MAINTNOTE-PROVIDER`, `X-MAINTNOTE-ACCOUNT`, `X-MAINTNOTE-MAINTENANCE-ID`,
    `X-MAINTNOTE-OBJECT-ID` (single or multiple, with `ALTREP` URIs), `X-MAINTNOTE-IMPACT`,
    and `X-MAINTNOTE-STATUS`.
  - Section 2.5.5 `OUTAGE` fallback: unknown `x-name` / `iana-token` impact values are preserved
    verbatim while `effective_impact` safely defaults to `Impact.OUTAGE`.
  - Section 2.3.1 `METHOD` policy: omitted by default, with per-recipient opt-in on the provider
    side and `strip_method_from_ical()` pre-processing on the consumer side.
  - Section 5.1 Localization (`LANGUAGE` property parameters and UTF-8 octet-safe 75-byte line folding).
  - Lenient interoperability mode handles real-world quirks (including the draft's Table 2
    `X-MAINTENOTE-*` typo and Example 4.5 leading whitespace) with structured warnings.
- **Complete Provider & Consumer Workflow Engine (Section 3)**
  - All 5 lifecycle workflows: **Initial (3.1)**, **Updated (3.2)**, **Cancelled (3.3)**,
    **Open / `IN-PROCESS` (3.4)**, and **Closed / `COMPLETED` (3.5)**.
  - Automatic `UID` preservation, monotonic `SEQUENCE` tracking, duplicate & out-of-order
    protection, structured field diffs, and cross-provider `(provider, object_id)` scoping.
  - Pluggable `StateStore` (with built-in `InMemoryStateStore` and `SQLiteStateStore`),
    pluggable `TicketHandler` (with `InMemoryTicketHandler`), and optional Section 5.2
    `OutOfBandVerifier`.
- **Email/MIME, OpenPGP (RFC 3156), ALTREP (RFC 7159), & CalDAV over TLS (RFC 4791)**
  - Build and extract `text/calendar` / `.ics` email attachments.
  - Extract and verify RFC 3156 `multipart/signed` OpenPGP signatures via pluggable verifier hook.
  - Fetch external `ALTREP` JSON metadata (e.g., PeeringDB APIs) over HTTPS.
  - Pull, publish, and delete maintenance events over TLS-enforced CalDAV (`REPORT`, `PUT`, `DELETE`).
- **Built-in CLI (`maintnote`)**
  - Validate, parse, generate/transition, strip `METHOD`, and extract from `.eml` files.

---

## Installation

```bash
pip install -e .
```

For development (testing, linting, type checking, coverage):

```bash
pip install -e ".[dev]"
```

For documentation builds:

```bash
pip install -e ".[docs]"
```

---

## Quick Start

### 1. Provider: Creating and Transitioning a Maintenance Lifecycle

```python
from datetime import datetime, timezone
from maintnote import (
    Impact,
    MaintenanceProvider,
    Organizer,
    ServiceObject,
    dumps,
)

provider = MaintenanceProvider(
    provider="example.com",
    organizer=Organizer("noc@example.com", cn="Example NOC"),
)

# 3.1 Initial Maintenance Notification (SEQUENCE=0, STATUS=TENTATIVE, no METHOD by default)
initial = provider.create_initial(
    account="137.035999173",
    maintenance_id="WorkOrder-31415",
    objects=[
        ServiceObject(
            object_id="2718281828459",
            altrep="https://example.org/maintenance?id=2718281828459",
        ),
        ServiceObject(object_id="2001:db8::d06:f00d"),
    ],
    dtstart=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc),
    dtend=datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc),
    summary="Core optical linecard upgrade",
    impact=Impact.OUTAGE,
)

# 3.2 Update & Confirm Window (preserves UID, increments SEQUENCE -> 1)
confirmed = provider.confirm(
    initial,
    dtstart=datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc),
    dtend=datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc),
)

# 3.4 Open Window (SEQUENCE -> 2, STATUS=IN-PROCESS)
opened = provider.open_window(confirmed, description="Maintenance window is now open.")

# 3.5 Close Window (SEQUENCE -> 3, STATUS=COMPLETED)
closed = provider.close_window(opened, description="Work complete; services restored.")

# Or 3.3 Cancel Window (from an active notification)
cancelled = provider.cancel(confirmed, description="Maintenance no longer required.")

print(dumps(initial))
```

### 2. Consumer: Automated Processing with SQLite State Tracking

```python
from maintnote import (
    InMemoryTicketHandler,
    MaintenanceConsumer,
    SQLiteStateStore,
    dumps,
)

store = SQLiteStateStore("maintenances.db")
handler = InMemoryTicketHandler(prefix="OPS")
consumer = MaintenanceConsumer(store=store, handler=handler)

# Process incoming .ics payloads (automatically handles UID correlation,
# SEQUENCE ordering, priority elevation, and TENTATIVE queue holding)
result = consumer.process(dumps(initial))
print(result.action, result.ticket_id, result.priority, result.assign_to_remediation_queue)
# WorkflowAction.INITIAL OPS-0001 TicketPriority.CRITICAL False

store.close()
```

### 3. Email/MIME & RFC 3156 OpenPGP Verification

```python
from maintnote import build_notification_email, extract_notifications_from_email

msg = build_notification_email(
    initial,
    sender="noc@example.com",
    recipient="ops@customer.example",
)
notifications = extract_notifications_from_email(msg, strip_method=True)
```

### 4. Command-Line Interface

```bash
# Validate an .ics maintenance notification
maintnote validate notice.ics --json

# Parse and inspect fields
maintnote parse notice.ics

# Generate an initial notification and transition it
maintnote generate --action initial \
  --provider example.com --account 137.035999173 \
  --maintenance-id WorkOrder-31415 --object-id acme-widgets-as-a-service \
  --impact OUTAGE --summary "Router upgrade" \
  --organizer noc@example.com --organizer-cn "Example NOC" \
  --dtstart 2026-10-10T08:00:00Z --dtend 2026-10-10T10:00:00Z \
  -o initial.ics

maintnote generate --action open --from-file initial.ics -o open.ics
maintnote generate --action close --from-file open.ics -o close.ics

# Strip METHOD before forwarding to personal calendars (Section 2.3.1)
maintnote strip-method notice.ics

# Extract notifications from an email (.eml)
maintnote extract-email message.eml --json
```

---

## Examples

Runnable Python scripts, sample `.ics` / `.eml` fixtures, and a CLI walkthrough live in [`examples/`](examples/):

| Example | What it demonstrates |
| --- | --- |
| [`examples/provider_lifecycle.py`](examples/provider_lifecycle.py) | Provider-side initial → confirmed → open → closed lifecycle |
| [`examples/consumer_pipeline.py`](examples/consumer_pipeline.py) | Consumer email extraction, SQLite state tracking, and out-of-order protection |
| [`examples/multi_customer_batch.py`](examples/multi_customer_batch.py) | Multi-customer batch fan-out, per-recipient `METHOD` opt-in, cancellation, and terminal-state guards |
| [`examples/multi_provider_automation.py`](examples/multi_provider_automation.py) | Scoped `(provider, object_id)` isolation, custom `TicketHandler`, `OUTAGE` fallback, and `OutOfBandVerifier` |
| [`examples/signed_email_and_sanitization.py`](examples/signed_email_and_sanitization.py) | RFC 3156 OpenPGP signing/verification, tamper detection, and `METHOD` email sanitization |
| [`examples/caldav_and_altrep_demo.py`](examples/caldav_and_altrep_demo.py) | Offline mock CalDAV server (`PROPFIND`, `PUT` + `ETag`, `REPORT`, `GET`, `DELETE`) and `ALTREP` SSRF protection |
| [`examples/localization_and_lenient_parsing.py`](examples/localization_and_lenient_parsing.py) | Section 5.1 `LocalizationStrings`, `LANGUAGE` params, `VTIMEZONE`/`VALARM`, and lenient diagnostics |
| [`examples/cli_walkthrough.sh`](examples/cli_walkthrough.sh) | End-to-end `maintnote` CLI walkthrough using [`examples/samples/`](examples/samples/) |

---

## Documentation

Full documentation is available in [`docs/`](docs/):

- [Getting Started](docs/getting-started.md)
- [Specification Compliance Matrix](docs/specification-compliance.md)
- [Provider & Consumer Workflows](docs/workflows.md)
- [Security, Email, ALTREP & CalDAV](docs/security-and-transport.md)
- [API Reference](docs/api-reference.md)

---

## Development & Testing

```bash
# Run unit & integration tests
PYTHONPATH=src pytest -v

# Lint and format check
ruff check src tests
ruff format --check src tests

# Strict static type checking
MYPYPATH=src mypy src
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for full contributor guidelines.

---

## License

This project is licensed under the **GNU General Public License v3.0 or later (GPL-3.0-or-later)**.
See [LICENSE](LICENSE) for the full license text.
