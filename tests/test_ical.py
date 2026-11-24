"""Tests for low-level RFC 5545 iCalendar parsing and serialization."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from maintnote.exceptions import ICalSyntaxError
from maintnote.ical import (
    ContentLine,
    escape_text,
    fold_line,
    format_datetime,
    parse_content_line,
    parse_datetime,
    parse_ical_components,
    unescape_text,
    unfold_lines,
)


def test_fold_and_unfold_preserves_multibyte_utf8() -> None:
    text = "SUMMARY:" + ("ネットワーク保守作業—" * 15)
    folded = fold_line(text)
    for physical in folded.split("\r\n"):
        assert len(physical.encode("utf-8")) <= 75
    unfolded = unfold_lines(folded)
    assert len(unfolded) == 1
    assert unfolded[0][1] == text


def test_unfold_supports_space_and_tab_continuations() -> None:
    raw = 'X-MAINTNOTE-OBJECT-ID;ALTREP="https://example.org/\r\n maintenance?id=123":\r\n\t2718281828459\r\n'
    unfolded = unfold_lines(raw)
    assert unfolded == [
        (1, 'X-MAINTNOTE-OBJECT-ID;ALTREP="https://example.org/maintenance?id=123":2718281828459')
    ]


def test_unfold_rejects_leading_continuation() -> None:
    with pytest.raises(ICalSyntaxError, match="continuation"):
        unfold_lines(" orphaned line\r\n")


def test_text_escape_and_unescape_roundtrip() -> None:
    original = "Line 1; with, comma & \\backslash\\\nLine 2"
    escaped = escape_text(original)
    assert escaped == r"Line 1\; with\, comma & \\backslash\\\nLine 2"
    assert unescape_text(escaped) == original
    assert unescape_text(r"A\NB") == "A\nB"


def test_parse_content_line_with_quoted_peeringdb_altrep() -> None:
    line = (
        "X-MAINTNOTE-OBJECT-ID;"
        'ALTREP="https://www.peeringdb.com/api/netixlan?asn__in=64496,65536&ipaddr4__in=192.0.2.42,192.0.2.137":'
        "2718281828459"
    )
    cl = parse_content_line(line)
    assert cl.name == "X-MAINTNOTE-OBJECT-ID"
    assert cl.value == "2718281828459"
    assert cl.get_param("ALTREP") == (
        "https://www.peeringdb.com/api/netixlan?asn__in=64496,65536&ipaddr4__in=192.0.2.42,192.0.2.137"
    )
    # Round-trip back to iCalendar and re-parse
    re_parsed = parse_content_line(unfold_lines(cl.to_ical())[0][1])
    assert re_parsed == cl


def test_parse_content_line_rfc6868_caret_escaping() -> None:
    cl = ContentLine("ORGANIZER", "mailto:noc@example.com", {"CN": ('NOC "Primary"\nTeam ^1',)})
    serialized = cl.to_ical(fold=False)
    reparsed = parse_content_line(serialized)
    assert reparsed.get_param("CN") == 'NOC "Primary"\nTeam ^1'


def test_parse_content_line_errors() -> None:
    with pytest.raises(ICalSyntaxError):
        parse_content_line("NO_COLON_HERE")
    with pytest.raises(ICalSyntaxError):
        parse_content_line('SUMMARY;CN="unterminated:value')
    with pytest.raises(ICalSyntaxError):
        parse_content_line("SUMMARY;BADPARAM:value")


def test_parse_ical_components_errors() -> None:
    with pytest.raises(ICalSyntaxError):
        parse_ical_components("")
    with pytest.raises(ICalSyntaxError):
        parse_ical_components("SUMMARY:Outside\r\n")
    with pytest.raises(ICalSyntaxError):
        parse_ical_components("BEGIN:VCALENDAR\r\nEND:VEVENT\r\n")
    with pytest.raises(ICalSyntaxError):
        parse_ical_components("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n")


def test_datetime_utc_tzid_and_floating() -> None:
    dt_utc = parse_datetime("20260501T080000Z")
    assert dt_utc == datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc)

    dt_tz = parse_datetime("20260501T080000", tzid="America/Los_Angeles")
    assert dt_tz.tzinfo is not None
    assert dt_tz.astimezone(timezone.utc) == datetime(2026, 5, 1, 15, 0, 0, tzinfo=timezone.utc)

    dt_float = parse_datetime("20260501T080000")
    assert dt_float.tzinfo is None

    params, formatted = format_datetime(dt_tz)
    assert params == {"VALUE": ("DATE-TIME",)}
    assert formatted == "20260501T150000Z"

    with pytest.raises(ICalSyntaxError):
        parse_datetime("20260501T080000Z", tzid="UTC")
    with pytest.raises(ICalSyntaxError):
        parse_datetime("20260501T080000", tzid="No/Such_Timezone")
    with pytest.raises(ICalSyntaxError):
        parse_datetime("not-a-date")
