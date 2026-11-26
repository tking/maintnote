# maintnote

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](pyproject.toml)
[![Typed: PEP 561](https://img.shields.io/badge/typing-strict-brightgreen.svg)](src/maintnote/py.typed)

`maintnote` is a Python 3.10+ library and command-line tool (CLI) for network maintenance notifications.
It implements IETF [**`draft-gunter-calext-maintenance-notifications-00`**](https://datatracker.ietf.org/doc/html/draft-gunter-calext-maintenance-notifications-00) (*Maintenance Notification Improvements Using iCalendar*).

Network operators usually send maintenance notifications as free-form emails that make automation unreliable.
This specification puts structured `X-MAINTNOTE-*` fields inside standard RFC 5545 iCalendar (`.ics`) events.
With `maintnote`, software developers, network engineers, and DevOps engineers can generate, validate, and automate maintenance windows.

`maintnote` uses only the Python standard library at runtime and includes full `mypy --strict` type annotations (`py.typed`).

---

## Core Concepts

Two roles use `maintnote`:

- **Provider:** A carrier, internet exchange, or cloud operator that creates and updates maintenance notifications for customer accounts.
- **Consumer:** A customer network operations center (NOC), DevOps pipeline, or ticketing service that parses notifications, tracks state, and runs automation.

Each notification identifies one maintenance event with a unique `UID` and a `SEQUENCE` number that increases on each update.
It also lists one or more affected service objects, an impact level, and an optional lifecycle status.

---

## Features

- **RFC 5545 and `X-MAINTNOTE-*` parsing and validation**
  - Parse and validate all mandatory and optional properties: `X-MAINTNOTE-PROVIDER`, `X-MAINTNOTE-ACCOUNT`, `X-MAINTNOTE-MAINTENANCE-ID`, `X-MAINTNOTE-OBJECT-ID` (with optional `ALTREP` URIs), `X-MAINTNOTE-IMPACT`, and `X-MAINTNOTE-STATUS`.
  - Keep unknown `x-name` or `iana-token` impact values as sent, and map `effective_impact` to `Impact.OUTAGE` (Section 2.5.5).
  - Omit the `METHOD` property by default so email clients do not automatically add notifications to personal calendars (Section 2.3.1).
  - Support per-recipient `METHOD` opt-in for providers and `METHOD` removal for consumers.
  - Support `LANGUAGE` property parameters and 75-octet line folding that is safe for UTF-8 (Section 5.1).
  - Accept common third-party quirks in lenient mode (`strict=False`) and return structured warnings.
- **Provider and consumer workflow engine (Section 3)**
  - Run all five lifecycle stages: Initial (3.1), Updated (3.2), Cancelled (3.3), Open or `IN-PROCESS` (3.4), and Closed or `COMPLETED` (3.5).
  - Keep `UID` values stable across updates, increase `SEQUENCE` numbers, and ignore duplicate or stale notifications.
  - Isolate object IDs by `(provider, object_id)` so identical circuit IDs from different carriers do not collide.
  - Connect custom storage (`StateStore`), ticketing (`TicketHandler`), and out-of-band checks (`OutOfBandVerifier`).
  - Use the built-in `InMemoryStateStore`, `SQLiteStateStore`, and `InMemoryTicketHandler` classes directly.
- **Email, OpenPGP, `ALTREP`, and CalDAV transport (Section 5.2)**
  - Build and parse RFC 5322 emails with `text/calendar` (`.ics`) attachments.
  - Sign and verify RFC 3156 `multipart/signed` OpenPGP emails over raw MIME bytes.
  - Get external JSON metadata (for example, PeeringDB data) from `ALTREP` URIs over HTTPS with redirect and private-IP protection.
  - Discover, query, get, publish, and delete events on a CalDAV server over TLS (RFC 4791).
- **Built-in CLI (`maintnote`)**
  - Validate, parse, generate, transition, remove `METHOD`, and extract notifications from `.ics` and `.eml` files.
  - Support `--json` output and `stdin` (`-`) for shell scripts and DevOps pipelines.

---

## Installation

Install the package:

```bash
pip install -e .
```

Install the development tools (`pytest`, `pytest-cov`, `ruff`, and `mypy`):

```bash
pip install -e ".[dev]"
```

Install the documentation tools (`mkdocs` and `mkdocs-material`):

```bash
pip install -e ".[docs]"
```

---

## Quick Start

### 1. Create and Update a Notification as a Provider

Use `MaintenanceProvider` to create an initial notification and move it through each lifecycle state:

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

# Section 3.1: Initial notification (SEQUENCE=0, STATUS=TENTATIVE, no METHOD)
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

# Section 3.2: Confirm and reschedule (same UID, SEQUENCE=1)
confirmed = provider.confirm(
    initial,
    dtstart=datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc),
    dtend=datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc),
)

# Section 3.4: Open the maintenance window (SEQUENCE=2, STATUS=IN-PROCESS)
opened = provider.open_window(confirmed, description="Maintenance window is now open.")

# Section 3.5: Close the maintenance window (SEQUENCE=3, STATUS=COMPLETED)
closed = provider.close_window(opened, description="Work complete; services restored.")

# Section 3.3: Cancel an active maintenance window instead
cancelled = provider.cancel(confirmed, description="Maintenance no longer required.")

print(dumps(initial))
```

### 2. Process Notifications as a Consumer

Use `MaintenanceConsumer` with `SQLiteStateStore` to track `(provider, uid)` state, check `SEQUENCE` order, and call a ticket handler:

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

result = consumer.process(dumps(initial))
print(result.action, result.ticket_id, result.priority, result.assign_to_remediation_queue)
# WorkflowAction.INITIAL OPS-0001 TicketPriority.CRITICAL False

store.close()
```

### 3. Send and Extract Email Attachments

Call `build_notification_email()` to attach an `.ics` notification to an email.
Call `extract_notifications_from_email()` to parse received emails:

```python
from maintnote import build_notification_email, extract_notifications_from_email

msg = build_notification_email(
    initial,
    sender="noc@example.com",
    recipient="ops@customer.example",
)
notifications = extract_notifications_from_email(msg, strip_method=True)
```

### 4. Use the Command-Line Interface

Run `maintnote` directly on `.ics` and `.eml` files, or pass `-` to read from `stdin`:

```bash
# Validate a maintenance notification and print JSON diagnostics
maintnote validate examples/samples/01_initial.ics --json

# Parse a notification and show its fields
maintnote parse examples/samples/01_initial.ics

# Generate an initial notification and transition it to open and closed
maintnote generate --action initial \
  --provider example.com --account 137.035999173 \
  --maintenance-id WorkOrder-31415 --object-id acme-widgets-as-a-service \
  --impact OUTAGE --summary "Router upgrade" \
  --organizer noc@example.com --organizer-cn "Example NOC" \
  --dtstart 2026-10-10T08:00:00Z --dtend 2026-10-10T10:00:00Z \
  -o initial.ics

maintnote generate --action open --from-file initial.ics -o open.ics
maintnote generate --action close --from-file open.ics -o close.ics

# Remove METHOD before you forward a notification to personal calendars (Section 2.3.1)
maintnote strip-method examples/samples/legacy_with_method.ics

# Extract notifications from an email file
maintnote extract-email examples/samples/legacy_provider.eml --strip-method --json
```

---

## Examples

Python example scripts, sample `.ics` and `.eml` files, and a CLI walkthrough are in [`examples/`](examples/):

| Example | Purpose |
| --- | --- |
| [`examples/provider_lifecycle.py`](examples/provider_lifecycle.py) | Run the provider lifecycle from initial notification through completion |
| [`examples/consumer_pipeline.py`](examples/consumer_pipeline.py) | Extract emails, track state in SQLite, and reject stale notifications |
| [`examples/multi_customer_batch.py`](examples/multi_customer_batch.py) | Send one maintenance notification to more than one account with per-account `METHOD` settings and cancel the batch |
| [`examples/multi_provider_automation.py`](examples/multi_provider_automation.py) | Isolate `(provider, object_id)` pairs, use a custom `TicketHandler`, test `OUTAGE` fallback, and run `OutOfBandVerifier` |
| [`examples/signed_email_and_sanitization.py`](examples/signed_email_and_sanitization.py) | Sign and verify RFC 3156 OpenPGP emails, detect tampering, and remove `METHOD` from emails |
| [`examples/caldav_and_altrep_demo.py`](examples/caldav_and_altrep_demo.py) | Run an offline mock CalDAV server (`PROPFIND`, `PUT` with `ETag`, `REPORT`, `GET`, `DELETE`) and test `ALTREP` SSRF checks |
| [`examples/localization_and_lenient_parsing.py`](examples/localization_and_lenient_parsing.py) | Use `LocalizationStrings`, `LANGUAGE` parameters, `VTIMEZONE`, `VALARM`, and lenient diagnostics |
| [`examples/cli_walkthrough.sh`](examples/cli_walkthrough.sh) | Run every `maintnote` CLI subcommand against the files in [`examples/samples/`](examples/samples/) |

---

## Documentation

Read the full guides in [`docs/`](docs/):

- [Overview](docs/index.md)
- [Getting Started](docs/getting-started.md)
- [Specification Compliance Matrix](docs/specification-compliance.md)
- [Provider and Consumer Workflows](docs/workflows.md)
- [Security and Transport](docs/security-and-transport.md)
- [API Reference](docs/api-reference.md)

---

## Development and Testing

Run the local checks before you open a Pull Request:

```bash
# Run unit and integration tests
PYTHONPATH=src pytest -v

# Check lint rules and formatting
ruff check src tests
ruff format --check src tests

# Run strict static type checks
MYPYPATH=src mypy src tests
```

To run lint, type checks, and tests with one command, run:

```bash
make check
```

To build the documentation in strict mode, run:

```bash
make docs
```

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the full Pull Request and coding rules.

---

## License

This project uses the **GNU General Public License v3.0 or later (`GPL-3.0-or-later`)**.
Read [LICENSE](LICENSE) for the full license text.
