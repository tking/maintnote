"""Shared test fixtures including verbatim examples from Section 4 of the IETF draft."""

from __future__ import annotations

import pytest

# Verbatim Section 4.1 Initial Maintenance Notification
DRAFT_EXAMPLE_4_1 = """\
BEGIN:VCALENDAR\r
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

# Verbatim Section 4.2 Updated Maintenance Notification
DRAFT_EXAMPLE_4_2 = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Maint Note//https://github.com/maint-notification//\r
BEGIN:VEVENT\r
SUMMARY:Maint Note Example\r
DTSTART;VALUE=DATE-TIME:20151012T080000Z\r
DTEND;VALUE=DATE-TIME:20151012T100000Z\r
DTSTAMP;VALUE=DATE-TIME:20151012T001000Z\r
UID:42\r
SEQUENCE:2\r
X-MAINTNOTE-PROVIDER:example.com\r
X-MAINTNOTE-ACCOUNT:137.035999173\r
X-MAINTNOTE-MAINTENANCE-ID:WorkOrder-31415\r
X-MAINTNOTE-OBJECT-ID:acme-widgets-as-a-service\r
X-MAINTNOTE-IMPACT:NO-IMPACT\r
X-MAINTNOTE-STATUS:CONFIRMED\r
ORGANIZER;CN="Example NOC":mailto:noone@example.com\r
END:VEVENT\r
END:VCALENDAR\r
"""

# Verbatim Section 4.3 Cancelled Maintenance Notification
DRAFT_EXAMPLE_4_3 = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Maint Note//https://github.com/maint-notification//\r
BEGIN:VEVENT\r
SUMMARY:Maint Note Example\r
DTSTART;VALUE=DATE-TIME:20151012T080000Z\r
DTEND;VALUE=DATE-TIME:20151012T100000Z\r
DTSTAMP;VALUE=DATE-TIME:20151012T001000Z\r
UID:42\r
SEQUENCE:3\r
X-MAINTNOTE-PROVIDER:example.com\r
X-MAINTNOTE-ACCOUNT:137.035999173\r
X-MAINTNOTE-MAINTENANCE-ID:WorkOrder-31415\r
X-MAINTNOTE-OBJECT-ID:acme-widgets-as-a-service\r
X-MAINTNOTE-IMPACT:NO-IMPACT\r
X-MAINTNOTE-STATUS:CANCELLED\r
ORGANIZER;CN="Example NOC":mailto:noone@example.com\r
END:VEVENT\r
END:VCALENDAR\r
"""

# Verbatim Section 4.4 Open Maintenance Notification
DRAFT_EXAMPLE_4_4 = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Maint Note//https://github.com/maint-notification//\r
BEGIN:VEVENT\r
SUMMARY:Open - Maint Note Example\r
DTSTART;VALUE=DATE-TIME:20151012T080000Z\r
DTEND;VALUE=DATE-TIME:20151012T100000Z\r
DTSTAMP;VALUE=DATE-TIME:20151012T001000Z\r
UID:42\r
SEQUENCE:3\r
X-MAINTNOTE-PROVIDER:example.com\r
X-MAINTNOTE-ACCOUNT:137.035999173\r
X-MAINTNOTE-MAINTENANCE-ID:WorkOrder-31415\r
X-MAINTNOTE-OBJECT-ID:acme-widgets-as-a-service\r
X-MAINTNOTE-IMPACT:NO-IMPACT\r
X-MAINTNOTE-STATUS:IN-PROCESS\r
ORGANIZER;CN="Example NOC":mailto:noone@example.com\r
END:VEVENT\r
END:VCALENDAR\r
"""

# Verbatim Section 4.5 Closed Maintenance Notification (including the draft's leading space before COMPLETED)
DRAFT_EXAMPLE_4_5 = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Maint Note//https://github.com/maint-notification//\r
BEGIN:VEVENT\r
SUMMARY:Closed - Maint Note Example\r
DTSTART;VALUE=DATE-TIME:20151012T080000Z\r
DTEND;VALUE=DATE-TIME:20151012T100000Z\r
DTSTAMP;VALUE=DATE-TIME:20151012T001000Z\r
UID:42\r
SEQUENCE:4\r
X-MAINTNOTE-PROVIDER:example.com\r
X-MAINTNOTE-ACCOUNT:137.035999173\r
X-MAINTNOTE-MAINTENANCE-ID:WorkOrder-31415\r
X-MAINTNOTE-OBJECT-ID:acme-widgets-as-a-service\r
X-MAINTNOTE-IMPACT:NO-IMPACT\r
X-MAINTNOTE-STATUS: COMPLETED\r
ORGANIZER;CN="Example NOC":mailto:noone@example.com\r
END:VEVENT\r
END:VCALENDAR\r
"""


@pytest.fixture
def example_4_1() -> str:
    return DRAFT_EXAMPLE_4_1


@pytest.fixture
def example_4_2() -> str:
    return DRAFT_EXAMPLE_4_2


@pytest.fixture
def example_4_3() -> str:
    return DRAFT_EXAMPLE_4_3


@pytest.fixture
def example_4_4() -> str:
    return DRAFT_EXAMPLE_4_4


@pytest.fixture
def example_4_5() -> str:
    return DRAFT_EXAMPLE_4_5
