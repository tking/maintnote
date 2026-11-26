# Getting Started

This guide explains how to install `maintnote`, parse and create `.ics` maintenance notifications in Python, and run the CLI.

## Requirements

- Python **3.10 or newer**.
- No external runtime packages (`maintnote` uses only the Python standard library).

## Install `maintnote`

Run `pip` from the repository root:

```bash
pip install -e .
```

To install the test, lint, and documentation tools also, run:

```bash
pip install -e ".[dev,docs]"
```

## Parse an `.ics` Maintenance Notification

Call `parse()` to convert an iCalendar string or bytes object into a typed `MaintenanceNotification`:

```python
from maintnote import parse

raw_ics = """BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Maint Note//https://github.com/maint-notification//\r
BEGIN:VEVENT\r
SUMMARY:Maint Note Example\r
DTSTART;VALUE=DATE-TIME:20151010T080000Z\r
DTEND;VALUE=DATE-TIME:20151010T100000Z\r
DTSTAMP;VALUE=DATE-TIME:20151010T001000Z\r
UID:42\r
SEQUENCE:1\r
X-MAINTNOTE-PROVIDER:example.com\r
X-MAINTNOTE-ACCOUNT:137.035999173\r
X-MAINTNOTE-MAINTENANCE-ID:WorkOrder-31415\r
X-MAINTNOTE-OBJECT-ID:acme-widgets-as-a-service\r
X-MAINTNOTE-IMPACT:NO-IMPACT\r
X-MAINTNOTE-STATUS:TENTATIVE\r
ORGANIZER;CN="Example NOC":mailto:noone@example.com\r
END:VEVENT\r
END:VCALENDAR\r
"""

notif = parse(raw_ics)
print(notif.provider)          # example.com
print(notif.maintenance_id)    # WorkOrder-31415
print(notif.effective_impact)  # Impact.NO_IMPACT
print(notif.standard_status)   # Status.TENTATIVE
```

If an `.ics` file contains more than one `VEVENT`, call `parse_calendar()`.
For example, a CalDAV calendar feed usually contains more than one `VEVENT`.

### Strict and Lenient Modes

By default, `parse(..., strict=True)` checks every `MUST` rule in the draft.
If the input violates a rule, `parse()` raises `ValidationError`.

Some third-party vendors send notifications with minor format defects.
For example, a vendor can use the `X-MAINTENOTE-*` typo from Table 2 of the draft.
To accept those notifications and inspect warnings, call `parse_with_diagnostics()` with `strict=False`:

```python
from maintnote import parse_with_diagnostics

result = parse_with_diagnostics(vendor_ics, strict=False)
notif = result.notification
for warning in result.warnings:
    print(warning)
```

## Create and Serialize a Notification

Call `MaintenanceNotification.create()` to build a valid notification.
Then call `dumps()` to serialize the notification as RFC 5545 text:

```python
from datetime import datetime, timezone
from maintnote import Impact, MaintenanceNotification, Organizer, ServiceObject, Status, dumps

notif = MaintenanceNotification.create(
    uid="maint-2026-0042@example.com",
    sequence=0,
    dtstart=datetime(2026, 11, 15, 2, 0, tzinfo=timezone.utc),
    dtend=datetime(2026, 11, 15, 4, 0, tzinfo=timezone.utc),
    summary="Core router software upgrade",
    organizer=Organizer("noc@example.com", cn="Example NOC"),
    provider="example.com",
    account="137.035999173",
    maintenance_id="WorkOrder-31415",
    objects=[
        ServiceObject(
            object_id="2718281828459",
            altrep="https://example.org/maintenance?id=2718281828459",
        )
    ],
    impact=Impact.DEGRADED,
    status=Status.TENTATIVE,
)

ical_output = dumps(notif)
```

!!! note
    `dumps()` does not include the `METHOD` property by default.
    This prevents email clients from automatically adding notifications to personal calendars (Section 2.3.1).

## Run the Command-Line Interface

Package installation adds the `maintnote` command to your `PATH`.
Run the CLI subcommands against the sample files in `examples/samples/`:

```bash
# Validate a sample .ics notification and print JSON diagnostics
maintnote validate examples/samples/01_initial.ics --json

# Parse a multi-event feed and show all events
maintnote parse examples/samples/multi_event_feed.ics

# Remove METHOD from a legacy .ics file
maintnote strip-method examples/samples/legacy_with_method.ics

# Extract notifications from an email (.eml) file
maintnote extract-email examples/samples/legacy_provider.eml --strip-method --json
```

For shell scripts and DevOps pipelines, `maintnote` supports these automation conventions:

- Pass `-` as the file path to read `.ics` or `.eml` data from `stdin`.
- Pass `--json` to `validate`, `parse`, or `extract-email` for machine-readable output.
- Check the process exit code: `maintnote` returns `0` on success and `1` on error.

To test the full CLI lifecycle (`initial`, `confirm`, `open`, and `close`), run `examples/cli_walkthrough.sh`.

## Next Steps

- Read [Provider and Consumer Workflows](workflows.md) to manage lifecycle transitions, batch fan-out, and SQLite state tracking.
- Read [Security and Transport](security-and-transport.md) to add OpenPGP email verification, `ALTREP` downloads, or CalDAV sync.
- Run the scripts in `examples/` to test each feature offline.
