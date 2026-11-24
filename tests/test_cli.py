"""End-to-end tests for the maintnote command-line interface."""

from __future__ import annotations

import json
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
