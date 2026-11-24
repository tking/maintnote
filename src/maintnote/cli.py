"""Command-line interface for validating, parsing, and generating maintenance notifications."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from maintnote.email_utils import extract_notifications_from_email, strip_method_from_ical
from maintnote.exceptions import MaintNoteError
from maintnote.models import Organizer, ServiceObject, Status
from maintnote.parser import parse, parse_with_diagnostics
from maintnote.serializer import dumps
from maintnote.workflow import MaintenanceProvider


def build_parser() -> argparse.ArgumentParser:
    """Construct the ``maintnote`` CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="maintnote",
        description=(
            "CLI for IETF draft-gunter-calext-maintenance-notifications-00 "
            "iCalendar maintenance notifications."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # validate
    val_p = sub.add_parser("validate", help="Validate an iCalendar maintenance notification file")
    val_p.add_argument("path", type=Path, help="Path to .ics file (use '-' for stdin)")
    val_p.add_argument("--lenient", action="store_true", help="Enable lenient parsing mode")
    val_p.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON report")

    # parse
    parse_p = sub.add_parser(
        "parse", help="Parse and inspect an iCalendar maintenance notification"
    )
    parse_p.add_argument("path", type=Path, help="Path to .ics file (use '-' for stdin)")
    parse_p.add_argument("--lenient", action="store_true", help="Enable lenient parsing mode")
    parse_p.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output")

    # generate
    gen_p = sub.add_parser("generate", help="Generate or transition a maintenance notification")
    gen_p.add_argument(
        "--action",
        choices=("initial", "update", "confirm", "cancel", "open", "close"),
        default="initial",
        help="Lifecycle workflow action (default: initial)",
    )
    gen_p.add_argument(
        "--from-file", type=Path, help="Previous .ics file for update/cancel/open/close"
    )
    gen_p.add_argument("--provider", help="X-MAINTNOTE-PROVIDER (required for initial)")
    gen_p.add_argument("--account", help="X-MAINTNOTE-ACCOUNT (required for initial)")
    gen_p.add_argument("--maintenance-id", help="X-MAINTNOTE-MAINTENANCE-ID (required for initial)")
    gen_p.add_argument(
        "--object-id",
        action="append",
        dest="object_ids",
        help="X-MAINTNOTE-OBJECT-ID (repeatable; optionally append '|https://altrep-uri')",
    )
    gen_p.add_argument(
        "--impact",
        help="X-MAINTNOTE-IMPACT (NO-IMPACT, REDUCED-REDUNDANCY, DEGRADED, OUTAGE, or x-name)",
    )
    gen_p.add_argument("--status", help="X-MAINTNOTE-STATUS")
    gen_p.add_argument("--summary", help="Event SUMMARY")
    gen_p.add_argument("--description", help="Optional event DESCRIPTION")
    gen_p.add_argument("--organizer", help="ORGANIZER email or mailto: URI")
    gen_p.add_argument("--organizer-cn", help="Optional ORGANIZER CN parameter")
    gen_p.add_argument(
        "--dtstart", help="Start time in ISO-8601 format (e.g. 2026-01-15T02:00:00Z)"
    )
    gen_p.add_argument("--dtend", help="End time in ISO-8601 format (e.g. 2026-01-15T04:00:00Z)")
    gen_p.add_argument("--uid", help="Explicit UID (auto-generated if omitted on initial)")
    gen_p.add_argument(
        "--include-method", action="store_true", help="Include METHOD property (omitted by default)"
    )
    gen_p.add_argument("--method", help="Explicit METHOD value (e.g. PUBLISH, REQUEST, CANCEL)")
    gen_p.add_argument("-o", "--output", type=Path, help="Output file path (defaults to stdout)")

    # strip-method
    strip_p = sub.add_parser(
        "strip-method",
        help="Remove METHOD property from an .ics file for safe human calendar delivery (Section 2.3.1)",
    )
    strip_p.add_argument("path", type=Path, help="Path to .ics file (use '-' for stdin)")

    # extract-email
    email_p = sub.add_parser(
        "extract-email",
        help="Extract maintenance notifications from an RFC 5322 .eml email file",
    )
    email_p.add_argument("path", type=Path, help="Path to .eml file (use '-' for stdin)")
    email_p.add_argument("--lenient", action="store_true", help="Enable lenient parsing mode")
    email_p.add_argument("--strip-method", action="store_true", help="Strip METHOD before parsing")
    email_p.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``maintnote`` CLI."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        if args.command == "validate":
            return _cmd_validate(args)
        if args.command == "parse":
            return _cmd_parse(args)
        if args.command == "generate":
            return _cmd_generate(args)
        if args.command == "strip-method":
            return _cmd_strip_method(args)
        if args.command == "extract-email":
            return _cmd_extract_email(args)
    except MaintNoteError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _read_text(path: Path) -> str:
    if str(path) == "-":
        return sys.stdin.read()
    return path.read_text(encoding="utf-8")


def _read_bytes(path: Path) -> bytes:
    if str(path) == "-":
        return sys.stdin.buffer.read()
    return path.read_bytes()


def _parse_iso_dt(raw: str) -> datetime:
    normalized = raw.strip()
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_object_arg(raw: str) -> ServiceObject:
    if "|" in raw:
        obj_id, altrep = raw.split("|", 1)
        return ServiceObject(object_id=obj_id, altrep=altrep)
    return ServiceObject(object_id=raw)


def _cmd_validate(args: argparse.Namespace) -> int:
    raw = _read_text(args.path)
    result = parse_with_diagnostics(raw, strict=not args.lenient)
    if args.as_json:
        payload = {
            "valid": True,
            "events": len(result.document.notifications),
            "warnings": [
                {
                    "code": w.code,
                    "property": w.property_name,
                    "message": w.message,
                }
                for w in result.warnings
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(f"VALID ({len(result.document.notifications)} VEVENT(s))")
        for warning in result.warnings:
            print(f"  {warning}")
    return 0


def _cmd_parse(args: argparse.Namespace) -> int:
    raw = _read_text(args.path)
    result = parse_with_diagnostics(raw, strict=not args.lenient)
    if args.as_json:
        items = [n.to_dict() for n in result.document.notifications]
        print(json.dumps(items[0] if len(items) == 1 else items, indent=2))
    else:
        for idx, notif in enumerate(result.document.notifications, start=1):
            if idx > 1:
                print("---")
            print(f"UID:            {notif.uid}")
            print(f"Sequence:       {notif.sequence}")
            print(f"Provider:       {notif.provider}")
            print(f"Account:        {notif.account}")
            print(f"Maintenance ID: {notif.maintenance_id}")
            print(f"Summary:        {notif.summary}")
            print(f"Window:         {notif.dtstart.isoformat()} -> {notif.dtend.isoformat()}")
            print(f"Impact:         {notif.impact.raw} (effective: {notif.effective_impact.value})")
            print(f"Status:         {notif.status.raw if notif.status else '(unspecified)'}")
            print(f"Objects:        {', '.join(notif.object_ids)}")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    if args.action == "initial":
        required = (
            "provider",
            "account",
            "maintenance_id",
            "object_ids",
            "impact",
            "summary",
            "organizer",
            "dtstart",
            "dtend",
        )
        missing = [field for field in required if not getattr(args, field)]
        if missing:
            raise MaintNoteError(
                f"Missing required arguments for initial notification: {', '.join(missing)}"
            )
        provider = MaintenanceProvider(
            provider=args.provider,
            organizer=Organizer(address=args.organizer, cn=args.organizer_cn),
        )
        notif = provider.create_initial(
            account=args.account,
            maintenance_id=args.maintenance_id,
            objects=[_parse_object_arg(item) for item in args.object_ids],
            dtstart=_parse_iso_dt(args.dtstart),
            dtend=_parse_iso_dt(args.dtend),
            summary=args.summary,
            impact=args.impact,
            status=args.status if args.status else Status.TENTATIVE,
            uid=args.uid,
            description=args.description,
        )
    else:
        if not args.from_file:
            raise MaintNoteError(f"--from-file is required for --action {args.action}")
        prev = parse(_read_text(args.from_file), strict=False)
        provider = MaintenanceProvider(
            provider=prev.provider, organizer=prev.organizer, prodid=prev.prodid
        )
        dtstart = _parse_iso_dt(args.dtstart) if args.dtstart else None
        dtend = _parse_iso_dt(args.dtend) if args.dtend else None
        objects = [_parse_object_arg(item) for item in args.object_ids] if args.object_ids else None

        if args.action == "update":
            notif = provider.update_window(
                prev,
                dtstart=dtstart,
                dtend=dtend,
                summary=args.summary,
                description=args.description,
                impact=args.impact,
                status=args.status,
                objects=objects,
            )
        elif args.action == "confirm":
            notif = provider.confirm(
                prev,
                dtstart=dtstart,
                dtend=dtend,
                summary=args.summary,
                description=args.description,
            )
        elif args.action == "cancel":
            notif = provider.cancel(prev, summary=args.summary, description=args.description)
        elif args.action == "open":
            notif = provider.open_window(prev, summary=args.summary, description=args.description)
        else:
            notif = provider.close_window(prev, summary=args.summary, description=args.description)

    rendered = dumps(
        notif,
        include_method=bool(args.include_method or args.method),
        method=args.method,
    )
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


def _cmd_strip_method(args: argparse.Namespace) -> int:
    raw = _read_text(args.path)
    sys.stdout.write(strip_method_from_ical(raw))
    return 0


def _cmd_extract_email(args: argparse.Namespace) -> int:
    raw = _read_bytes(args.path)
    items = extract_notifications_from_email(
        raw,
        strict=not args.lenient,
        strip_method=args.strip_method,
    )
    if args.as_json:
        print(json.dumps([n.to_dict() for n in items], indent=2))
    else:
        print(f"Found {len(items)} maintenance notification(s)")
        for notif in items:
            print(
                f"- UID={notif.uid} SEQ={notif.sequence} PROVIDER={notif.provider} "
                f"ID={notif.maintenance_id} IMPACT={notif.impact.raw} "
                f"STATUS={notif.status.raw if notif.status else 'UNSPECIFIED'}"
            )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
