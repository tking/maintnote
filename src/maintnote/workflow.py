"""Provider and consumer workflow engine for draft-gunter-calext-maintenance-notifications-00.

Implements all five lifecycle workflows defined in Section 3:
- 3.1 Initial Maintenance Notification
- 3.2 Updated Maintenance Notification Window
- 3.3 Canceled Maintenance Notification Window
- 3.4 Open Maintenance Notification Window (IN-PROCESS)
- 3.5 Closed Maintenance Notification Window (COMPLETED)
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from maintnote.exceptions import VerificationError, WorkflowError
from maintnote.models import (
    DEFAULT_PRODID,
    Impact,
    ImpactValue,
    MaintenanceNotification,
    Organizer,
    ServiceObject,
    Status,
    StatusValue,
)
from maintnote.parser import parse
from maintnote.serializer import dumps

_TERMINAL_STATUSES: frozenset[Status] = frozenset({Status.CANCELLED, Status.COMPLETED})


class WorkflowAction(str, Enum):
    """Action taken by a consumer when processing a maintenance notification."""

    INITIAL = "INITIAL"
    UPDATED = "UPDATED"
    CANCELLED = "CANCELLED"
    OPENED = "OPENED"
    CLOSED = "CLOSED"
    IGNORED_DUPLICATE = "IGNORED_DUPLICATE"
    IGNORED_STALE = "IGNORED_STALE"


class TicketPriority(str, Enum):
    """Suggested operational ticket priority derived from effective impact."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @classmethod
    def from_impact(cls, impact: Impact | ImpactValue) -> TicketPriority:
        """Map an impact (using Section 2.5.5 OUTAGE fallback) to ticket priority."""
        effective = impact.effective if isinstance(impact, ImpactValue) else impact
        mapping: dict[Impact, TicketPriority] = {
            Impact.NO_IMPACT: cls.LOW,
            Impact.REDUCED_REDUNDANCY: cls.NORMAL,
            Impact.DEGRADED: cls.HIGH,
            Impact.OUTAGE: cls.CRITICAL,
        }
        return mapping[effective]


@dataclass(frozen=True, slots=True)
class RecipientPreference:
    """Per-recipient delivery settings, notably Section 2.3.1 ``METHOD`` control."""

    include_method: bool = False
    method: str = "PUBLISH"
    cancel_method: str = "CANCEL"


@dataclass(frozen=True, slots=True)
class NotificationDiff:
    """Summary of field differences between consecutive notifications for a UID."""

    window_changed: bool = False
    status_changed: bool = False
    impact_changed: bool = False
    objects_changed: bool = False
    summary_changed: bool = False
    description_changed: bool = False
    previous_status: str | None = None
    current_status: str | None = None

    @property
    def changed_fields(self) -> tuple[str, ...]:
        """Return tuple of logical field names that changed."""
        changed: list[str] = []
        if self.window_changed:
            changed.append("window")
        if self.status_changed:
            changed.append("status")
        if self.impact_changed:
            changed.append("impact")
        if self.objects_changed:
            changed.append("objects")
        if self.summary_changed:
            changed.append("summary")
        if self.description_changed:
            changed.append("description")
        return tuple(changed)

    @property
    def has_changes(self) -> bool:
        return bool(self.changed_fields)


def compute_diff(
    previous: MaintenanceNotification, current: MaintenanceNotification
) -> NotificationDiff:
    """Compute a structured :class:`NotificationDiff` between two notifications."""
    prev_status = previous.status.raw if previous.status is not None else None
    curr_status = current.status.raw if current.status is not None else None
    return NotificationDiff(
        window_changed=(previous.dtstart != current.dtstart or previous.dtend != current.dtend),
        status_changed=(prev_status != curr_status),
        impact_changed=(previous.impact.raw != current.impact.raw),
        objects_changed=(previous.object_ids != current.object_ids),
        summary_changed=(previous.summary != current.summary),
        description_changed=(previous.description != current.description),
        previous_status=prev_status,
        current_status=curr_status,
    )


class MaintenanceProvider:
    """Provider-side workflow generator implementing Section 3.1.1-3.5.1."""

    def __init__(
        self,
        *,
        provider: str,
        organizer: Organizer | str,
        prodid: str = DEFAULT_PRODID,
        recipient_preferences: Mapping[str, RecipientPreference] | None = None,
    ) -> None:
        self.provider = provider
        self.organizer = (
            organizer if isinstance(organizer, Organizer) else Organizer(address=organizer)
        )
        self.prodid = prodid
        self._recipient_preferences: dict[str, RecipientPreference] = dict(
            recipient_preferences or {}
        )

    def set_recipient_preference(self, account: str, preference: RecipientPreference) -> None:
        """Configure per-account ``METHOD`` preference (Section 2.3.1)."""
        self._recipient_preferences[account] = preference

    def get_recipient_preference(self, account: str) -> RecipientPreference:
        """Return the ``METHOD`` preference for *account* (defaults to omitting METHOD)."""
        return self._recipient_preferences.get(account, RecipientPreference())

    def _resolve_method_for_account(self, account: str, *, is_cancel: bool = False) -> str | None:
        pref = self.get_recipient_preference(account)
        if not pref.include_method:
            return None
        return pref.cancel_method if is_cancel else pref.method

    def create_initial(
        self,
        *,
        account: str,
        maintenance_id: str,
        objects: Sequence[ServiceObject | str],
        dtstart: datetime,
        dtend: datetime,
        summary: str,
        impact: Impact | ImpactValue | str,
        status: Status | StatusValue | str | None = Status.TENTATIVE,
        uid: str | None = None,
        initial_sequence: int = 0,
        dtstamp: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
        url: str | None = None,
        language: str | None = None,
    ) -> MaintenanceNotification:
        """Create an initial maintenance notification (Section 3.1.1)."""
        resolved_uid = uid if uid is not None else f"{uuid.uuid4()}@{self.provider}"
        method = self._resolve_method_for_account(account, is_cancel=False)
        return MaintenanceNotification.create(
            uid=resolved_uid,
            sequence=initial_sequence,
            dtstamp=dtstamp or datetime.now(timezone.utc),
            dtstart=dtstart,
            dtend=dtend,
            summary=summary,
            organizer=self.organizer,
            provider=self.provider,
            account=account,
            maintenance_id=maintenance_id,
            objects=list(objects),
            impact=impact,
            status=status,
            prodid=self.prodid,
            method=method,
            description=description,
            location=location,
            url=url,
            language=language,
        )

    def create_batch_initial(
        self,
        *,
        maintenance_id: str,
        affected_accounts: Mapping[str, Sequence[ServiceObject | str]],
        dtstart: datetime,
        dtend: datetime,
        summary: str,
        impact: Impact | ImpactValue | str,
        status: Status | StatusValue | str | None = Status.TENTATIVE,
        initial_sequence: int = 0,
        dtstamp: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
        url: str | None = None,
        language: str | None = None,
    ) -> dict[str, MaintenanceNotification]:
        """Generate per-consumer notifications for all accounts impacted by one maintenance."""
        stamp = dtstamp or datetime.now(timezone.utc)
        notifications: dict[str, MaintenanceNotification] = {}
        for account, objects in affected_accounts.items():
            notifications[account] = self.create_initial(
                account=account,
                maintenance_id=maintenance_id,
                objects=objects,
                dtstart=dtstart,
                dtend=dtend,
                summary=summary,
                impact=impact,
                status=status,
                initial_sequence=initial_sequence,
                dtstamp=stamp,
                description=description,
                location=location,
                url=url,
                language=language,
            )
        return notifications

    def update_window(
        self,
        previous: MaintenanceNotification,
        *,
        dtstart: datetime | None = None,
        dtend: datetime | None = None,
        summary: str | None = None,
        description: str | None = None,
        impact: Impact | ImpactValue | str | None = None,
        status: Status | StatusValue | str | None = None,
        objects: Sequence[ServiceObject | str] | None = None,
        dtstamp: datetime | None = None,
        allow_from_terminal: bool = False,
    ) -> MaintenanceNotification:
        """Create an updated notification preserving UID and incrementing SEQUENCE (Section 3.2.1)."""
        self._guard_terminal(previous, allow_from_terminal=allow_from_terminal, action="update")
        updates: dict[str, object] = {
            "sequence": previous.sequence + 1,
            "dtstamp": dtstamp or datetime.now(timezone.utc),
            "method": self._resolve_method_for_account(previous.account, is_cancel=False),
        }
        if dtstart is not None:
            updates["dtstart"] = dtstart
        if dtend is not None:
            updates["dtend"] = dtend
        if summary is not None:
            updates["summary"] = summary
        if description is not None:
            updates["description"] = description
        if impact is not None:
            updates["impact"] = impact
        if status is not None:
            updates["status"] = status
        if objects is not None:
            updates["objects"] = list(objects)
        return previous.with_updates(**updates)

    def confirm(
        self,
        previous: MaintenanceNotification,
        *,
        dtstart: datetime | None = None,
        dtend: datetime | None = None,
        summary: str | None = None,
        description: str | None = None,
        dtstamp: datetime | None = None,
    ) -> MaintenanceNotification:
        """Confirm a tentative or updated maintenance window (Example 4.2)."""
        return self.update_window(
            previous,
            dtstart=dtstart,
            dtend=dtend,
            summary=summary,
            description=description,
            status=Status.CONFIRMED,
            dtstamp=dtstamp,
        )

    def cancel(
        self,
        previous: MaintenanceNotification,
        *,
        summary: str | None = None,
        description: str | None = None,
        dtstamp: datetime | None = None,
        allow_from_terminal: bool = False,
    ) -> MaintenanceNotification:
        """Cancel a previously announced maintenance window (Section 3.3.1)."""
        self._guard_terminal(previous, allow_from_terminal=allow_from_terminal, action="cancel")
        updates: dict[str, object] = {
            "sequence": previous.sequence + 1,
            "dtstamp": dtstamp or datetime.now(timezone.utc),
            "status": Status.CANCELLED,
            "method": self._resolve_method_for_account(previous.account, is_cancel=True),
        }
        if summary is not None:
            updates["summary"] = summary
        if description is not None:
            updates["description"] = description
        return previous.with_updates(**updates)

    def open_window(
        self,
        previous: MaintenanceNotification,
        *,
        summary: str | None = None,
        description: str | None = None,
        dtstamp: datetime | None = None,
        allow_from_terminal: bool = False,
    ) -> MaintenanceNotification:
        """Declare a scheduled maintenance window open / ``IN-PROCESS`` (Section 3.4.1)."""
        self._guard_terminal(previous, allow_from_terminal=allow_from_terminal, action="open")
        resolved_summary = summary
        if resolved_summary is None and not previous.summary.startswith("Open - "):
            resolved_summary = f"Open - {previous.summary}"
        updates: dict[str, object] = {
            "sequence": previous.sequence + 1,
            "dtstamp": dtstamp or datetime.now(timezone.utc),
            "status": Status.IN_PROCESS,
            "method": self._resolve_method_for_account(previous.account, is_cancel=False),
        }
        if resolved_summary is not None:
            updates["summary"] = resolved_summary
        if description is not None:
            updates["description"] = description
        return previous.with_updates(**updates)

    def close_window(
        self,
        previous: MaintenanceNotification,
        *,
        summary: str | None = None,
        description: str | None = None,
        dtstamp: datetime | None = None,
        allow_from_terminal: bool = False,
    ) -> MaintenanceNotification:
        """Declare a maintenance window closed / ``COMPLETED`` (Section 3.5.1)."""
        self._guard_terminal(previous, allow_from_terminal=allow_from_terminal, action="close")
        resolved_summary = summary
        if resolved_summary is None:
            base = previous.summary
            if base.startswith("Open - "):
                base = base[len("Open - ") :]
            resolved_summary = base if base.startswith("Closed - ") else f"Closed - {base}"
        updates: dict[str, object] = {
            "sequence": previous.sequence + 1,
            "dtstamp": dtstamp or datetime.now(timezone.utc),
            "status": Status.COMPLETED,
            "method": self._resolve_method_for_account(previous.account, is_cancel=False),
        }
        if resolved_summary is not None:
            updates["summary"] = resolved_summary
        if description is not None:
            updates["description"] = description
        return previous.with_updates(**updates)

    @staticmethod
    def _guard_terminal(
        previous: MaintenanceNotification, *, allow_from_terminal: bool, action: str
    ) -> None:
        if allow_from_terminal:
            return
        if previous.standard_status in _TERMINAL_STATUSES:
            raise WorkflowError(
                f"Cannot {action} maintenance UID={previous.uid!r} from terminal status "
                f"{previous.standard_status.value}"
            )


@dataclass(frozen=True, slots=True)
class TrackedMaintenance:
    """State persisted by a consumer for a maintenance notification UID."""

    uid: str
    provider: str
    maintenance_id: str
    account: str
    sequence: int
    ticket_id: str
    notification: MaintenanceNotification
    updated_at: datetime


@runtime_checkable
class StateStore(Protocol):
    """Persistence interface for consumer-side UID & SEQUENCE tracking."""

    def get(self, uid: str) -> TrackedMaintenance | None:
        """Retrieve tracked state for *uid*, or ``None`` if unseen."""

    def save(self, record: TrackedMaintenance) -> None:
        """Persist or update tracked state for ``record.uid``."""

    def list_by_scoped_object(self, provider: str, object_id: str) -> list[TrackedMaintenance]:
        """List all tracked maintenances affecting ``(provider, object_id)``."""

    def list_all(self) -> list[TrackedMaintenance]:
        """Return all tracked maintenance records."""


class InMemoryStateStore:
    """In-memory :class:`StateStore` implementation suitable for tests and ephemeral workers."""

    def __init__(self) -> None:
        self._records: dict[str, TrackedMaintenance] = {}

    def get(self, uid: str) -> TrackedMaintenance | None:
        return self._records.get(uid)

    def save(self, record: TrackedMaintenance) -> None:
        self._records[record.uid] = record

    def list_by_scoped_object(self, provider: str, object_id: str) -> list[TrackedMaintenance]:
        target = (provider, object_id)
        return [
            rec for rec in self._records.values() if target in rec.notification.scoped_object_ids
        ]

    def list_all(self) -> list[TrackedMaintenance]:
        return list(self._records.values())


class SQLiteStateStore:
    """Persistent SQLite-backed :class:`StateStore` using Python's stdlib ``sqlite3``."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS maintenance_state (
                uid TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                maintenance_id TEXT NOT NULL,
                account TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                ticket_id TEXT NOT NULL,
                scoped_objects_json TEXT NOT NULL,
                raw_ical TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def get(self, uid: str) -> TrackedMaintenance | None:
        row = self._conn.execute(
            """
            SELECT uid, provider, maintenance_id, account, sequence, ticket_id, raw_ical, updated_at
            FROM maintenance_state WHERE uid = ?
            """,
            (uid,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def save(self, record: TrackedMaintenance) -> None:
        raw_ical = dumps(record.notification, validate_before_dump=False)
        scoped_json = json.dumps(list(record.notification.scoped_object_ids))
        self._conn.execute(
            """
            INSERT INTO maintenance_state (
                uid, provider, maintenance_id, account, sequence,
                ticket_id, scoped_objects_json, raw_ical, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid) DO UPDATE SET
                provider = excluded.provider,
                maintenance_id = excluded.maintenance_id,
                account = excluded.account,
                sequence = excluded.sequence,
                ticket_id = excluded.ticket_id,
                scoped_objects_json = excluded.scoped_objects_json,
                raw_ical = excluded.raw_ical,
                updated_at = excluded.updated_at
            """,
            (
                record.uid,
                record.provider,
                record.maintenance_id,
                record.account,
                record.sequence,
                record.ticket_id,
                scoped_json,
                raw_ical,
                record.updated_at.isoformat(),
            ),
        )
        self._conn.commit()

    def list_by_scoped_object(self, provider: str, object_id: str) -> list[TrackedMaintenance]:
        rows = self._conn.execute(
            """
            SELECT uid, provider, maintenance_id, account, sequence, ticket_id, raw_ical, updated_at
            FROM maintenance_state WHERE provider = ?
            """,
            (provider,),
        ).fetchall()
        target = (provider, object_id)
        results: list[TrackedMaintenance] = []
        for row in rows:
            rec = self._row_to_record(row)
            if target in rec.notification.scoped_object_ids:
                results.append(rec)
        return results

    def list_all(self) -> list[TrackedMaintenance]:
        rows = self._conn.execute(
            """
            SELECT uid, provider, maintenance_id, account, sequence, ticket_id, raw_ical, updated_at
            FROM maintenance_state
            """
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row: tuple[str, str, str, str, int, str, str, str]) -> TrackedMaintenance:
        uid, provider, maintenance_id, account, sequence, ticket_id, raw_ical, updated_at = row
        notif = parse(raw_ical, strict=False)
        return TrackedMaintenance(
            uid=uid,
            provider=provider,
            maintenance_id=maintenance_id,
            account=account,
            sequence=sequence,
            ticket_id=ticket_id,
            notification=notif,
            updated_at=datetime.fromisoformat(updated_at),
        )


@runtime_checkable
class TicketHandler(Protocol):
    """Consumer-side ticketing / automation hook implementing Section 3.1.2-3.5.2."""

    def create_ticket(
        self,
        notification: MaintenanceNotification,
        *,
        priority: TicketPriority,
        assign_to_remediation_queue: bool,
    ) -> str:
        """Open a new ticket for an initial maintenance notification and return its ID."""

    def update_ticket(
        self,
        ticket_id: str,
        notification: MaintenanceNotification,
        diff: NotificationDiff,
        *,
        priority: TicketPriority,
        assign_to_remediation_queue: bool,
    ) -> None:
        """Update an existing ticket with modified window/impact/status details."""

    def cancel_ticket(
        self,
        ticket_id: str,
        notification: MaintenanceNotification,
        diff: NotificationDiff,
    ) -> None:
        """Cancel the ticket corresponding to a ``CANCELLED`` notification."""

    def open_ticket(
        self,
        ticket_id: str,
        notification: MaintenanceNotification,
        diff: NotificationDiff,
    ) -> None:
        """Mark the ticket as open / active when status becomes ``IN-PROCESS``."""

    def close_ticket(
        self,
        ticket_id: str,
        notification: MaintenanceNotification,
        diff: NotificationDiff,
    ) -> None:
        """Mark the ticket as closed when status becomes ``COMPLETED``."""


@dataclass(slots=True)
class TicketRecord:
    """In-memory ticket representation used by :class:`InMemoryTicketHandler`."""

    ticket_id: str
    uid: str
    provider: str
    maintenance_id: str
    summary: str
    description: str | None
    dtstart: datetime
    dtend: datetime
    priority: TicketPriority
    assigned_to_remediation_queue: bool
    state: str
    scoped_objects: tuple[tuple[str, str], ...]
    history: list[str] = field(default_factory=list)


class InMemoryTicketHandler:
    """Reference :class:`TicketHandler` implementing Section 3.1.2-3.5.2 semantics."""

    def __init__(self, *, prefix: str = "MAINT") -> None:
        self._prefix = prefix
        self._counter = 0
        self.tickets: dict[str, TicketRecord] = {}

    def create_ticket(
        self,
        notification: MaintenanceNotification,
        *,
        priority: TicketPriority,
        assign_to_remediation_queue: bool,
    ) -> str:
        self._counter += 1
        ticket_id = f"{self._prefix}-{self._counter:04d}"
        self.tickets[ticket_id] = TicketRecord(
            ticket_id=ticket_id,
            uid=notification.uid,
            provider=notification.provider,
            maintenance_id=notification.maintenance_id,
            summary=notification.summary,
            description=notification.description,
            dtstart=notification.dtstart,
            dtend=notification.dtend,
            priority=priority,
            assigned_to_remediation_queue=assign_to_remediation_queue,
            state="NEW",
            scoped_objects=notification.scoped_object_ids,
            history=[f"created(seq={notification.sequence}, priority={priority.value})"],
        )
        return ticket_id

    def update_ticket(
        self,
        ticket_id: str,
        notification: MaintenanceNotification,
        diff: NotificationDiff,
        *,
        priority: TicketPriority,
        assign_to_remediation_queue: bool,
    ) -> None:
        ticket = self.tickets[ticket_id]
        ticket.summary = notification.summary
        ticket.description = notification.description
        ticket.dtstart = notification.dtstart
        ticket.dtend = notification.dtend
        ticket.priority = priority
        ticket.assigned_to_remediation_queue = assign_to_remediation_queue
        ticket.scoped_objects = notification.scoped_object_ids
        ticket.history.append(
            f"updated(seq={notification.sequence}, fields={','.join(diff.changed_fields)})"
        )

    def cancel_ticket(
        self,
        ticket_id: str,
        notification: MaintenanceNotification,
        diff: NotificationDiff,
    ) -> None:
        ticket = self.tickets[ticket_id]
        ticket.state = "CANCELLED"
        ticket.summary = notification.summary
        ticket.description = notification.description
        ticket.assigned_to_remediation_queue = False
        ticket.history.append(
            f"cancelled(seq={notification.sequence}, fields={','.join(diff.changed_fields)})"
        )

    def open_ticket(
        self,
        ticket_id: str,
        notification: MaintenanceNotification,
        diff: NotificationDiff,
    ) -> None:
        ticket = self.tickets[ticket_id]
        ticket.state = "OPEN"
        ticket.summary = notification.summary
        ticket.description = notification.description
        ticket.history.append(
            f"opened(seq={notification.sequence}, fields={','.join(diff.changed_fields)})"
        )

    def close_ticket(
        self,
        ticket_id: str,
        notification: MaintenanceNotification,
        diff: NotificationDiff,
    ) -> None:
        ticket = self.tickets[ticket_id]
        ticket.state = "CLOSED"
        ticket.summary = notification.summary
        ticket.description = notification.description
        ticket.history.append(
            f"closed(seq={notification.sequence}, fields={','.join(diff.changed_fields)})"
        )


@runtime_checkable
class OutOfBandVerifier(Protocol):
    """Optional Section 5.2 verification callback before automated actions run."""

    def verify(self, notification: MaintenanceNotification) -> bool:
        """Return True if *notification* passes out-of-band authenticity/correctness checks."""


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    """Outcome of processing an incoming maintenance notification."""

    action: WorkflowAction
    notification: MaintenanceNotification
    ticket_id: str | None
    priority: TicketPriority
    assign_to_remediation_queue: bool
    diff: NotificationDiff | None = None


class MaintenanceConsumer:
    """Consumer-side workflow processor implementing Section 3.1.2-3.5.2.

    Tracks notifications by ``UID`` and ``SEQUENCE`` in a pluggable :class:`StateStore`,
    guards against out-of-order or duplicate updates, applies Section 2.5.5 ``OUTAGE``
    impact defaults, and dispatches lifecycle transitions to a :class:`TicketHandler`.
    """

    def __init__(
        self,
        *,
        store: StateStore | None = None,
        handler: TicketHandler | None = None,
        verifier: OutOfBandVerifier | None = None,
    ) -> None:
        self.store: StateStore = store if store is not None else InMemoryStateStore()
        self.handler: TicketHandler = handler if handler is not None else InMemoryTicketHandler()
        self.verifier = verifier

    def process(
        self,
        incoming: MaintenanceNotification | str | bytes,
        *,
        strict: bool = True,
    ) -> ProcessingResult:
        """Process a maintenance notification (parsed object or raw iCalendar payload)."""
        notification = (
            incoming
            if isinstance(incoming, MaintenanceNotification)
            else parse(incoming, strict=strict)
        )

        if self.verifier is not None and not self.verifier.verify(notification):
            raise VerificationError(
                f"Out-of-band verification failed for UID={notification.uid!r} "
                f"from provider={notification.provider!r}"
            )

        priority = TicketPriority.from_impact(notification.impact)
        # Per Section 3.1.2: tentative notifications are not assigned to remediation queue
        assign_to_remediation = not notification.is_tentative and not notification.is_cancelled

        existing = self.store.get(notification.uid)
        now = datetime.now(timezone.utc)

        if existing is None:
            ticket_id = self.handler.create_ticket(
                notification,
                priority=priority,
                assign_to_remediation_queue=assign_to_remediation,
            )
            self.store.save(
                TrackedMaintenance(
                    uid=notification.uid,
                    provider=notification.provider,
                    maintenance_id=notification.maintenance_id,
                    account=notification.account,
                    sequence=notification.sequence,
                    ticket_id=ticket_id,
                    notification=notification,
                    updated_at=now,
                )
            )
            return ProcessingResult(
                action=WorkflowAction.INITIAL,
                notification=notification,
                ticket_id=ticket_id,
                priority=priority,
                assign_to_remediation_queue=assign_to_remediation,
                diff=None,
            )

        # Sequence number monotonicity check (Section 3.1.1 / 3.2.2)
        if notification.sequence == existing.sequence:
            return ProcessingResult(
                action=WorkflowAction.IGNORED_DUPLICATE,
                notification=notification,
                ticket_id=existing.ticket_id,
                priority=priority,
                assign_to_remediation_queue=assign_to_remediation,
                diff=None,
            )
        if notification.sequence < existing.sequence:
            return ProcessingResult(
                action=WorkflowAction.IGNORED_STALE,
                notification=notification,
                ticket_id=existing.ticket_id,
                priority=priority,
                assign_to_remediation_queue=assign_to_remediation,
                diff=None,
            )

        diff = compute_diff(existing.notification, notification)
        ticket_id = existing.ticket_id

        if notification.is_cancelled:
            self.handler.cancel_ticket(ticket_id, notification, diff)
            action = WorkflowAction.CANCELLED
        elif notification.is_open:
            self.handler.open_ticket(ticket_id, notification, diff)
            action = WorkflowAction.OPENED
        elif notification.is_closed:
            self.handler.close_ticket(ticket_id, notification, diff)
            action = WorkflowAction.CLOSED
        else:
            self.handler.update_ticket(
                ticket_id,
                notification,
                diff,
                priority=priority,
                assign_to_remediation_queue=assign_to_remediation,
            )
            action = WorkflowAction.UPDATED

        self.store.save(
            TrackedMaintenance(
                uid=notification.uid,
                provider=notification.provider,
                maintenance_id=notification.maintenance_id,
                account=notification.account,
                sequence=notification.sequence,
                ticket_id=ticket_id,
                notification=notification,
                updated_at=now,
            )
        )

        return ProcessingResult(
            action=action,
            notification=notification,
            ticket_id=ticket_id,
            priority=priority,
            assign_to_remediation_queue=assign_to_remediation,
            diff=diff,
        )
