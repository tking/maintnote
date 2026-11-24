"""RFC 5545 serializer for draft-gunter-calext-maintenance-notifications-00."""

from __future__ import annotations

from typing import IO

from maintnote.exceptions import ValidationError
from maintnote.ical import ContentLine, ICalComponent, escape_text, format_datetime
from maintnote.models import CalendarDocument, MaintenanceNotification
from maintnote.parser import validate


def dumps(
    notification: MaintenanceNotification,
    *,
    include_method: bool | None = None,
    method: str | None = None,
    fold_lines: bool = True,
    validate_before_dump: bool = True,
) -> str:
    """Serialize a :class:`MaintenanceNotification` to an RFC 5545 iCalendar string.

    Per Section 2.3.1 of the draft:
    - By default, ``METHOD`` is omitted unless ``notification.method`` is set or
      explicitly requested via ``include_method=True``.
    - Passing ``include_method=False`` suppresses ``METHOD`` even if set on the
      model (useful for per-recipient delivery preferences).
    """
    if validate_before_dump:
        errors = [issue for issue in validate(notification) if issue.severity == "error"]
        if errors:
            raise ValidationError("Cannot serialize invalid MaintenanceNotification", errors)

    resolved_method = _resolve_method(
        model_method=notification.method,
        include_method=include_method,
        override_method=method,
    )

    doc = CalendarDocument(
        notifications=(notification,),
        version=notification.version,
        prodid=notification.prodid,
        method=resolved_method,
        extra_calendar_properties=notification.extra_calendar_properties,
        extra_calendar_subcomponents=notification.extra_calendar_subcomponents,
    )
    return dumps_calendar(
        doc,
        include_method=include_method,
        method=method,
        fold_lines=fold_lines,
        validate_before_dump=False,
    )


def dump(
    notification: MaintenanceNotification,
    fp: IO[str],
    *,
    include_method: bool | None = None,
    method: str | None = None,
    fold_lines: bool = True,
    validate_before_dump: bool = True,
) -> None:
    """Serialize a :class:`MaintenanceNotification` directly to a text file-like object."""
    fp.write(
        dumps(
            notification,
            include_method=include_method,
            method=method,
            fold_lines=fold_lines,
            validate_before_dump=validate_before_dump,
        )
    )


def dumps_calendar(
    document: CalendarDocument,
    *,
    include_method: bool | None = None,
    method: str | None = None,
    fold_lines: bool = True,
    validate_before_dump: bool = True,
) -> str:
    """Serialize a multi-event :class:`CalendarDocument` to an RFC 5545 string."""
    if not document.notifications:
        raise ValidationError("CalendarDocument must contain at least one notification")

    if validate_before_dump:
        for notif in document.notifications:
            errors = [issue for issue in validate(notif) if issue.severity == "error"]
            if errors:
                raise ValidationError("Cannot serialize invalid MaintenanceNotification", errors)

    resolved_method = _resolve_method(
        model_method=document.method,
        include_method=include_method,
        override_method=method,
    )

    cal_props: list[ContentLine] = [
        ContentLine("VERSION", document.version),
        ContentLine("PRODID", escape_text(document.prodid)),
    ]
    if resolved_method is not None:
        cal_props.append(ContentLine("METHOD", resolved_method.upper()))
    cal_props.extend(document.extra_calendar_properties)

    subcomponents: list[ICalComponent] = list(document.extra_calendar_subcomponents)
    subcomponents.extend(_build_vevent(notif) for notif in document.notifications)
    vcal = ICalComponent(name="VCALENDAR", properties=cal_props, subcomponents=subcomponents)
    return vcal.to_ical(fold=fold_lines)


def _resolve_method(
    *,
    model_method: str | None,
    include_method: bool | None,
    override_method: str | None,
) -> str | None:
    if include_method is False:
        return None
    if override_method is not None:
        return override_method.strip().upper()
    if include_method is True:
        return (model_method or "PUBLISH").strip().upper()
    return model_method.strip().upper() if model_method is not None else None


def _build_vevent(notification: MaintenanceNotification) -> ICalComponent:
    dtstart_params, dtstart_val = format_datetime(notification.dtstart)
    dtend_params, dtend_val = format_datetime(notification.dtend)
    dtstamp_params, dtstamp_val = format_datetime(notification.dtstamp)

    org_params: dict[str, tuple[str, ...]] = {}
    if notification.organizer.cn is not None:
        org_params["CN"] = (notification.organizer.cn,)
    org_params.update(notification.organizer.params)

    props: list[ContentLine] = [
        ContentLine("SUMMARY", escape_text(notification.summary), notification.summary_params),
        ContentLine("DTSTART", dtstart_val, dtstart_params),
        ContentLine("DTEND", dtend_val, dtend_params),
        ContentLine("DTSTAMP", dtstamp_val, dtstamp_params),
        ContentLine("UID", escape_text(notification.uid)),
        ContentLine("SEQUENCE", str(notification.sequence)),
        ContentLine(
            "X-MAINTNOTE-PROVIDER",
            escape_text(notification.provider),
            notification.provider_params,
        ),
        ContentLine(
            "X-MAINTNOTE-ACCOUNT",
            escape_text(notification.account),
            notification.account_params,
        ),
        ContentLine(
            "X-MAINTNOTE-MAINTENANCE-ID",
            escape_text(notification.maintenance_id),
            notification.maintenance_id_params,
        ),
    ]

    for obj in notification.objects:
        props.append(
            ContentLine(
                "X-MAINTNOTE-OBJECT-ID",
                escape_text(obj.object_id),
                obj.all_params(),
            )
        )

    props.append(
        ContentLine(
            "X-MAINTNOTE-IMPACT",
            notification.impact.raw,
            notification.impact.params,
        )
    )

    if notification.status is not None:
        props.append(
            ContentLine(
                "X-MAINTNOTE-STATUS",
                notification.status.raw,
                notification.status.params,
            )
        )

    props.append(ContentLine("ORGANIZER", notification.organizer.address, org_params))

    if notification.description is not None:
        props.append(
            ContentLine(
                "DESCRIPTION",
                escape_text(notification.description),
                notification.description_params,
            )
        )

    if notification.location is not None:
        props.append(
            ContentLine(
                "LOCATION", escape_text(notification.location), notification.location_params
            )
        )

    if notification.url is not None:
        props.append(ContentLine("URL", notification.url, notification.url_params))

    props.extend(notification.extra_event_properties)
    return ICalComponent(
        name="VEVENT",
        properties=props,
        subcomponents=list(notification.extra_event_subcomponents),
    )
