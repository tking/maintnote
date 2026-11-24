"""End-to-end tests for all five Provider and Consumer workflows (Section 3)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from maintnote.exceptions import VerificationError, WorkflowError
from maintnote.models import Impact, MaintenanceNotification, Organizer, ServiceObject, Status
from maintnote.serializer import dumps
from maintnote.workflow import (
    InMemoryStateStore,
    InMemoryTicketHandler,
    MaintenanceConsumer,
    MaintenanceProvider,
    RecipientPreference,
    SQLiteStateStore,
    TicketPriority,
    WorkflowAction,
)


def test_full_lifecycle_initial_update_open_close_with_sqlite(tmp_path: Path) -> None:
    """Exercises Workflows 3.1 (Initial), 3.2 (Updated), 3.4 (Open), and 3.5 (Closed)."""
    provider = MaintenanceProvider(
        provider="transit.example.com",
        organizer=Organizer("noc@transit.example.com", cn="Transit NOC"),
    )
    db_path = tmp_path / "maint_state.db"
    store = SQLiteStateStore(db_path)
    handler = InMemoryTicketHandler(prefix="OPS")
    consumer = MaintenanceConsumer(store=store, handler=handler)

    try:
        # 3.1 Initial notification: OUTAGE + TENTATIVE -> CRITICAL priority, NOT in remediation queue
        n0 = provider.create_initial(
            account="acct-9001",
            maintenance_id="CHG-2026-001",
            objects=[
                ServiceObject(
                    object_id="xe-0/0/1.sjc1",
                    altrep="https://transit.example.com/api/circuits/xe-0-0-1",
                )
            ],
            dtstart=datetime(2026, 9, 1, 2, 0, tzinfo=timezone.utc),
            dtend=datetime(2026, 9, 1, 4, 0, tzinfo=timezone.utc),
            summary="Optical transponder replacement",
            impact=Impact.OUTAGE,
            status=Status.TENTATIVE,
        )
        assert n0.sequence == 0
        assert n0.method is None

        res0 = consumer.process(dumps(n0))
        assert res0.action is WorkflowAction.INITIAL
        assert res0.ticket_id == "OPS-0001"
        assert res0.priority is TicketPriority.CRITICAL
        assert res0.assign_to_remediation_queue is False
        assert handler.tickets["OPS-0001"].state == "NEW"

        # Duplicate sequence=0 must be safely ignored
        res_dup = consumer.process(n0)
        assert res_dup.action is WorkflowAction.IGNORED_DUPLICATE
        assert res_dup.ticket_id == "OPS-0001"

        # 3.2 Updated & confirmed maintenance window -> sequence=1, remediation queue enabled
        n1 = provider.confirm(
            n0,
            dtstart=datetime(2026, 9, 2, 3, 0, tzinfo=timezone.utc),
            dtend=datetime(2026, 9, 2, 5, 0, tzinfo=timezone.utc),
        )
        assert n1.uid == n0.uid
        assert n1.sequence == 1
        assert n1.is_confirmed

        res1 = consumer.process(dumps(n1))
        assert res1.action is WorkflowAction.UPDATED
        assert res1.diff is not None
        assert res1.diff.window_changed is True
        assert res1.diff.status_changed is True
        assert res1.assign_to_remediation_queue is True
        assert handler.tickets["OPS-0001"].dtstart == datetime(
            2026, 9, 2, 3, 0, tzinfo=timezone.utc
        )

        # Out-of-order stale notification (sequence=0 arriving after sequence=1) is ignored
        res_stale = consumer.process(n0)
        assert res_stale.action is WorkflowAction.IGNORED_STALE
        assert store.get(n0.uid) is not None
        assert store.get(n0.uid).sequence == 1  # type: ignore[union-attr]

        # 3.4 Open maintenance window -> sequence=2, IN-PROCESS
        n2 = provider.open_window(n1, description="Engineers are now working in the POP.")
        assert n2.sequence == 2
        assert n2.is_open
        assert n2.summary.startswith("Open - ")

        res2 = consumer.process(dumps(n2))
        assert res2.action is WorkflowAction.OPENED
        assert handler.tickets["OPS-0001"].state == "OPEN"
        assert handler.tickets["OPS-0001"].description == "Engineers are now working in the POP."

        # 3.5 Closed maintenance window -> sequence=3, COMPLETED
        n3 = provider.close_window(n2, description="Work complete; optical levels nominal.")
        assert n3.sequence == 3
        assert n3.is_closed
        assert n3.summary == "Closed - Optical transponder replacement"

        res3 = consumer.process(dumps(n3))
        assert res3.action is WorkflowAction.CLOSED
        assert handler.tickets["OPS-0001"].state == "CLOSED"

        # Terminal status guards prevent accidental further transitions
        with pytest.raises(WorkflowError, match="terminal status"):
            provider.update_window(n3, summary="Should fail")

        # Verify SQLite scoped object lookup
        matches = store.list_by_scoped_object("transit.example.com", "xe-0/0/1.sjc1")
        assert len(matches) == 1
        assert matches[0].ticket_id == "OPS-0001"
        assert store.list_by_scoped_object("other-isp.example.net", "xe-0/0/1.sjc1") == []
    finally:
        store.close()


def test_cancel_workflow_and_per_recipient_method_preference() -> None:
    """Exercises Workflow 3.3 (Canceled) and Section 2.3.1 per-recipient METHOD."""
    provider = MaintenanceProvider(
        provider="carrier.example.net",
        organizer="noc@carrier.example.net",
    )
    # Account A opts INTO METHOD; Account B uses default (no METHOD)
    provider.set_recipient_preference(
        "acct-A", RecipientPreference(include_method=True, method="PUBLISH", cancel_method="CANCEL")
    )

    batch = provider.create_batch_initial(
        maintenance_id="WO-555",
        affected_accounts={
            "acct-A": ["ckt-100", "ckt-101"],
            "acct-B": ["ckt-200"],
        },
        dtstart=datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc),
        summary="Fiber splice maintenance",
        impact=Impact.DEGRADED,
    )

    assert batch["acct-A"].method == "PUBLISH"
    assert batch["acct-B"].method is None

    cancelled_a = provider.cancel(batch["acct-A"], description="Rescheduled indefinitely")
    assert cancelled_a.method == "CANCEL"
    assert cancelled_a.is_cancelled
    assert cancelled_a.sequence == 1

    handler = InMemoryTicketHandler()
    consumer = MaintenanceConsumer(store=InMemoryStateStore(), handler=handler)

    r_init = consumer.process(batch["acct-A"])
    assert r_init.action is WorkflowAction.INITIAL
    assert r_init.priority is TicketPriority.HIGH

    r_cancel = consumer.process(cancelled_a)
    assert r_cancel.action is WorkflowAction.CANCELLED
    assert r_cancel.ticket_id == r_init.ticket_id
    assert handler.tickets[r_cancel.ticket_id].state == "CANCELLED"  # type: ignore[index]


def test_consumer_handles_verbatim_draft_examples_branch_and_unknown_impact(
    example_4_1: str,
    example_4_2: str,
    example_4_3: str,
    example_4_4: str,
    example_4_5: str,
) -> None:
    # Branch A: 4.1 -> 4.2 -> 4.3 (Cancelled)
    consumer_a = MaintenanceConsumer()
    assert consumer_a.process(example_4_1).action is WorkflowAction.INITIAL
    assert consumer_a.process(example_4_2).action is WorkflowAction.UPDATED
    assert consumer_a.process(example_4_3).action is WorkflowAction.CANCELLED

    # Branch B: 4.1 -> 4.2 -> 4.4 (Open) -> 4.5 (Closed)
    consumer_b = MaintenanceConsumer()
    assert consumer_b.process(example_4_1).action is WorkflowAction.INITIAL
    assert consumer_b.process(example_4_2).action is WorkflowAction.UPDATED
    assert consumer_b.process(example_4_4).action is WorkflowAction.OPENED
    assert consumer_b.process(example_4_5).action is WorkflowAction.CLOSED


def test_consumer_out_of_band_verifier_blocks_untrusted_notification() -> None:
    class AllowListVerifier:
        def verify(self, notification: MaintenanceNotification) -> bool:
            return notification.provider == "trusted.example.com"

    provider = MaintenanceProvider(
        provider="untrusted.example.org", organizer="x@untrusted.example.org"
    )
    notif = provider.create_initial(
        account="1",
        maintenance_id="M1",
        objects=["obj-1"],
        dtstart=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
        summary="Spoofed maintenance",
        impact="X-CUSTOM-IMPACT",
    )
    consumer = MaintenanceConsumer(verifier=AllowListVerifier())
    with pytest.raises(VerificationError, match="Out-of-band verification failed"):
        consumer.process(notif)
    assert consumer.store.list_all() == []
