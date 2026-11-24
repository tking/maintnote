"""Low-level RFC 5545 iCalendar content-line parser and serializer.

Implements RFC 5545 Section 3.1 (content lines, folding/unfolding at 75 octets),
Section 3.2 (property parameters, quoted values, RFC 6868 parameter escaping),
Section 3.3.5 (DATE-TIME with UTC/TZID), Section 3.3.11 (TEXT escaping), and
Section 3.4/3.6 (component nesting).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from maintnote.exceptions import ICalSyntaxError

CRLF = "\r\n"
MAX_LINE_OCTETS = 75

_NAME_RE = re.compile(r"^[A-Za-z0-9-]+$")
_PARAM_NAME_RE = re.compile(r"^[A-Za-z0-9-]+$")
_DATETIME_RE = re.compile(
    r"^(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})"
    r"T(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})(?P<utc>Z?)$"
)
_IANA_TOKEN_RE = re.compile(r"^[A-Za-z0-9-]+$")
_X_NAME_RE = re.compile(r"^[Xx]-[A-Za-z0-9-]+$")


def is_valid_x_name(value: str) -> bool:
    """Return True if *value* matches RFC 5545 ``x-name`` syntax."""
    return bool(_X_NAME_RE.match(value))


def is_valid_iana_token(value: str) -> bool:
    """Return True if *value* matches RFC 5545 ``iana-token`` syntax."""
    return bool(_IANA_TOKEN_RE.match(value))


@dataclass(frozen=True, slots=True)
class ContentLine:
    """Represents a single RFC 5545 content line (``NAME;PARAM=VAL:VALUE``)."""

    name: str
    value: str
    params: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", self.name.upper())
        normalized: dict[str, tuple[str, ...]] = {
            k.upper(): tuple(v) for k, v in self.params.items()
        }
        object.__setattr__(self, "params", normalized)

    def get_param(self, name: str, default: str | None = None) -> str | None:
        """Return the first value for parameter *name* (case-insensitive)."""
        values = self.params.get(name.upper())
        if not values:
            return default
        return values[0]

    def get_params(self, name: str) -> tuple[str, ...]:
        """Return all values for parameter *name* (case-insensitive)."""
        return self.params.get(name.upper(), ())

    def to_ical(self, *, fold: bool = True) -> str:
        """Serialize this content line to an RFC 5545 string (without trailing CRLF)."""
        parts = [self.name]
        for param_name, param_values in self.params.items():
            encoded_values = [_format_param_value(val) for val in param_values]
            parts.append(f";{param_name}={','.join(encoded_values)}")
        parts.append(f":{self.value}")
        line = "".join(parts)
        return fold_line(line) if fold else line


@dataclass(slots=True)
class ICalComponent:
    """Represents a parsed RFC 5545 component (e.g., ``VCALENDAR``, ``VEVENT``)."""

    name: str
    properties: list[ContentLine] = field(default_factory=list)
    subcomponents: list[ICalComponent] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.name = self.name.upper()

    def get_properties(self, name: str) -> list[ContentLine]:
        """Return all properties matching *name* (case-insensitive)."""
        target = name.upper()
        return [prop for prop in self.properties if prop.name == target]

    def get_property(self, name: str) -> ContentLine | None:
        """Return the first property matching *name*, or ``None``."""
        target = name.upper()
        for prop in self.properties:
            if prop.name == target:
                return prop
        return None

    def get_subcomponents(self, name: str) -> list[ICalComponent]:
        """Return all direct subcomponents matching *name* (case-insensitive)."""
        target = name.upper()
        return [comp for comp in self.subcomponents if comp.name == target]

    def to_ical(self, *, fold: bool = True) -> str:
        """Serialize this component tree with CRLF line endings."""
        lines: list[str] = [f"BEGIN:{self.name}"]
        for prop in self.properties:
            lines.append(prop.to_ical(fold=fold))
        for sub in self.subcomponents:
            lines.append(sub.to_ical(fold=fold).rstrip("\r\n"))
        lines.append(f"END:{self.name}")
        return CRLF.join(lines) + CRLF


def unfold_lines(raw: str) -> list[tuple[int, str]]:
    """Unfold RFC 5545 content lines, preserving 1-based starting line numbers.

    Handles both CRLF (standard RFC 5545) and bare LF inputs. Empty lines are skipped.
    """
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    physical_lines = normalized.split("\n")
    unfolded: list[tuple[int, str]] = []

    for idx, phys in enumerate(physical_lines, start=1):
        if phys.startswith((" ", "\t")):
            if not unfolded:
                raise ICalSyntaxError(
                    "Unexpected folded continuation line at start of input",
                    line_number=idx,
                )
            prev_line_no, prev_text = unfolded[-1]
            unfolded[-1] = (prev_line_no, prev_text + phys[1:])
        elif phys == "":
            continue
        else:
            unfolded.append((idx, phys))

    return unfolded


def fold_line(line: str, max_octets: int = MAX_LINE_OCTETS) -> str:
    """Fold a content line per RFC 5545 Section 3.1 without splitting UTF-8 code points."""
    if len(line.encode("utf-8")) <= max_octets:
        return line

    chunks: list[str] = []
    current_chars: list[str] = []
    current_octets = 0
    limit = max_octets

    for ch in line:
        ch_octets = len(ch.encode("utf-8"))
        if current_octets + ch_octets > limit and current_chars:
            chunks.append("".join(current_chars))
            current_chars = [ch]
            current_octets = ch_octets
            # Continuation lines begin with a single SPACE octet.
            limit = max_octets - 1
        else:
            current_chars.append(ch)
            current_octets += ch_octets

    if current_chars:
        chunks.append("".join(current_chars))

    return (CRLF + " ").join(chunks)


def escape_text(text: str) -> str:
    """Escape a TEXT property value per RFC 5545 Section 3.3.11."""
    escaped = text.replace("\\", "\\\\")
    escaped = escaped.replace("\r\n", "\n").replace("\r", "\n")
    escaped = escaped.replace("\n", "\\n")
    escaped = escaped.replace(";", "\\;")
    return escaped.replace(",", "\\,")


def unescape_text(raw: str) -> str:
    """Unescape an RFC 5545 Section 3.3.11 TEXT value."""
    out: list[str] = []
    i = 0
    length = len(raw)
    while i < length:
        ch = raw[i]
        if ch == "\\" and i + 1 < length:
            nxt = raw[i + 1]
            if nxt in ("n", "N"):
                out.append("\n")
                i += 2
                continue
            if nxt in ("\\", ";", ","):
                out.append(nxt)
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _unescape_param_value(val: str) -> str:
    """Decode RFC 6868 caret-escaped characters inside parameter values."""
    if "^" not in val:
        return val
    out: list[str] = []
    i = 0
    length = len(val)
    while i < length:
        ch = val[i]
        if ch == "^" and i + 1 < length:
            nxt = val[i + 1]
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "^":
                out.append("^")
                i += 2
                continue
            if nxt == "'":
                out.append('"')
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _format_param_value(val: str) -> str:
    """Format a property parameter value, quoting if it contains ``;``, ``:``, or ``,``."""
    escaped = val.replace("^", "^^").replace("\r\n", "\n").replace("\r", "\n")
    escaped = escaped.replace("\n", "^n").replace('"', "^'")
    if any(c in escaped for c in (";", ":", ",", " ")) or escaped == "":
        return f'"{escaped}"'
    return escaped


def parse_content_line(line: str, *, line_number: int | None = None) -> ContentLine:
    """Parse a single unfolded RFC 5545 content line into a :class:`ContentLine`."""
    # Find the first unquoted ':' separating name+params from value.
    in_quotes = False
    colon_idx = -1
    for idx, ch in enumerate(line):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ":" and not in_quotes:
            colon_idx = idx
            break

    if in_quotes:
        raise ICalSyntaxError("Unterminated double-quoted parameter value", line_number=line_number)
    if colon_idx <= 0:
        raise ICalSyntaxError(
            f"Missing ':' separator in content line: {line!r}", line_number=line_number
        )

    header = line[:colon_idx]
    value = line[colon_idx + 1 :]

    # Split header on unquoted ';'
    segments: list[str] = []
    buf: list[str] = []
    in_quotes = False
    for ch in header:
        if ch == '"':
            in_quotes = not in_quotes
            buf.append(ch)
        elif ch == ";" and not in_quotes:
            segments.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    segments.append("".join(buf))

    prop_name = segments[0].strip()
    if not prop_name or not _NAME_RE.match(prop_name):
        raise ICalSyntaxError(f"Invalid property name: {prop_name!r}", line_number=line_number)

    params: dict[str, list[str]] = {}
    for seg in segments[1:]:
        if "=" not in seg:
            raise ICalSyntaxError(
                f"Malformed parameter without '=': {seg!r}",
                line_number=line_number,
            )
        p_name, p_val_raw = seg.split("=", 1)
        p_name = p_name.strip().upper()
        if not p_name or not _PARAM_NAME_RE.match(p_name):
            raise ICalSyntaxError(f"Invalid parameter name: {p_name!r}", line_number=line_number)

        values = _split_param_values(p_val_raw, line_number=line_number)
        params.setdefault(p_name, []).extend(values)

    return ContentLine(
        name=prop_name,
        value=value,
        params={k: tuple(v) for k, v in params.items()},
    )


def _split_param_values(raw: str, *, line_number: int | None = None) -> list[str]:
    """Split a comma-separated parameter value list respecting double quotes."""
    values: list[str] = []
    buf: list[str] = []
    in_quotes = False
    was_quoted = False

    for ch in raw:
        if ch == '"':
            in_quotes = not in_quotes
            was_quoted = True
        elif ch == "," and not in_quotes:
            values.append(_unescape_param_value("".join(buf)))
            buf = []
            was_quoted = False
        else:
            buf.append(ch)

    if in_quotes:
        raise ICalSyntaxError("Unterminated quoted parameter value", line_number=line_number)

    val = "".join(buf)
    if val or was_quoted or not values:
        values.append(_unescape_param_value(val))
    return values


def parse_ical_components(raw: str) -> list[ICalComponent]:
    """Parse raw iCalendar text into top-level :class:`ICalComponent` trees."""
    unfolded = unfold_lines(raw)
    if not unfolded:
        raise ICalSyntaxError("Empty iCalendar input")

    stack: list[ICalComponent] = []
    roots: list[ICalComponent] = []

    for line_no, text in unfolded:
        cl = parse_content_line(text, line_number=line_no)
        if cl.name == "BEGIN":
            comp_name = cl.value.strip().upper()
            if not comp_name or not _NAME_RE.match(comp_name):
                raise ICalSyntaxError(
                    f"Invalid component name in BEGIN: {cl.value!r}", line_number=line_no
                )
            comp = ICalComponent(name=comp_name)
            if stack:
                stack[-1].subcomponents.append(comp)
            else:
                roots.append(comp)
            stack.append(comp)
        elif cl.name == "END":
            comp_name = cl.value.strip().upper()
            if not stack:
                raise ICalSyntaxError(
                    f"Unexpected END:{comp_name} with no matching BEGIN", line_number=line_no
                )
            if stack[-1].name != comp_name:
                raise ICalSyntaxError(
                    f"Mismatched END:{comp_name}; expected END:{stack[-1].name}",
                    line_number=line_no,
                )
            stack.pop()
        else:
            if not stack:
                raise ICalSyntaxError(
                    f"Property {cl.name} encountered outside any BEGIN/END component",
                    line_number=line_no,
                )
            stack[-1].properties.append(cl)

    if stack:
        unclosed = ", ".join(c.name for c in stack)
        raise ICalSyntaxError(f"Unclosed iCalendar component(s): {unclosed}")

    return roots


def parse_datetime(value: str, *, tzid: str | None = None) -> datetime:
    """Parse an RFC 5545 DATE-TIME string into a Python :class:`datetime`.

    UTC values (trailing ``Z``) return timezone-aware UTC datetimes. Values with
    a ``TZID`` parameter return timezone-aware datetimes in that IANA timezone.
    Floating values without ``Z`` or ``TZID`` return naive datetimes.
    """
    raw = value.strip()
    match = _DATETIME_RE.match(raw)
    if not match:
        raise ICalSyntaxError(f"Invalid RFC 5545 DATE-TIME value: {value!r}")

    year = int(match.group("year"))
    month = int(match.group("month"))
    day = int(match.group("day"))
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    second = int(match.group("second"))
    is_utc = match.group("utc") == "Z"

    if is_utc and tzid:
        raise ICalSyntaxError(
            f"RFC 5545 forbids combining TZID ({tzid!r}) with UTC 'Z' suffix in {value!r}"
        )

    tzinfo: timezone | ZoneInfo | None = None
    if is_utc:
        tzinfo = timezone.utc
    elif tzid:
        try:
            tzinfo = ZoneInfo(tzid)
        except ZoneInfoNotFoundError as exc:
            raise ICalSyntaxError(f"Unknown TZID timezone: {tzid!r}") from exc

    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=tzinfo)
    except ValueError as exc:
        raise ICalSyntaxError(f"Invalid calendar date/time components in {value!r}: {exc}") from exc


def format_datetime(
    dt: datetime, *, include_value_param: bool = True
) -> tuple[dict[str, tuple[str, ...]], str]:
    """Format a Python :class:`datetime` as RFC 5545 DATE-TIME property params & value.

    Timezone-aware datetimes are normalized to UTC (``Z``) per common iCalendar
    and draft Section 4 conventions. Naive datetimes are emitted as UTC if
    converted upstream, or as floating DATE-TIME if left naive.
    """
    params: dict[str, tuple[str, ...]] = {}
    if include_value_param:
        params["VALUE"] = ("DATE-TIME",)

    if dt.tzinfo is not None:
        utc_dt = dt.astimezone(timezone.utc)
        return params, utc_dt.strftime("%Y%m%dT%H%M%SZ")

    return params, dt.strftime("%Y%m%dT%H%M%S")
