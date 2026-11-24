"""Comprehensive edge-case tests covering draft nuances, validation branches, transport errors, and CLI modes."""

from __future__ import annotations

import io
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import pytest

from maintnote.cli import main
from maintnote.email_utils import (
    build_notification_email,
    extract_notifications_from_email,
    extract_pgp_signed_parts,
)
from maintnote.exceptions import ParseError, TransportError, ValidationError, VerificationError
from maintnote.ical import ContentLine
from maintnote.models import (
    Impact,
    ImpactValue,
    MaintenanceNotification,
    Organizer,
    ServiceObject,
    Status,
    StatusValue,
)
from maintnote.parser import parse, parse_with_diagnostics, validate
from maintnote.serializer import dumps
from maintnote.transport import CalDAVClient, fetch_altrep_metadata
from maintnote.workflow import (
    InMemoryStateStore,
    InMemoryTicketHandler,
    MaintenanceConsumer,
    MaintenanceProvider,
    SQLiteStateStore,
    WorkflowAction,
    compute_diff,
)


def test_all_seven_section_2_5_4_object_id_examples_roundtrip() -> None:
    """Tests every X-MAINTNOTE-OBJECT-ID format shown in Section 2.5.4 of the draft."""
    objects = [
        ServiceObject(object_id="2718281828459"),
        ServiceObject(
            object_id="2718281828459",
            altrep="https://example.org/maintenance?id=2718281828459",
        ),
        ServiceObject(
            object_id="2718281828459",
            altrep="https://www.peeringdb.com/api/netixlan?asn__in=64496,65536&ipaddr4__in=192.0.2.42,192.0.2.137",
        ),
        ServiceObject(object_id="acme-widgets-as-a-service"),
        ServiceObject(object_id="vm-1054571726.region.example.com"),
        ServiceObject(object_id="2001:db8::d06:f00d"),
        ServiceObject(object_id="198.51.100.13"),
    ]
    notif = MaintenanceNotification.create(
        uid="all-7-objects@example.com",
        dtstart=datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 11, 1, 2, 0, tzinfo=timezone.utc),
        summary="Multi-object maintenance",
        organizer="noc@example.com",
        provider="example.com",
        account="137.035999173",
        maintenance_id="WorkOrder-31415",
        objects=objects,
        impact=Impact.DEGRADED,
        status=Status.CONFIRMED,
    )
    restored = parse(dumps(notif))
    assert restored.objects == tuple(objects)


def test_vtimezone_tzid_and_valarm_interoperability() -> None:
    """Ensures VTIMEZONE, TZID parameters, and VALARM subcomponents parse cleanly."""
    raw = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Carrier//Maintenance//EN\r
BEGIN:VTIMEZONE\r
TZID:America/New_York\r
BEGIN:STANDARD\r
DTSTART:20261101T020000\r
TZOFFSETFROM:-0400\r
TZOFFSETTO:-0500\r
END:STANDARD\r
END:VTIMEZONE\r
BEGIN:VEVENT\r
SUMMARY:NYC POP Maintenance\r
DTSTART;TZID=America/New_York:20261110T010000\r
DTEND;TZID=America/New_York:20261110T030000\r
DTSTAMP:20261101T120000Z\r
UID:nyc-tz-1\r
SEQUENCE:0\r
X-MAINTNOTE-PROVIDER:carrier.example\r
X-MAINTNOTE-ACCOUNT:ACC-NYC\r
X-MAINTNOTE-MAINTENANCE-ID:WO-NYC-1\r
X-MAINTNOTE-OBJECT-ID:nyc-core-01\r
X-MAINTNOTE-IMPACT:OUTAGE\r
X-MAINTNOTE-STATUS:CONFIRMED\r
ORGANIZER;CN="NYC NOC":mailto:noc@carrier.example\r
BEGIN:VALARM\r
ACTION:DISPLAY\r
TRIGGER:-PT30M\r
DESCRIPTION:Maintenance starts in 30 minutes\r
END:VALARM\r
END:VEVENT\r
END:VCALENDAR\r
"""
    notif = parse(raw)
    assert notif.dtstart.astimezone(timezone.utc) == datetime(
        2026, 11, 10, 6, 0, tzinfo=timezone.utc
    )
    assert notif.dtend.astimezone(timezone.utc) == datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)


def test_section_5_1_localization_end_to_end_email_and_sqlite(tmp_path: Path) -> None:
    """Tests UTF-8 localized notifications across iCal folding, email MIME, and SQLite."""
    provider = MaintenanceProvider(
        provider="jp.example.net",
        organizer=Organizer("noc@jp.example.net", cn="東京ネットワーク運用センター"),
    )
    notif = provider.create_initial(
        account="JP-001",
        maintenance_id="WO-東京-2026",
        objects=[ServiceObject(object_id="tyo1-core-sw01", language="ja")],
        dtstart=datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 11, 20, 17, 0, tzinfo=timezone.utc),
        summary="光ファイバー切替作業に伴うメンテナンス通知",
        description="予定作業時間中は冗長性が低下します。",
        impact=Impact.REDUCED_REDUNDANCY,
        language="ja",
    )

    msg = build_notification_email(notif, sender="noc@jp.example.net", recipient="ops@client.jp")
    extracted = extract_notifications_from_email(msg.as_bytes())
    assert len(extracted) == 1
    assert extracted[0].summary == "光ファイバー切替作業に伴うメンテナンス通知"
    assert extracted[0].summary_params == {"LANGUAGE": ("ja",)}

    store = SQLiteStateStore(tmp_path / "jp.db")
    try:
        consumer = MaintenanceConsumer(store=store)
        res = consumer.process(extracted[0])
        assert res.action is WorkflowAction.INITIAL
        all_records = store.list_all()
        assert len(all_records) == 1
        assert all_records[0].notification.summary == notif.summary
    finally:
        store.close()


def test_validate_reports_all_error_and_warning_conditions() -> None:
    base = MaintenanceNotification.create(
        uid="val-1",
        dtstart=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc),
        summary="Valid",
        organizer="noc@example.com",
        provider="example.com",
        account="ACC",
        maintenance_id="WO",
        objects=["OBJ"],
        impact=Impact.NO_IMPACT,
        status=StatusValue("X-CUSTOM-STATUS"),
    )

    # Non-standard status warning
    issues = validate(base)
    assert any(i.code == "NONSTANDARD_STATUS" and i.severity == "warning" for i in issues)

    # Error branches via broken model
    broken = MaintenanceNotification(
        uid="  ",
        sequence=-1,
        dtstamp=datetime(2026, 1, 1, 0, 0),  # noqa: DTZ001
        dtstart=datetime(2026, 1, 1, 1, 0),  # noqa: DTZ001
        dtend=datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc),  # aware -> mismatch
        summary="",
        organizer=Organizer("noc@example.com"),
        provider="",
        account="",
        maintenance_id="",
        objects=(),
        impact=ImpactValue("X-UNKNOWN"),
        version="1.0",
        prodid="",
        extra_calendar_properties=(ContentLine("VERSION", "2.0"),),
        extra_event_properties=(ContentLine("UID", "dup"),),
    )
    codes = {i.code for i in validate(broken)}
    assert {
        "INVALID_VERSION",
        "MISSING_PRODID",
        "MISSING_UID",
        "INVALID_SEQUENCE",
        "MISSING_SUMMARY",
        "MISSING_PROVIDER",
        "MISSING_ACCOUNT",
        "MISSING_MAINTENANCE_ID",
        "MISSING_OBJECT_ID",
        "MISMATCHED_TIMEZONES",
        "FLOATING_TIMESTAMP",
        "NONSTANDARD_IMPACT",
        "CONFLICTING_CALENDAR_PROPERTY",
        "CONFLICTING_EVENT_PROPERTY",
    }.issubset(codes)

    with pytest.raises(ValidationError):
        dumps(broken)


def test_parser_structural_and_duplicate_property_errors() -> None:
    # Wrong root component
    with pytest.raises(ValidationError):
        parse("BEGIN:VEVENT\r\nUID:1\r\nEND:VEVENT\r\n")

    # Missing VEVENT
    with pytest.raises(ValidationError):
        parse("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//T//EN\r\nEND:VCALENDAR\r\n")

    # Wrong VERSION, duplicate UID, negative/non-int SEQUENCE, bad DTSTART, duplicate STATUS
    bad = """\
BEGIN:VCALENDAR\r
VERSION:1.0\r
PRODID:-//T//EN\r
BEGIN:VEVENT\r
SUMMARY:Bad\r
DTSTART:not-a-dt\r
DTEND:20260101T020000Z\r
DTSTAMP:20260101T000000Z\r
UID:1\r
UID:2\r
SEQUENCE:abc\r
X-MAINTNOTE-PROVIDER:example.com\r
X-MAINTNOTE-ACCOUNT:1\r
X-MAINTNOTE-MAINTENANCE-ID:M1\r
X-MAINTNOTE-OBJECT-ID:O1\r
X-MAINTNOTE-IMPACT:OUTAGE\r
X-MAINTNOTE-STATUS:CONFIRMED\r
X-MAINTNOTE-STATUS:CANCELLED\r
ORGANIZER:mailto:noc@example.com\r
END:VEVENT\r
END:VCALENDAR\r
"""
    with pytest.raises(ValidationError):
        parse(bad)

    # Duplicate METHOD and invalid VERSION on calendar
    dup_method = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//T//EN\r
METHOD:PUBLISH\r
METHOD:CANCEL\r
BEGIN:VEVENT\r
SUMMARY:Bad\r
DTSTART:20260101T010000Z\r
DTEND:20260101T020000Z\r
DTSTAMP:20260101T000000Z\r
UID:1\r
SEQUENCE:-5\r
X-MAINTNOTE-PROVIDER:example.com\r
X-MAINTNOTE-ACCOUNT:1\r
X-MAINTNOTE-MAINTENANCE-ID:M1\r
X-MAINTNOTE-OBJECT-ID:O1\r
X-MAINTNOTE-IMPACT:OUTAGE\r
ORGANIZER:mailto:noc@example.com\r
END:VEVENT\r
END:VCALENDAR\r
"""
    with pytest.raises(ValidationError):
        parse(dup_method)

    # Whitespace around impact produces warning
    ws_impact = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//T//EN\r
BEGIN:VEVENT\r
SUMMARY:WS\r
DTSTART:20260101T010000Z\r
DTEND:20260101T020000Z\r
DTSTAMP:20260101T000000Z\r
UID:ws-1\r
SEQUENCE:0\r
X-MAINTNOTE-PROVIDER:example.com\r
X-MAINTNOTE-ACCOUNT:1\r
X-MAINTNOTE-MAINTENANCE-ID:M1\r
X-MAINTNOTE-OBJECT-ID:O1\r
X-MAINTNOTE-IMPACT: OUTAGE \r
ORGANIZER:mailto:noc@example.com\r
END:VEVENT\r
END:VCALENDAR\r
"""
    diag = parse_with_diagnostics(ws_impact)
    assert diag.notification.effective_impact is Impact.OUTAGE
    assert any(w.code == "WHITESPACE_VALUE" for w in diag.warnings)


def test_out_of_order_first_seen_states_and_diff_all_fields() -> None:
    handler = InMemoryTicketHandler()
    store = InMemoryStateStore()
    consumer = MaintenanceConsumer(store=store, handler=handler)
    provider = MaintenanceProvider(provider="p.example", organizer="noc@p.example")

    for idx, status_val, expected_state in [
        (1, Status.CANCELLED, "CANCELLED"),
        (2, Status.IN_PROCESS, "OPEN"),
        (3, Status.COMPLETED, "CLOSED"),
    ]:
        notif = provider.create_initial(
            account="A",
            maintenance_id=f"M-{idx}",
            objects=[f"O-{idx}"],
            dtstart=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            dtend=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
            summary="Direct",
            impact=Impact.NO_IMPACT,
            status=status_val,
            initial_sequence=2,
        )
        res = consumer.process(notif)
        assert res.ticket_id is not None
        assert handler.tickets[res.ticket_id].state == expected_state

    assert len(store.list_by_scoped_object("p.example", "O-1")) == 1
    assert len(store.list_all()) == 3

    # Full field diff check
    n1 = provider.create_initial(
        account="A",
        maintenance_id="M-diff",
        objects=["O-1"],
        dtstart=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
        summary="Original",
        description="Old desc",
        impact=Impact.NO_IMPACT,
        status=Status.TENTATIVE,
    )
    n2 = provider.update_window(
        n1,
        dtstart=datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 1, 2, 2, 0, tzinfo=timezone.utc),
        summary="Updated",
        description="New desc",
        impact=Impact.OUTAGE,
        status=Status.CONFIRMED,
        objects=["O-1", "O-2"],
    )
    diff = compute_diff(n1, n2)
    assert diff.has_changes
    assert set(diff.changed_fields) == {
        "window",
        "status",
        "impact",
        "objects",
        "summary",
        "description",
    }


def test_email_pgp_edge_cases() -> None:
    # Malformed multipart/signed with only 1 part
    bad_signed = MIMEMultipart("signed", protocol="application/pgp-signature")
    bad_signed.attach(MIMEText("only one part"))
    with pytest.raises(ParseError, match="exactly 2"):
        extract_pgp_signed_parts(bad_signed)

    # Wrong second MIME type
    bad_sig_type = MIMEMultipart("signed", protocol="application/pgp-signature")
    bad_sig_type.attach(MIMEText("body"))
    bad_sig_type.attach(MIMEText("not a pgp signature"))
    with pytest.raises(ParseError, match="application/pgp-signature"):
        extract_pgp_signed_parts(bad_sig_type)

    # require_pgp_signature without verifier
    with pytest.raises(VerificationError, match="requires a pgp_verifier"):
        extract_notifications_from_email("From: a@b\n\nHi", require_pgp_signature=True)


def test_transport_error_paths_and_bearer_auth() -> None:
    class _FailingOpener(urllib.request.OpenerDirector):
        def open(self, fullurl: Any, data: Any = None, timeout: Any = None) -> Any:
            raise urllib.error.URLError("connection refused")

    class _StaticResponse:
        def __init__(self, body: bytes, content_type: str = "text/plain") -> None:
            self._io = io.BytesIO(body)
            self.headers = {"Content-Type": content_type}

        def read(self, n: int = -1) -> bytes:
            return self._io.read(n)

        def __enter__(self) -> _StaticResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class _StaticOpener(urllib.request.OpenerDirector):
        def __init__(self, body: bytes, content_type: str = "text/plain") -> None:
            super().__init__()
            self._body = body
            self._ct = content_type
            self.last_request: urllib.request.Request | None = None

        def open(self, fullurl: Any, data: Any = None, timeout: Any = None) -> Any:
            self.last_request = fullurl
            return _StaticResponse(self._body, self._ct)

    obj = ServiceObject(object_id="1", altrep="https://example.org/data")
    with pytest.raises(TransportError, match="Failed to retrieve"):
        fetch_altrep_metadata(obj, opener=_FailingOpener())

    with pytest.raises(TransportError, match="invalid JSON"):
        fetch_altrep_metadata(obj, opener=_StaticOpener(b"{bad json", "application/json"))

    # Opportunistic JSON decoding when server returns text/plain
    res = fetch_altrep_metadata(obj, opener=_StaticOpener(b'{"ok": true}', "text/plain"))
    assert res.data == {"ok": True}

    # Plain non-JSON text returns data=None
    res_plain = fetch_altrep_metadata(obj, opener=_StaticOpener(b"plain text", "text/plain"))
    assert res_plain.data is None

    # CalDAV unsupported scheme & error paths
    with pytest.raises(TransportError, match="Unsupported CalDAV URL scheme"):
        CalDAVClient("ftp://cal.example.com/maint", require_tls=False)

    bearer_opener = _StaticOpener(b"<not-xml")
    client = CalDAVClient(
        "https://cal.example.com/maint", bearer_token="tok-123", opener=bearer_opener
    )
    with pytest.raises(TransportError, match="Invalid CalDAV XML"):
        client.fetch_notifications()
    assert bearer_opener.last_request is not None
    assert bearer_opener.last_request.headers["Authorization"] == "Bearer tok-123"

    failing_client = CalDAVClient("https://cal.example.com/maint", opener=_FailingOpener())
    with pytest.raises(TransportError, match="REPORT failed"):
        failing_client.fetch_notifications()
    with pytest.raises(TransportError, match="DELETE failed"):
        failing_client.delete_notification("x.ics")


def test_cli_human_readable_modes_and_update_confirm_cancel(
    tmp_path: Path, example_4_1: str, capsys: pytest.CaptureFixture[str]
) -> None:
    ics_path = tmp_path / "ex.ics"
    ics_path.write_text(example_4_1, encoding="utf-8")

    assert main(["validate", str(ics_path)]) == 0
    assert "VALID" in capsys.readouterr().out

    assert main(["parse", str(ics_path)]) == 0
    out = capsys.readouterr().out
    assert "Provider:       example.com" in out

    # Missing required args for initial
    assert main(["generate", "--action", "initial"]) == 1
    assert "Missing required arguments" in capsys.readouterr().err

    # Update, confirm, cancel transitions
    upd_path = tmp_path / "upd.ics"
    assert (
        main(
            [
                "generate",
                "--action",
                "update",
                "--from-file",
                str(ics_path),
                "--dtstart",
                "2026-10-12T08:00:00Z",
                "--dtend",
                "2026-10-12T10:00:00Z",
                "-o",
                str(upd_path),
            ]
        )
        == 0
    )
    assert parse(upd_path.read_text(encoding="utf-8")).sequence == 2

    conf_path = tmp_path / "conf.ics"
    assert (
        main(
            ["generate", "--action", "confirm", "--from-file", str(upd_path), "-o", str(conf_path)]
        )
        == 0
    )
    assert parse(conf_path.read_text(encoding="utf-8")).is_confirmed

    canc_path = tmp_path / "canc.ics"
    assert (
        main(
            ["generate", "--action", "cancel", "--from-file", str(conf_path), "-o", str(canc_path)]
        )
        == 0
    )
    assert parse(canc_path.read_text(encoding="utf-8")).is_cancelled

    # Human-readable extract-email
    eml = build_notification_email(
        parse(example_4_1),
        sender="noc@example.com",
        recipient="ops@customer.example",
    )
    eml_path = tmp_path / "mail.eml"
    eml_path.write_bytes(eml.as_bytes())
    assert main(["extract-email", str(eml_path)]) == 0
    assert "Found 1 maintenance notification(s)" in capsys.readouterr().out
