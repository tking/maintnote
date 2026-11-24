# Getting Started

## Requirements

- Python **3.10 or newer**
- Zero runtime dependencies (uses only the Python standard library)

## Installation

```bash
pip install -e .
```

## Parsing an Existing `.ics` Maintenance Notification

```python
from maintnote import parse, parse_with_diagnostics

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

### Strict vs. Lenient Parsing

By default, `parse(..., strict=True)` enforces all MUST-level rules in the draft.
When consuming notifications from third-party vendors with minor formatting quirks (for example, vendors that copied the `X-MAINTENOTE-*` typo from Table 2 of the draft), use `strict=False` with `parse_with_diagnostics()`:

```python
result = parse_with_diagnostics(vendor_ics, strict=False)
notif = result.notification
for warning in result.warnings:
    print(warning)
```

## Creating and Serializing a Notification

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
