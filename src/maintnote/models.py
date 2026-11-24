"""Typed domain models for IETF draft-gunter-calext-maintenance-notifications-00."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from maintnote.exceptions import ValidationError
from maintnote.ical import ContentLine, ICalComponent, is_valid_iana_token, is_valid_x_name

DEFAULT_PRODID = "-//maintnote//https://github.com/tking/maintnote//EN"
ICAL_VERSION = "2.0"


@dataclass(frozen=True, slots=True)
class LocalizationStrings:
    """Configurable localized labels for generated summaries and emails (Section 5.1)."""

    open_prefix: str = "Open - "
    closed_prefix: str = "Closed - "
    email_title: str = "Maintenance Notification"
    email_provider: str = "Provider"
    email_account: str = "Account"
    email_maintenance_id: str = "Maintenance ID"
    email_window: str = "Window"
    email_window_separator: str = "to"
    email_impact: str = "Impact"
    email_status: str = "Status"
    email_status_unspecified: str = "UNSPECIFIED"
    email_objects: str = "Objects"


class Impact(str, Enum):
    """Standard ``X-MAINTNOTE-IMPACT`` values (Section 2.5.5, Table 3)."""

    NO_IMPACT = "NO-IMPACT"
    REDUCED_REDUNDANCY = "REDUCED-REDUNDANCY"
    DEGRADED = "DEGRADED"
    OUTAGE = "OUTAGE"

    @property
    def severity(self) -> int:
        """Numeric severity ranking (0 = NO-IMPACT .. 3 = OUTAGE)."""
        return _IMPACT_SEVERITY[self]

    @classmethod
    def worst(cls, *impacts: Impact | ImpactValue) -> Impact:
        """Return the highest-severity effective impact among *impacts*."""
        if not impacts:
            return cls.OUTAGE
        resolved = [imp.effective if isinstance(imp, ImpactValue) else imp for imp in impacts]
        return max(resolved, key=lambda item: item.severity)


_IMPACT_SEVERITY: dict[Impact, int] = {
    Impact.NO_IMPACT: 0,
    Impact.REDUCED_REDUNDANCY: 1,
    Impact.DEGRADED: 2,
    Impact.OUTAGE: 3,
}


@dataclass(frozen=True, slots=True)
class ImpactValue:
    """Represents ``X-MAINTNOTE-IMPACT`` including standard and custom extensions.

    Per Section 2.5.5:
    "The default value is ``OUTAGE``; applications SHOULD treat ``x-name`` and
    ``iana-token`` values they don't recognize the same way as they would the
    ``OUTAGE`` value."
    """

    raw: str
    params: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        cleaned = self.raw.strip()
        if not cleaned:
            raise ValidationError("X-MAINTNOTE-IMPACT value must not be empty")
        normalized_upper = cleaned.upper()
        # Canonicalize standard values to uppercase; keep custom extensions as provided
        if normalized_upper in _STANDARD_IMPACTS:
            object.__setattr__(self, "raw", normalized_upper)
        else:
            if not (is_valid_x_name(cleaned) or is_valid_iana_token(cleaned)):
                raise ValidationError(
                    f"Invalid X-MAINTNOTE-IMPACT value {cleaned!r}; must be a standard value, x-name, or iana-token"
                )
            object.__setattr__(self, "raw", cleaned)
        object.__setattr__(
            self,
            "params",
            {k.upper(): tuple(v) for k, v in self.params.items()},
        )

    @classmethod
    def from_impact(
        cls,
        impact: Impact | ImpactValue | str,
        *,
        params: dict[str, tuple[str, ...]] | None = None,
    ) -> ImpactValue:
        """Coerce an :class:`Impact`, string, or :class:`ImpactValue` into :class:`ImpactValue`."""
        if isinstance(impact, ImpactValue):
            if params:
                merged = dict(impact.params)
                merged.update({k.upper(): tuple(v) for k, v in params.items()})
                return ImpactValue(raw=impact.raw, params=merged)
            return impact
        raw = impact.value if isinstance(impact, Impact) else impact
        return cls(raw=raw, params=params or {})

    @property
    def standard(self) -> Impact | None:
        """Return the matching :class:`Impact` enum member, or ``None`` if custom."""
        return _STANDARD_IMPACTS.get(self.raw.upper())

    @property
    def is_standard(self) -> bool:
        """Return True if this value is one of the four standard impact labels."""
        return self.standard is not None

    @property
    def effective(self) -> Impact:
        """Effective impact per Section 2.5.5 (unknown values default to ``OUTAGE``)."""
        return self.standard if self.standard is not None else Impact.OUTAGE

    @property
    def severity(self) -> int:
        """Severity score based on :attr:`effective` impact."""
        return self.effective.severity

    def __str__(self) -> str:
        return self.raw


_STANDARD_IMPACTS: dict[str, Impact] = {member.value: member for member in Impact}


class Status(str, Enum):
    """Standard ``X-MAINTNOTE-STATUS`` values (Section 2.5.6, Table 4)."""

    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    IN_PROCESS = "IN-PROCESS"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class StatusValue:
    """Represents ``X-MAINTNOTE-STATUS`` including standard and custom extensions."""

    raw: str
    params: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        cleaned = self.raw.strip()
        if not cleaned:
            raise ValidationError("X-MAINTNOTE-STATUS value must not be empty")
        normalized_upper = cleaned.upper()
        if normalized_upper in _STANDARD_STATUSES:
            object.__setattr__(self, "raw", normalized_upper)
        else:
            if not (is_valid_x_name(cleaned) or is_valid_iana_token(cleaned)):
                raise ValidationError(
                    f"Invalid X-MAINTNOTE-STATUS value {cleaned!r}; must be a standard value, x-name, or iana-token"
                )
            object.__setattr__(self, "raw", cleaned)
        object.__setattr__(
            self,
            "params",
            {k.upper(): tuple(v) for k, v in self.params.items()},
        )

    @classmethod
    def from_status(
        cls,
        status: Status | StatusValue | str,
        *,
        params: dict[str, tuple[str, ...]] | None = None,
    ) -> StatusValue:
        """Coerce a :class:`Status`, string, or :class:`StatusValue` into :class:`StatusValue`."""
        if isinstance(status, StatusValue):
            if params:
                merged = dict(status.params)
                merged.update({k.upper(): tuple(v) for k, v in params.items()})
                return StatusValue(raw=status.raw, params=merged)
            return status
        raw = status.value if isinstance(status, Status) else status
        return cls(raw=raw, params=params or {})

    @property
    def standard(self) -> Status | None:
        """Return the matching :class:`Status` enum member, or ``None`` if custom."""
        return _STANDARD_STATUSES.get(self.raw.upper())

    @property
    def is_standard(self) -> bool:
        """Return True if this value is one of the five standard status labels."""
        return self.standard is not None

    def __str__(self) -> str:
        return self.raw


_STANDARD_STATUSES: dict[str, Status] = {member.value: member for member in Status}


@dataclass(frozen=True, slots=True)
class Organizer:
    """Represents the iCalendar ``ORGANIZER`` property (RFC 5545 Section 3.8.4.3)."""

    address: str
    cn: str | None = None
    params: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        addr = self.address.strip()
        if not addr:
            raise ValidationError("ORGANIZER address must not be empty")
        # Normalize bare email addresses to mailto: URI per RFC 5545 CAL-ADDRESS
        if ":" not in addr and "@" in addr:
            addr = f"mailto:{addr}"
        object.__setattr__(self, "address", addr)
        cleaned_params = {k.upper(): tuple(v) for k, v in self.params.items() if k.upper() != "CN"}
        object.__setattr__(self, "params", cleaned_params)

    @property
    def email(self) -> str:
        """Return the email address without the ``mailto:`` scheme if present."""
        if self.address.lower().startswith("mailto:"):
            return self.address[7:]
        return self.address


@dataclass(frozen=True, slots=True)
class ServiceObject:
    """Represents a single ``X-MAINTNOTE-OBJECT-ID`` property (Section 2.5.4).

    Supports the optional ``ALTREP`` URI parameter (RFC 5545 Section 3.2.1) for
    linking external structured metadata (e.g., JSON or PeeringDB API endpoints),
    plus ``LANGUAGE`` and arbitrary IANA/non-standard property parameters.
    """

    object_id: str
    altrep: str | None = None
    language: str | None = None
    params: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.object_id or not self.object_id.strip():
            raise ValidationError("X-MAINTNOTE-OBJECT-ID value must not be empty")
        cleaned_params = {
            k.upper(): tuple(v)
            for k, v in self.params.items()
            if k.upper() not in ("ALTREP", "LANGUAGE")
        }
        object.__setattr__(self, "params", cleaned_params)

    def scoped_id(self, provider: str) -> tuple[str, str]:
        """Return ``(provider, object_id)`` composite key per Section 2.5.4.

        Consumers SHOULD combine the provider and object identifier to prevent
        namespace collisions across independent service providers.
        """
        return (provider, self.object_id)

    def all_params(self) -> dict[str, tuple[str, ...]]:
        """Return all RFC 5545 parameters for serialization."""
        out: dict[str, tuple[str, ...]] = {}
        if self.altrep is not None:
            out["ALTREP"] = (self.altrep,)
        if self.language is not None:
            out["LANGUAGE"] = (self.language,)
        out.update(self.params)
        return out


@dataclass(frozen=True, slots=True)
class MaintenanceNotification:
    """A complete maintenance notification conforming to draft-gunter-calext-maintenance-notifications-00.

    Represents both the enclosing ``VCALENDAR`` metadata (``version``, ``prodid``,
    optional ``method``) and the mandatory/optional ``VEVENT`` properties.
    """

    # Mandatory VEVENT RFC 5545 properties (Section 2.4, Table 2)
    uid: str
    sequence: int
    dtstamp: datetime
    dtstart: datetime
    dtend: datetime
    summary: str
    organizer: Organizer

    # Mandatory X-MAINTNOTE-* properties (Section 2.5)
    provider: str
    account: str
    maintenance_id: str
    objects: tuple[ServiceObject, ...]
    impact: ImpactValue

    # Optional X-MAINTNOTE-STATUS property (Section 2.5.6: 0 or 1)
    status: StatusValue | None = None

    # Enclosing VCALENDAR properties (Section 2.3, Table 1)
    version: str = ICAL_VERSION
    prodid: str = DEFAULT_PRODID
    method: str | None = None

    # Common optional RFC 5545 VEVENT properties
    description: str | None = None
    location: str | None = None
    url: str | None = None

    # Optional property parameters (e.g., LANGUAGE per Section 5.1, IANA/x-params)
    summary_params: dict[str, tuple[str, ...]] = field(default_factory=dict)
    description_params: dict[str, tuple[str, ...]] = field(default_factory=dict)
    location_params: dict[str, tuple[str, ...]] = field(default_factory=dict)
    url_params: dict[str, tuple[str, ...]] = field(default_factory=dict)
    provider_params: dict[str, tuple[str, ...]] = field(default_factory=dict)
    account_params: dict[str, tuple[str, ...]] = field(default_factory=dict)
    maintenance_id_params: dict[str, tuple[str, ...]] = field(default_factory=dict)

    # Extra RFC 5545 properties and subcomponents preserved across round-trips (Section 2.4)
    extra_calendar_properties: tuple[ContentLine, ...] = ()
    extra_event_properties: tuple[ContentLine, ...] = ()
    extra_calendar_subcomponents: tuple[ICalComponent, ...] = ()
    extra_event_subcomponents: tuple[ICalComponent, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        uid: str,
        dtstart: datetime,
        dtend: datetime,
        summary: str,
        organizer: Organizer | str,
        provider: str,
        account: str,
        maintenance_id: str,
        objects: list[ServiceObject | str] | tuple[ServiceObject | str, ...],
        impact: Impact | ImpactValue | str,
        status: Status | StatusValue | str | None = Status.TENTATIVE,
        sequence: int = 0,
        dtstamp: datetime | None = None,
        prodid: str = DEFAULT_PRODID,
        method: str | None = None,
        description: str | None = None,
        location: str | None = None,
        url: str | None = None,
        language: str | None = None,
        extra_calendar_properties: tuple[ContentLine, ...] = (),
        extra_event_properties: tuple[ContentLine, ...] = (),
        extra_calendar_subcomponents: tuple[ICalComponent, ...] = (),
        extra_event_subcomponents: tuple[ICalComponent, ...] = (),
    ) -> MaintenanceNotification:
        """Ergonomic factory with automatic coercion of enums, strings, and UTC timestamps."""
        org = organizer if isinstance(organizer, Organizer) else Organizer(address=organizer)
        svc_objects = tuple(
            obj if isinstance(obj, ServiceObject) else ServiceObject(object_id=obj)
            for obj in objects
        )
        imp = ImpactValue.from_impact(impact)
        st = StatusValue.from_status(status) if status is not None else None
        stamp = dtstamp if dtstamp is not None else datetime.now(timezone.utc)

        lang_params: dict[str, tuple[str, ...]] = {"LANGUAGE": (language,)} if language else {}

        return cls(
            uid=uid,
            sequence=sequence,
            dtstamp=stamp,
            dtstart=dtstart,
            dtend=dtend,
            summary=summary,
            organizer=org,
            provider=provider,
            account=account,
            maintenance_id=maintenance_id,
            objects=svc_objects,
            impact=imp,
            status=st,
            prodid=prodid,
            method=method,
            description=description,
            location=location,
            url=url,
            summary_params=dict(lang_params),
            description_params=dict(lang_params) if description is not None else {},
            extra_calendar_properties=extra_calendar_properties,
            extra_event_properties=extra_event_properties,
            extra_calendar_subcomponents=extra_calendar_subcomponents,
            extra_event_subcomponents=extra_event_subcomponents,
        )

    @property
    def duration(self) -> timedelta:
        """Duration of the maintenance window (``dtend - dtstart``)."""
        return self.dtend - self.dtstart

    @property
    def effective_impact(self) -> Impact:
        """Effective impact level, defaulting unrecognized custom values to ``OUTAGE``."""
        return self.impact.effective

    @property
    def standard_status(self) -> Status | None:
        """Standard :class:`Status` if set and recognized, otherwise ``None``."""
        return self.status.standard if self.status is not None else None

    @property
    def is_tentative(self) -> bool:
        return self.standard_status is Status.TENTATIVE

    @property
    def is_confirmed(self) -> bool:
        return self.standard_status is Status.CONFIRMED

    @property
    def is_cancelled(self) -> bool:
        return self.standard_status is Status.CANCELLED

    @property
    def is_open(self) -> bool:
        return self.standard_status is Status.IN_PROCESS

    @property
    def is_closed(self) -> bool:
        return self.standard_status is Status.COMPLETED

    @property
    def object_ids(self) -> tuple[str, ...]:
        """Tuple of raw service object identifier strings."""
        return tuple(obj.object_id for obj in self.objects)

    @property
    def scoped_object_ids(self) -> tuple[tuple[str, str], ...]:
        """Tuple of ``(provider, object_id)`` keys per Section 2.5.4."""
        return tuple(obj.scoped_id(self.provider) for obj in self.objects)

    def with_updates(self, **changes: Any) -> MaintenanceNotification:
        """Return a new :class:`MaintenanceNotification` with selected fields replaced."""
        if "impact" in changes and not isinstance(changes["impact"], ImpactValue):
            changes["impact"] = ImpactValue.from_impact(changes["impact"])
        if (
            "status" in changes
            and changes["status"] is not None
            and not isinstance(changes["status"], StatusValue)
        ):
            changes["status"] = StatusValue.from_status(changes["status"])
        if "organizer" in changes and isinstance(changes["organizer"], str):
            changes["organizer"] = Organizer(address=changes["organizer"])
        if "objects" in changes:
            changes["objects"] = tuple(
                obj if isinstance(obj, ServiceObject) else ServiceObject(object_id=obj)
                for obj in changes["objects"]
            )
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dictionary representation."""
        return {
            "version": self.version,
            "prodid": self.prodid,
            "method": self.method,
            "uid": self.uid,
            "sequence": self.sequence,
            "dtstamp": self.dtstamp.isoformat(),
            "dtstart": self.dtstart.isoformat(),
            "dtend": self.dtend.isoformat(),
            "summary": self.summary,
            "description": self.description,
            "location": self.location,
            "url": self.url,
            "organizer": {
                "address": self.organizer.address,
                "cn": self.organizer.cn,
            },
            "provider": self.provider,
            "account": self.account,
            "maintenance_id": self.maintenance_id,
            "objects": [
                {
                    "object_id": obj.object_id,
                    "altrep": obj.altrep,
                    "language": obj.language,
                }
                for obj in self.objects
            ],
            "impact": self.impact.raw,
            "effective_impact": self.effective_impact.value,
            "status": self.status.raw if self.status is not None else None,
        }


@dataclass(frozen=True, slots=True)
class CalendarDocument:
    """Represents a ``VCALENDAR`` containing one or more maintenance notifications.

    Useful for CalDAV feeds (RFC 4791) or multi-event ``.ics`` exports.
    """

    notifications: tuple[MaintenanceNotification, ...]
    version: str = ICAL_VERSION
    prodid: str = DEFAULT_PRODID
    method: str | None = None
    extra_calendar_properties: tuple[ContentLine, ...] = ()
    extra_calendar_subcomponents: tuple[ICalComponent, ...] = ()
