"""Parser and validator for draft-gunter-calext-maintenance-notifications-00."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import IO

from maintnote.exceptions import (
    ICalSyntaxError,
    ParseError,
    ValidationError,
    ValidationIssue,
)
from maintnote.ical import (
    ContentLine,
    ICalComponent,
    parse_datetime,
    parse_ical_components,
    unescape_text,
)
from maintnote.models import (
    ICAL_VERSION,
    CalendarDocument,
    ImpactValue,
    MaintenanceNotification,
    Organizer,
    ServiceObject,
    StatusValue,
)

# Draft Table 2 accidentally wrote "X-MAINTENOTE-*" instead of "X-MAINTNOTE-*".
# In lenient mode we accept the typo while reporting a structured warning.
_TYPO_ALIASES: dict[str, str] = {
    "X-MAINTENOTE-PROVIDER": "X-MAINTNOTE-PROVIDER",
    "X-MAINTENOTE-ACCOUNT": "X-MAINTNOTE-ACCOUNT",
    "X-MAINTENOTE-MAINTENANCE-ID": "X-MAINTNOTE-MAINTENANCE-ID",
    "X-MAINTENOTE-OBJECT-ID": "X-MAINTNOTE-OBJECT-ID",
    "X-MAINTENOTE-IMPACT": "X-MAINTNOTE-IMPACT",
    "X-MAINTENOTE-STATUS": "X-MAINTNOTE-STATUS",
}

_MANAGED_CALENDAR_PROPS: frozenset[str] = frozenset({"VERSION", "PRODID", "METHOD"})

_MANAGED_EVENT_PROPS: frozenset[str] = frozenset(
    {
        "DTSTAMP",
        "DTSTART",
        "DTEND",
        "UID",
        "SUMMARY",
        "ORGANIZER",
        "SEQUENCE",
        "DESCRIPTION",
        "LOCATION",
        "URL",
        "X-MAINTNOTE-PROVIDER",
        "X-MAINTNOTE-ACCOUNT",
        "X-MAINTNOTE-MAINTENANCE-ID",
        "X-MAINTNOTE-OBJECT-ID",
        "X-MAINTNOTE-IMPACT",
        "X-MAINTNOTE-STATUS",
    }
)


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Result returned by :func:`parse_with_diagnostics` containing warnings."""

    document: CalendarDocument
    warnings: tuple[ValidationIssue, ...] = ()

    @property
    def notification(self) -> MaintenanceNotification:
        """Return the single notification when the document contains exactly one VEVENT."""
        if len(self.document.notifications) != 1:
            raise ParseError(f"Expected exactly 1 VEVENT, found {len(self.document.notifications)}")
        return self.document.notifications[0]


def validate(notification: MaintenanceNotification) -> list[ValidationIssue]:
    """Validate a :class:`MaintenanceNotification` against draft-gunter-calext-maintenance-notifications-00.

    Returns a list of :class:`ValidationIssue` objects (both ``error`` and ``warning``).
    An empty list (or a list with no ``severity == "error"`` entries) indicates conformance.
    """
    issues: list[ValidationIssue] = []

    if notification.version != ICAL_VERSION:
        issues.append(
            ValidationIssue(
                code="INVALID_VERSION",
                message=f"VERSION must be '2.0', got {notification.version!r}",
                severity="error",
                property_name="VERSION",
            )
        )

    if not notification.prodid.strip():
        issues.append(
            ValidationIssue(
                code="MISSING_PRODID",
                message="PRODID must be a non-empty string",
                severity="error",
                property_name="PRODID",
            )
        )

    if not notification.uid.strip():
        issues.append(
            ValidationIssue(
                code="MISSING_UID",
                message="UID must be a non-empty string",
                severity="error",
                property_name="UID",
            )
        )

    if notification.sequence < 0:
        issues.append(
            ValidationIssue(
                code="INVALID_SEQUENCE",
                message=f"SEQUENCE must be a non-negative integer, got {notification.sequence}",
                severity="error",
                property_name="SEQUENCE",
            )
        )

    if not notification.summary.strip():
        issues.append(
            ValidationIssue(
                code="MISSING_SUMMARY",
                message="SUMMARY must be a non-empty string",
                severity="error",
                property_name="SUMMARY",
            )
        )

    if not notification.provider.strip():
        issues.append(
            ValidationIssue(
                code="MISSING_PROVIDER",
                message="X-MAINTNOTE-PROVIDER must be a non-empty string",
                severity="error",
                property_name="X-MAINTNOTE-PROVIDER",
            )
        )

    if not notification.account.strip():
        issues.append(
            ValidationIssue(
                code="MISSING_ACCOUNT",
                message="X-MAINTNOTE-ACCOUNT must be a non-empty string",
                severity="error",
                property_name="X-MAINTNOTE-ACCOUNT",
            )
        )

    if not notification.maintenance_id.strip():
        issues.append(
            ValidationIssue(
                code="MISSING_MAINTENANCE_ID",
                message="X-MAINTNOTE-MAINTENANCE-ID must be a non-empty string",
                severity="error",
                property_name="X-MAINTNOTE-MAINTENANCE-ID",
            )
        )

    if not notification.objects:
        issues.append(
            ValidationIssue(
                code="MISSING_OBJECT_ID",
                message="At least one X-MAINTNOTE-OBJECT-ID property is required",
                severity="error",
                property_name="X-MAINTNOTE-OBJECT-ID",
            )
        )

    # Timestamp comparability and ordering checks
    dtstart_aware = notification.dtstart.tzinfo is not None
    dtend_aware = notification.dtend.tzinfo is not None
    if dtstart_aware != dtend_aware:
        issues.append(
            ValidationIssue(
                code="MISMATCHED_TIMEZONES",
                message="DTSTART and DTEND must both be timezone-aware or both be floating (naive)",
                severity="error",
                property_name="DTEND",
            )
        )
    elif notification.dtend < notification.dtstart:
        issues.append(
            ValidationIssue(
                code="INVALID_TIME_RANGE",
                message="DTEND must not precede DTSTART",
                severity="error",
                property_name="DTEND",
            )
        )

    if not dtstart_aware or not dtend_aware or notification.dtstamp.tzinfo is None:
        issues.append(
            ValidationIssue(
                code="FLOATING_TIMESTAMP",
                message="UTC timezone-aware timestamps are strongly recommended for cross-timezone automation",
                severity="warning",
                property_name="DTSTAMP",
            )
        )

    if not notification.impact.is_standard:
        issues.append(
            ValidationIssue(
                code="NONSTANDARD_IMPACT",
                message=(
                    f"Non-standard X-MAINTNOTE-IMPACT value {notification.impact.raw!r}; "
                    "per Section 2.5.5 consumers SHOULD treat unrecognized values as OUTAGE"
                ),
                severity="warning",
                property_name="X-MAINTNOTE-IMPACT",
            )
        )

    if notification.status is not None and not notification.status.is_standard:
        issues.append(
            ValidationIssue(
                code="NONSTANDARD_STATUS",
                message=f"Non-standard X-MAINTNOTE-STATUS value {notification.status.raw!r}",
                severity="warning",
                property_name="X-MAINTNOTE-STATUS",
            )
        )

    # Check for conflicting extra properties (Section 2.4)
    for prop in notification.extra_calendar_properties:
        if prop.name in _MANAGED_CALENDAR_PROPS:
            issues.append(
                ValidationIssue(
                    code="CONFLICTING_CALENDAR_PROPERTY",
                    message=f"Extra calendar property {prop.name} conflicts with managed property",
                    severity="error",
                    property_name=prop.name,
                )
            )

    for prop in notification.extra_event_properties:
        if prop.name in _MANAGED_EVENT_PROPS:
            issues.append(
                ValidationIssue(
                    code="CONFLICTING_EVENT_PROPERTY",
                    message=f"Extra event property {prop.name} conflicts with managed property",
                    severity="error",
                    property_name=prop.name,
                )
            )

    return issues


def parse(ical_text: str | bytes, *, strict: bool = True) -> MaintenanceNotification:
    """Parse a single maintenance notification from RFC 5545 iCalendar text or UTF-8 bytes."""
    result = parse_with_diagnostics(ical_text, strict=strict)
    return result.notification


def load(fp: IO[str] | IO[bytes], *, strict: bool = True) -> MaintenanceNotification:
    """Read and parse a single maintenance notification from a file-like object."""
    return parse(fp.read(), strict=strict)


def parse_calendar(ical_text: str | bytes, *, strict: bool = True) -> CalendarDocument:
    """Parse a ``VCALENDAR`` containing one or more maintenance notification ``VEVENT``s."""
    return parse_with_diagnostics(ical_text, strict=strict).document


def parse_with_diagnostics(ical_text: str | bytes, *, strict: bool = True) -> ParseResult:
    """Parse an iCalendar payload and return both the :class:`CalendarDocument` and warnings."""
    if isinstance(ical_text, bytes):
        try:
            text = ical_text.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParseError(f"iCalendar payload is not valid UTF-8: {exc}") from exc
    else:
        text = ical_text

    try:
        roots = parse_ical_components(text)
    except ICalSyntaxError as exc:
        raise ParseError(str(exc)) from exc

    calendars = [comp for comp in roots if comp.name == "VCALENDAR"]
    if len(calendars) != 1:
        raise ValidationError(
            "Expected exactly one VCALENDAR root component",
            [
                ValidationIssue(
                    code="INVALID_ROOT",
                    message=f"Found {len(calendars)} VCALENDAR components",
                    severity="error",
                )
            ],
        )

    cal = calendars[0]
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    version = _require_single_prop(cal, "VERSION", errors)
    if version is not None and version.value.strip() != ICAL_VERSION:
        errors.append(
            ValidationIssue(
                code="INVALID_VERSION",
                message=f"VERSION must be '2.0', got {version.value.strip()!r}",
                severity="error",
                property_name="VERSION",
            )
        )

    prodid = _require_single_prop(cal, "PRODID", errors)
    method_prop = _optional_single_prop(cal, "METHOD", errors)

    extra_cal_props = tuple(
        prop for prop in cal.properties if prop.name not in _MANAGED_CALENDAR_PROPS
    )

    vevents = cal.get_subcomponents("VEVENT")
    if not vevents:
        errors.append(
            ValidationIssue(
                code="MISSING_VEVENT",
                message="VCALENDAR must contain at least one VEVENT component",
                severity="error",
            )
        )

    if errors:
        raise ValidationError("Invalid VCALENDAR maintenance notification", errors)

    assert version is not None
    assert prodid is not None

    notifications: list[MaintenanceNotification] = []
    for vevent in vevents:
        notif = _parse_vevent(
            vevent,
            version=version.value.strip(),
            prodid=unescape_text(prodid.value),
            method=method_prop.value.strip().upper() if method_prop is not None else None,
            extra_calendar_properties=extra_cal_props,
            strict=strict,
            warnings=warnings,
        )
        notifications.append(notif)

    doc = CalendarDocument(
        notifications=tuple(notifications),
        version=version.value.strip(),
        prodid=unescape_text(prodid.value),
        method=method_prop.value.strip().upper() if method_prop is not None else None,
        extra_calendar_properties=extra_cal_props,
    )
    return ParseResult(document=doc, warnings=tuple(warnings))


def _parse_vevent(
    vevent: ICalComponent,
    *,
    version: str,
    prodid: str,
    method: str | None,
    extra_calendar_properties: tuple[ContentLine, ...],
    strict: bool,
    warnings: list[ValidationIssue],
) -> MaintenanceNotification:
    errors: list[ValidationIssue] = []

    # Normalize properties (supporting draft Table 2 typo X-MAINTENOTE-* in lenient mode)
    normalized_props: list[ContentLine] = []
    for prop in vevent.properties:
        if not strict and prop.name in _TYPO_ALIASES:
            canonical = _TYPO_ALIASES[prop.name]
            warnings.append(
                ValidationIssue(
                    code="LEGACY_TYPO_PROPERTY",
                    message=f"Mapped draft Table 2 typo property {prop.name} to {canonical}",
                    severity="warning",
                    property_name=prop.name,
                )
            )
            normalized_props.append(
                ContentLine(name=canonical, value=prop.value, params=prop.params)
            )
        else:
            normalized_props.append(prop)

    normalized_event = ICalComponent(
        name=vevent.name,
        properties=normalized_props,
        subcomponents=vevent.subcomponents,
    )

    dtstamp_prop = _require_single_prop(normalized_event, "DTSTAMP", errors)
    dtstart_prop = _require_single_prop(normalized_event, "DTSTART", errors)
    dtend_prop = _require_single_prop(normalized_event, "DTEND", errors)
    uid_prop = _require_single_prop(normalized_event, "UID", errors)
    summary_prop = _require_single_prop(normalized_event, "SUMMARY", errors)
    organizer_prop = _require_single_prop(normalized_event, "ORGANIZER", errors)
    sequence_prop = _require_single_prop(normalized_event, "SEQUENCE", errors)

    provider_prop = _require_single_prop(normalized_event, "X-MAINTNOTE-PROVIDER", errors)
    account_prop = _require_single_prop(normalized_event, "X-MAINTNOTE-ACCOUNT", errors)
    maint_id_prop = _require_single_prop(normalized_event, "X-MAINTNOTE-MAINTENANCE-ID", errors)
    impact_prop = _require_single_prop(normalized_event, "X-MAINTNOTE-IMPACT", errors)
    status_prop = _optional_single_prop(normalized_event, "X-MAINTNOTE-STATUS", errors)

    object_props = normalized_event.get_properties("X-MAINTNOTE-OBJECT-ID")
    if not object_props:
        errors.append(
            ValidationIssue(
                code="MISSING_PROPERTY",
                message="Required property X-MAINTNOTE-OBJECT-ID is missing",
                severity="error",
                property_name="X-MAINTNOTE-OBJECT-ID",
            )
        )

    description_prop = _optional_single_prop(normalized_event, "DESCRIPTION", errors)
    location_prop = _optional_single_prop(normalized_event, "LOCATION", errors)
    url_prop = _optional_single_prop(normalized_event, "URL", errors)

    dtstamp = _parse_dt_prop(dtstamp_prop, errors) if dtstamp_prop is not None else None
    dtstart = _parse_dt_prop(dtstart_prop, errors) if dtstart_prop is not None else None
    dtend = _parse_dt_prop(dtend_prop, errors) if dtend_prop is not None else None

    sequence: int | None = None
    if sequence_prop is not None:
        try:
            sequence = int(sequence_prop.value.strip())
            if sequence < 0:
                errors.append(
                    ValidationIssue(
                        code="INVALID_SEQUENCE",
                        message=f"SEQUENCE must be >= 0, got {sequence}",
                        severity="error",
                        property_name="SEQUENCE",
                    )
                )
        except ValueError:
            errors.append(
                ValidationIssue(
                    code="INVALID_SEQUENCE",
                    message=f"SEQUENCE must be an integer, got {sequence_prop.value!r}",
                    severity="error",
                    property_name="SEQUENCE",
                )
            )

    organizer: Organizer | None = None
    if organizer_prop is not None:
        try:
            organizer = Organizer(
                address=organizer_prop.value,
                cn=organizer_prop.get_param("CN"),
                params=organizer_prop.params,
            )
        except ValidationError as exc:
            errors.append(
                ValidationIssue(
                    code="INVALID_ORGANIZER",
                    message=str(exc),
                    severity="error",
                    property_name="ORGANIZER",
                )
            )

    objects: list[ServiceObject] = []
    for obj_prop in object_props:
        try:
            objects.append(
                ServiceObject(
                    object_id=unescape_text(obj_prop.value),
                    altrep=obj_prop.get_param("ALTREP"),
                    language=obj_prop.get_param("LANGUAGE"),
                    params=obj_prop.params,
                )
            )
        except ValidationError as exc:
            errors.append(
                ValidationIssue(
                    code="INVALID_OBJECT_ID",
                    message=str(exc),
                    severity="error",
                    property_name="X-MAINTNOTE-OBJECT-ID",
                )
            )

    impact: ImpactValue | None = None
    if impact_prop is not None:
        if impact_prop.value != impact_prop.value.strip():
            warnings.append(
                ValidationIssue(
                    code="WHITESPACE_VALUE",
                    message="X-MAINTNOTE-IMPACT contains leading/trailing whitespace",
                    severity="warning",
                    property_name="X-MAINTNOTE-IMPACT",
                )
            )
        try:
            impact = ImpactValue(raw=impact_prop.value, params=impact_prop.params)
        except ValidationError as exc:
            errors.append(
                ValidationIssue(
                    code="INVALID_IMPACT",
                    message=str(exc),
                    severity="error",
                    property_name="X-MAINTNOTE-IMPACT",
                )
            )

    status: StatusValue | None = None
    if status_prop is not None:
        if status_prop.value != status_prop.value.strip():
            # Notably present in Example 4.5 of the Internet-Draft itself:
            # `X-MAINTNOTE-STATUS: COMPLETED`
            warnings.append(
                ValidationIssue(
                    code="WHITESPACE_VALUE",
                    message="X-MAINTNOTE-STATUS contains leading/trailing whitespace",
                    severity="warning",
                    property_name="X-MAINTNOTE-STATUS",
                )
            )
        try:
            status = StatusValue(raw=status_prop.value, params=status_prop.params)
        except ValidationError as exc:
            errors.append(
                ValidationIssue(
                    code="INVALID_STATUS",
                    message=str(exc),
                    severity="error",
                    property_name="X-MAINTNOTE-STATUS",
                )
            )

    if errors:
        raise ValidationError("Invalid VEVENT maintenance notification", errors)

    assert uid_prop is not None
    assert sequence is not None
    assert dtstamp is not None
    assert dtstart is not None
    assert dtend is not None
    assert summary_prop is not None
    assert organizer is not None
    assert provider_prop is not None
    assert account_prop is not None
    assert maint_id_prop is not None
    assert impact is not None

    extra_event_props = tuple(
        prop for prop in normalized_event.properties if prop.name not in _MANAGED_EVENT_PROPS
    )

    notification = MaintenanceNotification(
        uid=unescape_text(uid_prop.value),
        sequence=sequence,
        dtstamp=dtstamp,
        dtstart=dtstart,
        dtend=dtend,
        summary=unescape_text(summary_prop.value),
        organizer=organizer,
        provider=unescape_text(provider_prop.value),
        account=unescape_text(account_prop.value),
        maintenance_id=unescape_text(maint_id_prop.value),
        objects=tuple(objects),
        impact=impact,
        status=status,
        version=version,
        prodid=prodid,
        method=method,
        description=unescape_text(description_prop.value) if description_prop is not None else None,
        location=unescape_text(location_prop.value) if location_prop is not None else None,
        url=url_prop.value if url_prop is not None else None,
        summary_params=summary_prop.params,
        description_params=description_prop.params if description_prop is not None else {},
        provider_params=provider_prop.params,
        account_params=account_prop.params,
        maintenance_id_params=maint_id_prop.params,
        extra_calendar_properties=extra_calendar_properties,
        extra_event_properties=extra_event_props,
    )

    validation_issues = validate(notification)
    val_errors = [issue for issue in validation_issues if issue.severity == "error"]
    val_warnings = [issue for issue in validation_issues if issue.severity == "warning"]
    warnings.extend(val_warnings)

    if val_errors:
        raise ValidationError("Maintenance notification failed validation", val_errors)

    return notification


def _require_single_prop(
    comp: ICalComponent, name: str, errors: list[ValidationIssue]
) -> ContentLine | None:
    props = comp.get_properties(name)
    if len(props) == 0:
        errors.append(
            ValidationIssue(
                code="MISSING_PROPERTY",
                message=f"Required property {name} is missing",
                severity="error",
                property_name=name,
            )
        )
        return None
    if len(props) > 1:
        errors.append(
            ValidationIssue(
                code="DUPLICATE_PROPERTY",
                message=f"Property {name} must appear exactly once, found {len(props)}",
                severity="error",
                property_name=name,
            )
        )
        return None
    return props[0]


def _optional_single_prop(
    comp: ICalComponent, name: str, errors: list[ValidationIssue]
) -> ContentLine | None:
    props = comp.get_properties(name)
    if len(props) == 0:
        return None
    if len(props) > 1:
        errors.append(
            ValidationIssue(
                code="DUPLICATE_PROPERTY",
                message=f"Property {name} may appear at most once, found {len(props)}",
                severity="error",
                property_name=name,
            )
        )
        return None
    return props[0]


def _parse_dt_prop(prop: ContentLine, errors: list[ValidationIssue]) -> datetime | None:
    tzid = prop.get_param("TZID")
    try:
        return parse_datetime(prop.value, tzid=tzid)
    except ICalSyntaxError as exc:
        errors.append(
            ValidationIssue(
                code="INVALID_DATETIME",
                message=str(exc),
                severity="error",
                property_name=prop.name,
            )
        )
        return None
