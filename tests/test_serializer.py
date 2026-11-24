"""Tests for RFC 5545 serialization, round-trips, and Section 2.3.1 METHOD policy."""

from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest

from maintnote.exceptions import ValidationError
from maintnote.ical import ContentLine
from maintnote.models import (
    CalendarDocument,
    Impact,
    MaintenanceNotification,
    Organizer,
    ServiceObject,
    Status,
)
from maintnote.parser import load, parse, parse_calendar
from maintnote.serializer import dump, dumps, dumps_calendar


def test_roundtrip_preserves_all_properties_and_parameters() -> None:
    notif = MaintenanceNotification.create(
        uid="uid-roundtrip-1@example.com",
        sequence=2,
        dtstamp=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        dtstart=datetime(2026, 8, 10, 4, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 8, 10, 6, 0, tzinfo=timezone.utc),
        summary="Router upgrade; site A, rack 3",
        description="Line 1\nLine 2; details, etc.",
        location="SJC1 POP",
        url="https://status.example.com/maint/31415",
        organizer=Organizer(address="noc@example.com", cn="Example NOC"),
        provider="example.com",
        account="137.035999173",
        maintenance_id="WorkOrder-31415",
        objects=[
            ServiceObject(
                object_id="2718281828459",
                altrep="https://example.org/maintenance?id=2718281828459",
                language="en",
            ),
            ServiceObject(object_id="198.51.100.13"),
        ],
        impact=Impact.REDUCED_REDUNDANCY,
        status=Status.CONFIRMED,
        language="en-US",
        extra_calendar_properties=(ContentLine("CALSCALE", "GREGORIAN"),),
        extra_event_properties=(ContentLine("X-VENDOR-CAB", "CAB-2026-88"),),
    )

    ical_str = dumps(notif)
    assert "METHOD:" not in ical_str  # Section 2.3.1: omitted by default

    # Verify CRLF endings and <= 75 octet folding
    assert "\r\n" in ical_str
    for line in ical_str.split("\r\n"):
        if line:
            assert len(line.encode("utf-8")) <= 75

    parsed = parse(ical_str)
    assert parsed == notif


def test_method_policy_per_section_2_3_1() -> None:
    notif = MaintenanceNotification.create(
        uid="uid-method-1",
        dtstart=datetime(2026, 8, 10, 4, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 8, 10, 5, 0, tzinfo=timezone.utc),
        summary="Method test",
        organizer="noc@example.com",
        provider="example.com",
        account="acct-1",
        maintenance_id="WO-1",
        objects=["obj-1"],
        impact=Impact.NO_IMPACT,
    )

    # Default: no METHOD
    assert parse(dumps(notif)).method is None

    # Opt-in METHOD via include_method=True -> defaults to PUBLISH
    assert parse(dumps(notif, include_method=True)).method == "PUBLISH"

    # Explicit method override
    assert parse(dumps(notif, method="REQUEST")).method == "REQUEST"

    # Model has METHOD, but recipient opts out with include_method=False
    notif_with_method = notif.with_updates(method="PUBLISH")
    assert parse(dumps(notif_with_method)).method == "PUBLISH"
    assert parse(dumps(notif_with_method, include_method=False)).method is None


def test_dump_and_load_file_like_objects() -> None:
    notif = MaintenanceNotification.create(
        uid="io-test",
        dtstart=datetime(2026, 8, 10, 4, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 8, 10, 5, 0, tzinfo=timezone.utc),
        summary="IO test",
        organizer="noc@example.com",
        provider="example.com",
        account="acct-1",
        maintenance_id="WO-2",
        objects=["obj-1"],
        impact=Impact.DEGRADED,
    )
    buf = io.StringIO()
    dump(notif, buf)
    buf.seek(0)
    restored = load(buf)
    assert restored.uid == "io-test"
    assert restored.effective_impact is Impact.DEGRADED


def test_dumps_calendar_multi_event_and_empty_error() -> None:
    n1 = MaintenanceNotification.create(
        uid="multi-1",
        dtstart=datetime(2026, 8, 10, 4, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 8, 10, 5, 0, tzinfo=timezone.utc),
        summary="First",
        organizer="noc@example.com",
        provider="example.com",
        account="acct-1",
        maintenance_id="WO-1",
        objects=["obj-1"],
        impact=Impact.NO_IMPACT,
    )
    n2 = n1.with_updates(uid="multi-2", summary="Second", maintenance_id="WO-2")
    doc = CalendarDocument(notifications=(n1, n2))
    raw = dumps_calendar(doc)
    restored = parse_calendar(raw)
    assert [n.uid for n in restored.notifications] == ["multi-1", "multi-2"]

    with pytest.raises(ValidationError):
        dumps_calendar(CalendarDocument(notifications=()))
