"""End-to-end tests for the maintnote command-line interface."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from maintnote.cli import main
from maintnote.email_utils import build_notification_email
from maintnote.parser import parse


def test_cli_generate_validate_parse_transition_and_strip_method(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    initial_ics = tmp_path / "initial.ics"
    rc = main(
        [
            "generate",
            "--action",
            "initial",
            "--provider",
            "example.com",
            "--account",
            "ACC-1",
            "--maintenance-id",
            "WO-100",
            "--object-id",
            "ckt-1|https://example.com/api/ckt-1",
            "--impact",
            "OUTAGE",
            "--summary",
            "Backbone router upgrade",
            "--organizer",
            "noc@example.com",
            "--organizer-cn",
            "Example NOC",
            "--dtstart",
            "2026-11-10T02:00:00Z",
            "--dtend",
            "2026-11-10T04:00:00Z",
            "--include-method",
            "-o",
            str(initial_ics),
        ]
    )
    assert rc == 0
    assert initial_ics.exists()

    # Validate --json
    assert main(["validate", str(initial_ics), "--json"]) == 0
    val_out = json.loads(capsys.readouterr().out)
    assert val_out["valid"] is True
    assert val_out["events"] == 1

    # Parse --json
    assert main(["parse", str(initial_ics), "--json"]) == 0
    parsed_json = json.loads(capsys.readouterr().out)
    assert parsed_json["provider"] == "example.com"
    assert parsed_json["method"] == "PUBLISH"
    assert parsed_json["objects"][0]["altrep"] == "https://example.com/api/ckt-1"

    # Strip METHOD
    assert main(["strip-method", str(initial_ics)]) == 0
    stripped = capsys.readouterr().out
    assert "METHOD:" not in stripped

    # Transition to open -> close
    open_ics = tmp_path / "open.ics"
    assert (
        main(["generate", "--action", "open", "--from-file", str(initial_ics), "-o", str(open_ics)])
        == 0
    )
    opened = parse(open_ics.read_text(encoding="utf-8"))
    assert opened.sequence == 1
    assert opened.is_open

    close_ics = tmp_path / "close.ics"
    assert (
        main(["generate", "--action", "close", "--from-file", str(open_ics), "-o", str(close_ics)])
        == 0
    )
    closed = parse(close_ics.read_text(encoding="utf-8"))
    assert closed.sequence == 2
    assert closed.is_closed


def test_cli_extract_email_and_error_exit_code(
    tmp_path: Path, example_4_1: str, capsys: pytest.CaptureFixture[str]
) -> None:
    notif = parse(example_4_1)
    eml = build_notification_email(
        notif,
        sender="noc@example.com",
        recipient="ops@customer.example",
    )
    eml_path = tmp_path / "notice.eml"
    eml_path.write_bytes(eml.as_bytes())

    assert main(["extract-email", str(eml_path), "--json"]) == 0
    items = json.loads(capsys.readouterr().out)
    assert len(items) == 1
    assert items[0]["uid"] == "42"

    # Invalid file returns exit code 1
    bad_ics = tmp_path / "bad.ics"
    bad_ics.write_text("NOT ICALENDAR", encoding="utf-8")
    assert main(["validate", str(bad_ics)]) == 1
    assert "Error:" in capsys.readouterr().err


class _FakeBinaryStream:
    def __init__(self, initial: bytes = b"") -> None:
        self.buffer = io.BytesIO(initial)


def test_cli_stdin_stdout_multi_event_and_error_paths(
    tmp_path: Path,
    example_4_1: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # validate reading from stdin (-) with --lenient warning output
    typo_ics = example_4_1.replace("X-MAINTNOTE-PROVIDER:", "X-MAINTENOTE-PROVIDER:")
    monkeypatch.setattr(sys, "stdin", io.StringIO(typo_ics))
    assert main(["validate", "-", "--lenient"]) == 0
    val_out = capsys.readouterr().out
    assert "VALID" in val_out
    assert "LEGACY_TYPO_PROPERTY" in val_out

    # generate to stdout with plain --object-id and naive ISO-8601 timestamps
    rc = main(
        [
            "generate",
            "--action",
            "initial",
            "--provider",
            "example.com",
            "--account",
            "ACC-2",
            "--maintenance-id",
            "WO-200",
            "--object-id",
            "ckt-plain",
            "--impact",
            "DEGRADED",
            "--summary",
            "Stdout test",
            "--organizer",
            "noc@example.com",
            "--dtstart",
            "2026-11-10T02:00:00",
            "--dtend",
            "2026-11-10T04:00:00",
        ]
    )
    assert rc == 0
    generated_stdout = capsys.readouterr().out
    assert "X-MAINTNOTE-OBJECT-ID:ckt-plain" in generated_stdout

    # generate transition without --from-file returns error code 1
    assert main(["generate", "--action", "open"]) == 1
    assert "--from-file is required" in capsys.readouterr().err

    # parse multi-event feed in text mode prints --- separator
    vevent_block = example_4_1.split("BEGIN:VEVENT", 1)[1].rsplit("END:VEVENT", 1)[0]
    multi_ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//Test//EN\r\n"
        f"BEGIN:VEVENT{vevent_block}END:VEVENT\r\n"
        f"BEGIN:VEVENT{vevent_block.replace('UID:42', 'UID:43')}END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    multi_path = tmp_path / "multi.ics"
    multi_path.write_text(multi_ics, encoding="utf-8")
    assert main(["parse", str(multi_path)]) == 0
    parse_out = capsys.readouterr().out
    assert "---" in parse_out
    assert "UID:            43" in parse_out

    # strip-email-method reading from stdin (-) and writing to stdout
    eml = build_notification_email(
        parse(example_4_1),
        sender="noc@example.com",
        recipient="ops@customer.example",
        include_method=True,
    )
    fake_in = _FakeBinaryStream(eml.as_bytes())
    fake_out = _FakeBinaryStream()
    monkeypatch.setattr(sys, "stdin", fake_in)
    monkeypatch.setattr(sys, "stdout", fake_out)
    assert main(["strip-email-method", "-"]) == 0
    assert b"METHOD:" not in fake_out.buffer.getvalue()
