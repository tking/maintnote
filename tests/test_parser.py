"""Tests for parser and validator against all draft examples and edge cases."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from maintnote.exceptions import ParseError, ValidationError
from maintnote.models import Impact, Status
from maintnote.parser import parse, parse_calendar, parse_with_diagnostics, validate


def test_parse_all_five_draft_section_4_examples(
    example_4_1: str,
    example_4_2: str,
    example_4_3: str,
    example_4_4: str,
    example_4_5: str,
) -> None:
    n1 = parse(example_4_1)
    assert n1.uid == "42"
    assert n1.sequence == 1
    assert n1.provider == "example.com"
    assert n1.account == "137.035999173"
    assert n1.maintenance_id == "WorkOrder-31415"
    assert n1.object_ids == ("acme-widgets-as-a-service",)
    assert n1.effective_impact is Impact.NO_IMPACT
    assert n1.standard_status is Status.TENTATIVE
    assert n1.organizer.cn == "Example NOC"
    assert n1.organizer.address == "mailto:noone@example.com"
    assert n1.method is None
    assert n1.dtstart == datetime(2015, 10, 10, 8, 0, tzinfo=timezone.utc)
    assert n1.dtend == datetime(2015, 10, 10, 10, 0, tzinfo=timezone.utc)

    n2 = parse(example_4_2)
    assert n2.sequence == 2
    assert n2.standard_status is Status.CONFIRMED
    assert n2.dtstart == datetime(2015, 10, 12, 8, 0, tzinfo=timezone.utc)

    n3 = parse(example_4_3)
    assert n3.sequence == 3
    assert n3.standard_status is Status.CANCELLED

    n4 = parse(example_4_4)
    assert n4.sequence == 3
    assert n4.summary == "Open - Maint Note Example"
    assert n4.standard_status is Status.IN_PROCESS

    # Example 4.5 has a leading space in `X-MAINTNOTE-STATUS: COMPLETED`
    res5 = parse_with_diagnostics(example_4_5)
    assert res5.notification.sequence == 4
    assert res5.notification.standard_status is Status.COMPLETED
    assert any(w.code == "WHITESPACE_VALUE" for w in res5.warnings)


def test_parse_multiple_objects_and_altrep_and_localization() -> None:
    raw = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Test//Test//EN\r
BEGIN:VEVENT\r
SUMMARY;LANGUAGE=fr:Maintenance réseau\r
DTSTART;VALUE=DATE-TIME:20260701T000000Z\r
DTEND;VALUE=DATE-TIME:20260701T020000Z\r
DTSTAMP;VALUE=DATE-TIME:20260620T120000Z\r
UID:multi-obj-1\r
SEQUENCE:0\r
X-MAINTNOTE-PROVIDER:isp.example.org\r
X-MAINTNOTE-ACCOUNT:ACC-100\r
X-MAINTNOTE-MAINTENANCE-ID:CHG-777\r
X-MAINTNOTE-OBJECT-ID;ALTREP="https://www.peeringdb.com/api/netixlan?asn__in=64496,65536&ipaddr4__in=192.0.2.42,192.0.2.137":2718281828459\r
X-MAINTNOTE-OBJECT-ID:2001:db8::d06:f00d\r
X-MAINTNOTE-OBJECT-ID:vm-1054571726.region.example.com\r
X-MAINTNOTE-IMPACT:X-PARTIAL-BGP-DRAIN\r
ORGANIZER;CN="NOC FR":mailto:noc@isp.example.org\r
DESCRIPTION;LANGUAGE=fr:Remplacement de carte optique\r
X-CUSTOM-TICKET-REF:INTERNAL-99\r
END:VEVENT\r
END:VCALENDAR\r
"""
    res = parse_with_diagnostics(raw)
    notif = res.notification
    assert notif.status is None  # X-MAINTNOTE-STATUS is optional (0 or 1)
    assert len(notif.objects) == 3
    assert notif.objects[0].altrep == (
        "https://www.peeringdb.com/api/netixlan?asn__in=64496,65536&ipaddr4__in=192.0.2.42,192.0.2.137"
    )
    assert notif.objects[1].object_id == "2001:db8::d06:f00d"
    assert notif.impact.raw == "X-PARTIAL-BGP-DRAIN"
    assert notif.effective_impact is Impact.OUTAGE
    assert notif.summary_params == {"LANGUAGE": ("fr",)}
    assert notif.description == "Remplacement de carte optique"
    assert any(prop.name == "X-CUSTOM-TICKET-REF" for prop in notif.extra_event_properties)
    assert any(w.code == "NONSTANDARD_IMPACT" for w in res.warnings)


def test_lenient_mode_accepts_draft_table_2_typo_with_warning() -> None:
    raw = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Legacy//EN\r
BEGIN:VEVENT\r
SUMMARY:Legacy Vendor Typo\r
DTSTART:20260701T000000Z\r
DTEND:20260701T010000Z\r
DTSTAMP:20260620T000000Z\r
UID:typo-1\r
SEQUENCE:0\r
X-MAINTENOTE-PROVIDER:legacy.example\r
X-MAINTENOTE-ACCOUNT:A1\r
X-MAINTENOTE-MAINTENANCE-ID:M1\r
X-MAINTENOTE-OBJECT-ID:OBJ1\r
X-MAINTENOTE-IMPACT:DEGRADED\r
X-MAINTENOTE-STATUS:CONFIRMED\r
ORGANIZER:mailto:noc@legacy.example\r
END:VEVENT\r
END:VCALENDAR\r
"""
    with pytest.raises(ValidationError):
        parse(raw, strict=True)

    result = parse_with_diagnostics(raw, strict=False)
    assert result.notification.provider == "legacy.example"
    assert result.notification.effective_impact is Impact.DEGRADED
    typo_warnings = [w for w in result.warnings if w.code == "LEGACY_TYPO_PROPERTY"]
    assert len(typo_warnings) == 6


def test_parse_validation_failures() -> None:
    # Missing mandatory fields
    incomplete = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Test//EN\r
BEGIN:VEVENT\r
UID:1\r
SUMMARY:Missing fields\r
END:VEVENT\r
END:VCALENDAR\r
"""
    with pytest.raises(ValidationError) as exc_info:
        parse(incomplete)
    missing_props = {issue.property_name for issue in exc_info.value.issues}
    assert "X-MAINTNOTE-PROVIDER" in missing_props
    assert "X-MAINTNOTE-OBJECT-ID" in missing_props
    assert "X-MAINTNOTE-IMPACT" in missing_props
    assert "SEQUENCE" in missing_props

    # DTEND before DTSTART
    bad_window = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Test//EN\r
BEGIN:VEVENT\r
SUMMARY:Bad Window\r
DTSTART:20260701T050000Z\r
DTEND:20260701T020000Z\r
DTSTAMP:20260620T000000Z\r
UID:bad-win\r
SEQUENCE:0\r
X-MAINTNOTE-PROVIDER:example.com\r
X-MAINTNOTE-ACCOUNT:1\r
X-MAINTNOTE-MAINTENANCE-ID:M1\r
X-MAINTNOTE-OBJECT-ID:O1\r
X-MAINTNOTE-IMPACT:OUTAGE\r
ORGANIZER:mailto:noc@example.com\r
END:VEVENT\r
END:VCALENDAR\r
"""
    with pytest.raises(ValidationError) as exc_win:
        parse(bad_window)
    assert any(i.code == "INVALID_TIME_RANGE" for i in exc_win.value.issues)


def test_parse_multi_event_calendar_document() -> None:
    raw = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Batch//EN\r
BEGIN:VEVENT\r
SUMMARY:Event 1\r
DTSTART:20260701T010000Z\r
DTEND:20260701T020000Z\r
DTSTAMP:20260620T000000Z\r
UID:e1\r
SEQUENCE:0\r
X-MAINTNOTE-PROVIDER:example.com\r
X-MAINTNOTE-ACCOUNT:1\r
X-MAINTNOTE-MAINTENANCE-ID:M1\r
X-MAINTNOTE-OBJECT-ID:O1\r
X-MAINTNOTE-IMPACT:NO-IMPACT\r
ORGANIZER:mailto:noc@example.com\r
END:VEVENT\r
BEGIN:VEVENT\r
SUMMARY:Event 2\r
DTSTART:20260702T010000Z\r
DTEND:20260702T020000Z\r
DTSTAMP:20260620T000000Z\r
UID:e2\r
SEQUENCE:0\r
X-MAINTNOTE-PROVIDER:example.com\r
X-MAINTNOTE-ACCOUNT:1\r
X-MAINTNOTE-MAINTENANCE-ID:M2\r
X-MAINTNOTE-OBJECT-ID:O2\r
X-MAINTNOTE-IMPACT:OUTAGE\r
ORGANIZER:mailto:noc@example.com\r
END:VEVENT\r
END:VCALENDAR\r
"""
    doc = parse_calendar(raw)
    assert len(doc.notifications) == 2
    assert [n.uid for n in doc.notifications] == ["e1", "e2"]
    with pytest.raises(ParseError):
        parse(raw)


def test_parse_invalid_utf8_bytes() -> None:
    with pytest.raises(ParseError, match="UTF-8"):
        parse(b"\xff\xfe\xfd")


def test_validate_reports_clean_notification() -> None:
    notif = parse(
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//T//EN\r\nBEGIN:VEVENT\r\n"
        "SUMMARY:OK\r\nDTSTART:20260101T000000Z\r\nDTEND:20260101T010000Z\r\n"
        "DTSTAMP:20260101T000000Z\r\nUID:ok-1\r\nSEQUENCE:0\r\n"
        "X-MAINTNOTE-PROVIDER:example.com\r\nX-MAINTNOTE-ACCOUNT:1\r\n"
        "X-MAINTNOTE-MAINTENANCE-ID:M1\r\nX-MAINTNOTE-OBJECT-ID:O1\r\n"
        "X-MAINTNOTE-IMPACT:NO-IMPACT\r\nX-MAINTNOTE-STATUS:CONFIRMED\r\n"
        "ORGANIZER:mailto:noc@example.com\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    assert validate(notif) == []
