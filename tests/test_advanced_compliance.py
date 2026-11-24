"""Tests for advanced RFC 5545/5546/3156/4791 compliance, batch workflows, localization, and hardening."""

from __future__ import annotations

import hashlib
import hmac
import io
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from maintnote import (
    CalDAVClient,
    Impact,
    InMemoryStateStore,
    InMemoryTicketHandler,
    LocalizationStrings,
    MaintenanceConsumer,
    MaintenanceProvider,
    ServiceObject,
    SQLiteStateStore,
    Status,
    TransportError,
    ValidationError,
    WorkflowAction,
    WorkflowError,
    build_notification_email,
    dumps,
    extract_notifications_from_email,
    extract_pgp_signed_parts,
    fetch_altrep_metadata,
    parse,
    parse_with_diagnostics,
    sign_notification_email,
    strip_method_from_email,
    verify_email_signature,
)
from maintnote.cli import main
from maintnote.transport import _SafeRedirectHandler


def test_windows_vtimezone_fallback_and_subcomponent_roundtrip() -> None:
    raw = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Exchange//Maintenance//EN\r
BEGIN:VTIMEZONE\r
TZID:Eastern Standard Time\r
BEGIN:STANDARD\r
DTSTART:16011104T020000\r
TZOFFSETFROM:-0400\r
TZOFFSETTO:-0500\r
END:STANDARD\r
END:VTIMEZONE\r
BEGIN:VEVENT\r
SUMMARY:Windows TZID Maintenance\r
DTSTART;TZID="Eastern Standard Time":20261110T010000\r
DTEND;TZID="Eastern Standard Time":20261110T030000\r
DTSTAMP:20261101T120000Z\r
UID:win-tz-1\r
SEQUENCE:0\r
X-MAINTNOTE-PROVIDER:carrier.example\r
X-MAINTNOTE-ACCOUNT:ACC-1\r
X-MAINTNOTE-MAINTENANCE-ID:WO-WIN-1\r
X-MAINTNOTE-OBJECT-ID:ckt-1\r
X-MAINTNOTE-IMPACT:OUTAGE\r
X-MAINTNOTE-STATUS:CONFIRMED\r
ORGANIZER;CN="NOC":mailto:noc@carrier.example\r
BEGIN:VALARM\r
ACTION:DISPLAY\r
TRIGGER:-PT15M\r
DESCRIPTION:Starting soon\r
END:VALARM\r
END:VEVENT\r
END:VCALENDAR\r
"""
    notif = parse(raw)
    assert notif.dtstart.astimezone(timezone.utc) == datetime(
        2026, 11, 10, 6, 0, tzinfo=timezone.utc
    )
    assert notif.dtend.astimezone(timezone.utc) == datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)
    assert len(notif.extra_calendar_subcomponents) == 1
    assert notif.extra_calendar_subcomponents[0].name == "VTIMEZONE"
    assert len(notif.extra_event_subcomponents) == 1
    assert notif.extra_event_subcomponents[0].name == "VALARM"

    # Re-serialized iCalendar preserves VTIMEZONE and VALARM subcomponents
    redumped = dumps(notif)
    assert "BEGIN:VTIMEZONE" in redumped
    assert "BEGIN:VALARM" in redumped
    reparsed = parse(redumped)
    assert len(reparsed.extra_calendar_subcomponents) == 1
    assert len(reparsed.extra_event_subcomponents) == 1


def test_value_date_warning_and_non_utc_dtstamp_error() -> None:
    date_only = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Test//EN\r
BEGIN:VEVENT\r
SUMMARY:All-day maintenance window\r
DTSTART;VALUE=DATE:20261110\r
DTEND;VALUE=DATE:20261111\r
DTSTAMP:20261101T000000Z\r
UID:date-only-1\r
SEQUENCE:0\r
X-MAINTNOTE-PROVIDER:example.com\r
X-MAINTNOTE-ACCOUNT:1\r
X-MAINTNOTE-MAINTENANCE-ID:M1\r
X-MAINTNOTE-OBJECT-ID:O1\r
X-MAINTNOTE-IMPACT:NO-IMPACT\r
ORGANIZER:mailto:noc@example.com\r
END:VEVENT\r
END:VCALENDAR\r
"""
    res = parse_with_diagnostics(date_only)
    assert res.notification.dtstart == datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)
    assert any(w.code == "DATE_ONLY_TIMESTAMP" for w in res.warnings)

    non_utc_stamp = date_only.replace(
        "DTSTAMP:20261101T000000Z",
        "DTSTAMP;TZID=America/New_York:20261101T000000",
    )
    with pytest.raises(ValidationError) as exc:
        parse(non_utc_stamp)
    assert any(i.code == "NON_UTC_DTSTAMP" for i in exc.value.issues)


def test_itip_method_param_language_altrep_duplicate_and_status_conflict_checks() -> None:
    # METHOD:REQUEST without ATTENDEE, LANGUAGE on IMPACT/STATUS, duplicate OBJECT-ID
    raw = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Test//EN\r
METHOD:REQUEST\r
BEGIN:VEVENT\r
SUMMARY:Checks\r
DTSTART:20261110T010000Z\r
DTEND:20261110T020000Z\r
DTSTAMP:20261101T000000Z\r
UID:check-1\r
SEQUENCE:0\r
X-MAINTNOTE-PROVIDER:example.com\r
X-MAINTNOTE-ACCOUNT:1\r
X-MAINTNOTE-MAINTENANCE-ID:M1\r
X-MAINTNOTE-OBJECT-ID:dup-obj\r
X-MAINTNOTE-OBJECT-ID:dup-obj\r
X-MAINTNOTE-IMPACT;LANGUAGE=en:OUTAGE\r
X-MAINTNOTE-STATUS;LANGUAGE=en:CONFIRMED\r
STATUS:CONFIRMED\r
ORGANIZER:mailto:noc@example.com\r
END:VEVENT\r
END:VCALENDAR\r
"""
    diag = parse_with_diagnostics(raw)
    warning_codes = {w.code for w in diag.warnings}
    assert "MISSING_METHOD_PROPERTY" in warning_codes
    assert "DISALLOWED_LANGUAGE_PARAM" in warning_codes
    assert "DUPLICATE_OBJECT_ID" in warning_codes

    # Conflicting RFC 5545 STATUS:CANCELLED vs X-MAINTNOTE-STATUS:CONFIRMED -> error
    conflicting = raw.replace("STATUS:CONFIRMED", "STATUS:CANCELLED")
    with pytest.raises(ValidationError) as exc:
        parse(conflicting)
    assert any(i.code == "CONFLICTING_ICAL_STATUS" for i in exc.value.issues)

    # Unrecognized METHOD warning
    weird_method = raw.replace("METHOD:REQUEST", "METHOD:X-CUSTOM-VERB")
    diag_weird = parse_with_diagnostics(weird_method)
    assert any(w.code == "UNRECOGNIZED_METHOD" for w in diag_weird.warnings)

    # Invalid ALTREP URI -> error
    bad_altrep = raw.replace(
        "X-MAINTNOTE-OBJECT-ID:dup-obj\r\n", 'X-MAINTNOTE-OBJECT-ID;ALTREP="not-a-uri":obj-1\r\n', 1
    )
    with pytest.raises(ValidationError) as exc_uri:
        parse(bad_altrep)
    assert any(i.code == "INVALID_ALTREP_URI" for i in exc_uri.value.issues)


def test_cross_provider_uid_42_isolation_in_memory_and_sqlite(tmp_path: Path) -> None:
    """Two independent providers both using UID:42 must never collide in consumer state."""
    for store in (InMemoryStateStore(), SQLiteStateStore(tmp_path / "multi_provider.db")):
        try:
            handler = InMemoryTicketHandler(prefix="INC")
            consumer = MaintenanceConsumer(store=store, handler=handler)

            prov_a = MaintenanceProvider(provider="isp-a.example", organizer="noc@isp-a.example")
            prov_b = MaintenanceProvider(provider="isp-b.example", organizer="noc@isp-b.example")

            na0 = prov_a.create_initial(
                uid="42",
                account="A1",
                maintenance_id="WO-A",
                objects=["ckt-1"],
                dtstart=datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc),
                dtend=datetime(2026, 11, 1, 2, 0, tzinfo=timezone.utc),
                summary="ISP-A maintenance",
                impact=Impact.OUTAGE,
            )
            nb0 = prov_b.create_initial(
                uid="42",
                account="B1",
                maintenance_id="WO-B",
                objects=["ckt-1"],
                dtstart=datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc),
                dtend=datetime(2026, 11, 2, 2, 0, tzinfo=timezone.utc),
                summary="ISP-B maintenance",
                impact=Impact.NO_IMPACT,
            )

            ra = consumer.process(na0)
            rb = consumer.process(nb0)
            assert ra.action is WorkflowAction.INITIAL
            assert rb.action is WorkflowAction.INITIAL
            assert ra.ticket_id != rb.ticket_id
            assert len(store.list_all()) == 2

            rec_a = store.get("42", provider="isp-a.example")
            rec_b = store.get("42", provider="isp-b.example")
            assert rec_a is not None
            assert rec_b is not None
            assert rec_a.maintenance_id == "WO-A"
            assert rec_b.maintenance_id == "WO-B"
        finally:
            if isinstance(store, SQLiteStateStore):
                store.close()


def test_provider_batch_lifecycle_and_consumer_noop_update_and_localization() -> None:
    fr_loc = LocalizationStrings(
        open_prefix="Ouvert - ",
        closed_prefix="Fermé - ",
        email_title="Notification de maintenance",
        email_provider="Fournisseur",
        email_account="Compte",
        email_maintenance_id="ID de maintenance",
        email_window="Fenêtre",
        email_window_separator="à",
        email_impact="Impact",
        email_status="Statut",
        email_objects="Objets",
    )
    provider = MaintenanceProvider(
        provider="fr.example.net",
        organizer="noc@fr.example.net",
        localization=fr_loc,
    )

    with pytest.raises(WorkflowError, match="Unknown maintenance_id"):
        provider.get_batch("NON-EXISTENT")

    provider.create_batch_initial(
        maintenance_id="CHG-FR-1",
        affected_accounts={"ACC-1": ["obj-a"], "ACC-2": ["obj-b"]},
        dtstart=datetime(2026, 12, 1, 2, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 12, 1, 4, 0, tzinfo=timezone.utc),
        summary="Mise à jour routeur",
        impact=Impact.DEGRADED,
        language="fr",
    )
    confirmed = provider.confirm_batch("CHG-FR-1")
    assert all(n.sequence == 1 and n.is_confirmed for n in confirmed.values())

    opened = provider.open_batch("CHG-FR-1", description="Travaux en cours")
    assert all(n.summary == "Ouvert - Mise à jour routeur" for n in opened.values())

    closed = provider.close_batch("CHG-FR-1", description="Travaux terminés")
    assert all(n.summary == "Fermé - Mise à jour routeur" for n in closed.values())

    # Also test cancel_batch
    provider.create_batch_initial(
        maintenance_id="CHG-FR-2",
        affected_accounts={"ACC-1": ["obj-a"]},
        dtstart=datetime(2026, 12, 5, 2, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 12, 5, 4, 0, tzinfo=timezone.utc),
        summary="Maintenance annulée",
        impact=Impact.NO_IMPACT,
    )
    cancelled = provider.cancel_batch("CHG-FR-2")
    assert cancelled["ACC-1"].is_cancelled

    # Localized email body check
    eml = build_notification_email(
        closed["ACC-1"],
        sender="noc@fr.example.net",
        recipient="ops@client.fr",
        localization=fr_loc,
    )
    body_part = eml.get_body(preferencelist=("plain",))
    assert body_part is not None
    body_text = body_part.get_content()
    assert "Notification de maintenance:" in body_text
    assert "Fournisseur: fr.example.net" in body_text

    # Consumer Section 3.2.2 NO_OP_UPDATE check
    handler = InMemoryTicketHandler()
    consumer = MaintenanceConsumer(handler=handler, skip_noop_ticket_updates=True)
    n0 = confirmed["ACC-1"]
    r0 = consumer.process(n0)
    assert r0.ticket_id is not None
    history_before = list(handler.tickets[r0.ticket_id].history)

    # Bump only SEQUENCE & DTSTAMP without changing window/status/impact/objects/summary/description
    n_noop = n0.with_updates(
        sequence=n0.sequence + 1, dtstamp=datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc)
    )
    r_noop = consumer.process(n_noop)
    assert r_noop.action is WorkflowAction.NO_OP_UPDATE
    assert handler.tickets[r0.ticket_id].history == history_before
    stored = consumer.store.get(n0.uid, provider=n0.provider)
    assert stored is not None
    assert stored.sequence == n_noop.sequence


def test_email_strip_method_and_rfc3156_raw_byte_sign_verify_roundtrip(tmp_path: Path) -> None:
    provider = MaintenanceProvider(provider="example.com", organizer="noc@example.com")
    notif = provider.create_initial(
        account="1",
        maintenance_id="M1",
        objects=["O1"],
        dtstart=datetime(2026, 12, 1, 2, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 12, 1, 4, 0, tzinfo=timezone.utc),
        summary="Signed & Method Test",
        impact=Impact.OUTAGE,
    )
    eml = build_notification_email(
        notif,
        sender="noc@example.com",
        recipient="ops@customer.example",
        include_method=True,
        method="REQUEST",
    )
    raw_with_method = eml.as_bytes()
    assert b"method=REQUEST" in raw_with_method or b'method="REQUEST"' in raw_with_method
    assert b"METHOD:REQUEST" in raw_with_method

    # Email-level sanitizer removes BOTH MIME method param and METHOD:REQUEST in .ics
    cleaned_msg = strip_method_from_email(raw_with_method)
    cleaned_bytes = cleaned_msg.as_bytes()
    assert b"METHOD:REQUEST" not in cleaned_bytes
    for part in cleaned_msg.walk():
        if part.get_content_type() == "text/calendar":
            assert part.get_param("method") is None
    assert extract_notifications_from_email(cleaned_bytes)[0].method is None

    # CLI strip-email-method test
    in_eml = tmp_path / "in.eml"
    out_eml = tmp_path / "out.eml"
    in_eml.write_bytes(raw_with_method)
    assert main(["strip-email-method", str(in_eml), "-o", str(out_eml)]) == 0
    assert b"METHOD:REQUEST" not in out_eml.read_bytes()

    # Exact byte-level RFC 3156 signing & raw-boundary verification using HMAC-SHA256 as mock signer
    secret_key = b"test-pgp-signing-key"

    class ByteExactSignerVerifier:
        def sign(self, payload: bytes) -> bytes:
            digest = hmac.new(secret_key, payload, hashlib.sha256).hexdigest()
            return (
                f"-----BEGIN PGP SIGNATURE-----\r\n{digest}\r\n-----END PGP SIGNATURE-----\r\n"
            ).encode()

        def verify(self, signed_payload: bytes, detached_signature: bytes) -> bool:
            expected = self.sign(signed_payload).strip()
            return hmac.compare_digest(expected, detached_signature.strip())

    sv = ByteExactSignerVerifier()
    signed_msg = sign_notification_email(cleaned_msg, sv, micalg="pgp-sha256")
    wire_bytes = signed_msg.as_bytes()

    parts = extract_pgp_signed_parts(wire_bytes)
    assert parts is not None
    assert parts.micalg == "pgp-sha256"
    assert verify_email_signature(wire_bytes, sv) is True

    # Tampering a single byte in the signed body invalidates raw-byte signature!
    tampered = wire_bytes.replace(b"Signed & Method Test", b"Tampered Method Test")
    with pytest.raises(Exception, match="verification failed"):
        verify_email_signature(tampered, sv)


def test_altrep_hardening_and_caldav_discovery_propfilter_etag() -> None:
    # Private/loopback IP SSRF protection
    for bad_uri in (
        "https://127.0.0.1/secret",
        "https://10.0.0.1/internal",
        "https://169.254.169.254/latest/meta-data/",
        "https://localhost/admin",
    ):
        with pytest.raises(TransportError, match="Blocked"):
            fetch_altrep_metadata(ServiceObject(object_id="1", altrep=bad_uri))

    # Redirect downgrade protection (https -> http)
    handler = _SafeRedirectHandler(allowed_schemes=("https",), block_private_ips=True)
    req = urllib.request.Request("https://example.org/start")
    with pytest.raises(TransportError, match="allowed schemes"):
        handler.redirect_request(req, None, 302, "Found", {}, "http://example.org/downgraded")

    # Max response size enforcement
    class _BigResp:
        def __init__(self) -> None:
            self.headers = {"Content-Type": "application/json"}

        def read(self, n: int = -1) -> bytes:
            return b"x" * (n if n > 0 else 1024)

        def __enter__(self) -> _BigResp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class _BigOpener(urllib.request.OpenerDirector):
        def open(self, fullurl: Any, data: Any = None, timeout: Any = None) -> Any:
            return _BigResp()

    with pytest.raises(TransportError, match="max_bytes"):
        fetch_altrep_metadata(
            ServiceObject(object_id="1", altrep="https://example.org/huge.json"),
            max_bytes=16,
            opener=_BigOpener(),
        )

    # CalDAV PROPFIND, prop-filter REPORT with ETag, GET, and If-Match / If-None-Match
    prov = MaintenanceProvider(provider="example.com", organizer="noc@example.com")
    notif = prov.create_initial(
        uid="cdav-1",
        account="1",
        maintenance_id="WO-42",
        objects=["ckt-1"],
        dtstart=datetime(2026, 12, 1, 2, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 12, 1, 4, 0, tzinfo=timezone.utc),
        summary="CalDAV Advanced",
        impact=Impact.OUTAGE,
        status=Status.CONFIRMED,
    )
    ical_str = dumps(notif)

    propfind_resp = b"""<?xml version="1.0" encoding="utf-8"?>
    <D:multistatus xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/">
      <D:response>
        <D:propstat>
          <D:prop>
            <D:displayname>Network Maintenances</D:displayname>
            <CS:getctag>ctag-99</CS:getctag>
          </D:prop>
        </D:propstat>
      </D:response>
    </D:multistatus>"""

    report_resp = f"""<?xml version="1.0" encoding="utf-8"?>
    <D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
      <D:response>
        <D:href>/cal/cdav-1.ics</D:href>
        <D:propstat>
          <D:prop>
            <D:getetag>"etag-1"</D:getetag>
            <C:calendar-data>{ical_str}</C:calendar-data>
          </D:prop>
        </D:propstat>
      </D:response>
    </D:multistatus>""".encode()

    class _SeqResp:
        def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
            self._io = io.BytesIO(body)
            self.headers = headers or {}

        def read(self, n: int = -1) -> bytes:
            return self._io.read(n)

        def __enter__(self) -> _SeqResp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class _SeqOpener(urllib.request.OpenerDirector):
        def __init__(self, responses: list[_SeqResp]) -> None:
            super().__init__()
            self._responses = list(responses)
            self.requests: list[urllib.request.Request] = []

        def open(self, fullurl: Any, data: Any = None, timeout: Any = None) -> Any:
            self.requests.append(fullurl)
            return self._responses.pop(0)

    opener = _SeqOpener(
        [
            _SeqResp(propfind_resp),
            _SeqResp(report_resp),
            _SeqResp(ical_str.encode("utf-8"), headers={"ETag": '"etag-1"'}),
            _SeqResp(b""),
            _SeqResp(b""),
        ]
    )
    client = CalDAVClient("https://cal.example.com/cal/", opener=opener)

    info = client.discover_collection()
    assert info.display_name == "Network Maintenances"
    assert info.ctag == "ctag-99"
    assert opener.requests[0].get_method() == "PROPFIND"

    events = client.fetch_events(
        provider="example.com",
        maintenance_id="WO-42",
        status=Status.CONFIRMED,
    )
    assert len(events) == 1
    assert events[0].href == "/cal/cdav-1.ics"
    assert events[0].etag == '"etag-1"'
    report_body = opener.requests[1].data
    assert isinstance(report_body, bytes)
    assert b'prop-filter name="X-MAINTNOTE-PROVIDER"' in report_body
    assert b'prop-filter name="X-MAINTNOTE-MAINTENANCE-ID"' in report_body
    assert b'prop-filter name="X-MAINTNOTE-STATUS"' in report_body

    single = client.get_notification("cdav-1.ics")
    assert single.etag == '"etag-1"'
    assert single.notifications[0].uid == "cdav-1"

    client.publish_notification(notif, if_match='"etag-1"', if_none_match="*")
    assert opener.requests[3].headers["If-match"] == '"etag-1"'
    assert opener.requests[3].headers["If-none-match"] == "*"

    client.delete_notification("cdav-1.ics", if_match='"etag-1"')
    assert opener.requests[4].headers["If-match"] == '"etag-1"'
