"""Example: Localization (Section 5.1), timezones, and lenient legacy-feed parsing.

Demonstrates:
- Custom LocalizationStrings (German prefixes & email labels) + LANGUAGE parameters
- Multi-byte UTF-8 safe 75-octet RFC 5545 line folding across email & iCalendar round-trips
- Parsing VTIMEZONE/TZID, VALARM, extra X-* properties, and draft Table 2 X-MAINTENOTE-* typos
  using parse_with_diagnostics(strict=False) while preserving unknown data on round-trip
"""

from __future__ import annotations

from datetime import datetime, timezone

from maintnote import (
    Impact,
    LocalizationStrings,
    MaintenanceProvider,
    Organizer,
    ServiceObject,
    build_notification_email,
    dumps,
    extract_notifications_from_email,
    parse_with_diagnostics,
)

LEGACY_FEED = """\
BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Legacy Carrier//Maint//EN\r
BEGIN:VTIMEZONE\r
TZID:America/New_York\r
BEGIN:STANDARD\r
DTSTART:20261101T020000\r
TZOFFSETFROM:-0400\r
TZOFFSETTO:-0500\r
END:STANDARD\r
END:VTIMEZONE\r
BEGIN:VEVENT\r
UID:legacy-quirk-01@carrier.example\r
SEQUENCE:0\r
DTSTAMP:20261101T120000Z\r
DTSTART;TZID=America/New_York:20261110T010000\r
DTEND;TZID=America/New_York:20261110T030000\r
SUMMARY:NYC optical chassis maintenance\r
ORGANIZER;CN="Legacy NOC":mailto:noc@carrier.example\r
X-MAINTNOTE-PROVIDER:carrier.example\r
X-MAINTENOTE-ACCOUNT:ACC-TYPO-01\r
X-MAINTNOTE-MAINTENANCE-ID:WO-LEGACY-9\r
X-MAINTNOTE-OBJECT-ID:nyc-core-sw01\r
X-MAINTNOTE-IMPACT:X-LINK-FLAP\r
X-MAINTNOTE-STATUS:CONFIRMED\r
X-VENDOR-CHANGE-URL:https://status.carrier.example/changes/WO-LEGACY-9\r
BEGIN:VALARM\r
ACTION:DISPLAY\r
TRIGGER:-PT30M\r
DESCRIPTION:Maintenance starts in 30 minutes\r
END:VALARM\r
END:VEVENT\r
END:VCALENDAR\r
"""


def main() -> None:
    print("=== 1. Localized German notification with UTF-8 folding & email round-trip ===")
    german_loc = LocalizationStrings(
        open_prefix="Offen - ",
        closed_prefix="Abgeschlossen - ",
        email_title="Wartungsankündigung",
        email_provider="Anbieter",
        email_account="Konto",
        email_maintenance_id="Wartungs-ID",
        email_window="Zeitfenster",
        email_window_separator="bis",
        email_impact="Auswirkung",
        email_status="Status",
        email_objects="Betroffene Objekte",
    )
    provider = MaintenanceProvider(
        provider="netz.example.de",
        organizer=Organizer("noc@netz.example.de", cn="Netzbetrieb München"),
        localization=german_loc,
    )
    initial = provider.create_initial(
        account="DE-4711",
        maintenance_id="WO-MUC-2026-08",
        objects=[ServiceObject(object_id="muc1-glasfaser-ring-01", language="de")],
        dtstart=datetime(2026, 11, 25, 1, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 11, 25, 3, 30, tzinfo=timezone.utc),
        summary="Glasfaser-Spleißarbeiten am Kernknoten München-Süd (Redundanzprüfung)",
        description="Während der Wartung ist mit erhöhter Latenz über Ersatzwege zu rechnen.",
        impact=Impact.REDUCED_REDUNDANCY,
        language="de",
    )
    opened = provider.open_window(initial)
    closed = provider.close_window(opened)

    eml = build_notification_email(
        closed,
        sender="noc@netz.example.de",
        recipient="betrieb@kunde.example.de",
        localization=german_loc,
    )
    extracted = extract_notifications_from_email(eml.as_bytes())[0]
    body_part = eml.get_body(preferencelist=("plain",))
    preview = body_part.get_content().splitlines()[0] if body_part is not None else ""
    print(f"  Summary:        {extracted.summary}")
    print(f"  Summary params: {extracted.summary_params}")
    print(f"  Email preview:  {preview}")

    print("\n=== 2. Lenient parsing of legacy feed with VTIMEZONE, VALARM & typo diagnostics ===")
    result = parse_with_diagnostics(LEGACY_FEED, strict=False)
    notif = result.notification
    print(f"  Parsed account:     {notif.account}")
    print(f"  UTC window:         {notif.dtstart.astimezone(timezone.utc).isoformat()} -> {notif.dtend.astimezone(timezone.utc).isoformat()}")
    print(f"  Impact / effective: {notif.impact.raw} -> {notif.effective_impact.value}")
    print(f"  Warnings ({len(result.warnings)}):")
    for warning in result.warnings:
        print(f"    - [{warning.code}] {warning.property_name}: {warning.message}")

    # Verify vendor extension properties and VALARM survive round-trip serialization
    reserialized = dumps(notif)
    has_vendor_prop = "X-VENDOR-CHANGE-URL:" in reserialized
    has_valarm = "BEGIN:VALARM" in reserialized
    print(f"  Round-trip preserved: X-VENDOR-CHANGE-URL={has_vendor_prop} VALARM={has_valarm}")


if __name__ == "__main__":
    main()
