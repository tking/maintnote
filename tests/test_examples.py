"""Smoke tests ensuring all runnable examples and sample fixtures stay valid."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from maintnote import (
    Impact,
    ValidationError,
    extract_notifications_from_email,
    parse,
    parse_calendar,
    strip_method_from_email,
    strip_method_from_ical,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
EXAMPLES_DIR = REPO_ROOT / "examples"
SAMPLES_DIR = EXAMPLES_DIR / "samples"

EXAMPLE_SCRIPTS = (
    "provider_lifecycle.py",
    "consumer_pipeline.py",
    "multi_customer_batch.py",
    "multi_provider_automation.py",
    "signed_email_and_sanitization.py",
    "caldav_and_altrep_demo.py",
    "localization_and_lenient_parsing.py",
)

VALID_SAMPLE_ICS = (
    "01_initial.ics",
    "02_confirmed.ics",
    "03_open.ics",
    "04_closed.ics",
    "cancelled.ics",
    "legacy_with_method.ics",
    "multi_event_feed.ics",
)


def _example_env() -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{SRC_DIR}{os.pathsep}{existing}" if existing else str(SRC_DIR)
    return env


@pytest.mark.parametrize("script_name", EXAMPLE_SCRIPTS)
def test_python_example_runs_cleanly(script_name: str) -> None:
    """Every script in examples/ must execute cleanly with exit code 0."""
    script_path = EXAMPLES_DIR / script_name
    assert script_path.is_file()
    proc = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=REPO_ROOT,
        env=_example_env(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, (
        f"Example {script_name} failed (rc={proc.returncode}):\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    assert proc.stdout.strip()


@pytest.mark.skipif(sys.platform == "win32", reason="CLI shell walkthrough requires POSIX bash")
def test_cli_walkthrough_script_runs_cleanly() -> None:
    """The CLI walkthrough script must succeed against the sample fixtures."""
    script_path = EXAMPLES_DIR / "cli_walkthrough.sh"
    assert script_path.is_file()
    env = _example_env()
    env["MAINTNOTE_CMD"] = f"{sys.executable} -m maintnote.cli"
    proc = subprocess.run(
        ["bash", str(script_path)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, (
        f"cli_walkthrough.sh failed (rc={proc.returncode}):\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    assert "VALID (1 VEVENT(s))" in proc.stdout


@pytest.mark.parametrize("sample_name", VALID_SAMPLE_ICS)
def test_valid_sample_ics_fixtures_parse_strictly(sample_name: str) -> None:
    """All valid .ics sample fixtures must pass strict parsing."""
    raw = (SAMPLES_DIR / sample_name).read_text(encoding="utf-8")
    doc = parse_calendar(raw, strict=True)
    assert len(doc.notifications) >= 1


def test_sample_lifecycle_sequence_and_multi_event_feed() -> None:
    """Lifecycle sample fixtures share one UID with monotonic SEQUENCE 0..3."""
    lifecycle_files = ("01_initial.ics", "02_confirmed.ics", "03_open.ics", "04_closed.ics")
    notifs = [parse((SAMPLES_DIR / name).read_text(encoding="utf-8")) for name in lifecycle_files]
    assert len({n.uid for n in notifs}) == 1
    assert [n.sequence for n in notifs] == [0, 1, 2, 3]

    feed = parse_calendar((SAMPLES_DIR / "multi_event_feed.ics").read_text(encoding="utf-8"))
    assert len(feed.notifications) == 2


def test_legacy_samples_and_invalid_sample_behavior() -> None:
    """Verify legacy METHOD/custom-impact fixtures and invalid-window error handling."""
    legacy_ics = (SAMPLES_DIR / "legacy_with_method.ics").read_text(encoding="utf-8")
    legacy_notif = parse(legacy_ics, strict=True)
    assert legacy_notif.method == "PUBLISH"
    assert legacy_notif.impact.raw == "X-PACKET-LOSS"
    assert legacy_notif.effective_impact is Impact.OUTAGE
    cleaned_ics = strip_method_from_ical(legacy_ics)
    assert parse(cleaned_ics, strict=True).method is None

    legacy_eml = (SAMPLES_DIR / "legacy_provider.eml").read_bytes()
    extracted = extract_notifications_from_email(legacy_eml, strict=True, strip_method=True)
    assert len(extracted) == 1
    assert extracted[0].method is None
    sanitized_eml = strip_method_from_email(legacy_eml)
    assert all(part.get_param("method") is None for part in sanitized_eml.walk())

    invalid_ics = (SAMPLES_DIR / "invalid_window.ics").read_text(encoding="utf-8")
    with pytest.raises(ValidationError):
        parse_calendar(invalid_ics, strict=True)
