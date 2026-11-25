"""Example: Multi-provider consumer automation, scoped objects, and out-of-band verification.

Demonstrates:
- Cross-provider (provider, object_id) collision isolation (Section 2.5.4)
- Unknown custom X-MAINTNOTE-IMPACT falling back to OUTAGE/CRITICAL (Section 2.5.5)
- TENTATIVE vs. CONFIRMED remediation-queue gating (Section 3.1.2)
- Custom TicketHandler reacting to NotificationDiff and Impact.worst()
- OutOfBandVerifier rejecting spoofed notifications before automation runs (Section 5.2)
"""

from __future__ import annotations

from datetime import datetime, timezone

from maintnote import (
    Impact,
    MaintenanceConsumer,
    MaintenanceNotification,
    MaintenanceProvider,
    NotificationDiff,
    SQLiteStateStore,
    TicketPriority,
    VerificationError,
)


class BGPDrainAutomationHandler:
    """Custom TicketHandler illustrating NOC ticket + BGP session drain integration."""

    def __init__(self) -> None:
        self._counter = 0
        self.events: list[str] = []

    def create_ticket(
        self,
        notification: MaintenanceNotification,
        *,
        priority: TicketPriority,
        assign_to_remediation_queue: bool,
    ) -> str:
        self._counter += 1
        ticket_id = f"NOC-{self._counter:04d}"
        queue_state = "QUEUED_FOR_DRAIN" if assign_to_remediation_queue else "HOLD_TENTATIVE"
        msg = (
            f"CREATE {ticket_id} provider={notification.provider} "
            f"impact={notification.impact.raw}->{notification.effective_impact.value} "
            f"priority={priority.value} queue={queue_state}"
        )
        self.events.append(msg)
        print(f"  [handler] {msg}")
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
        msg = (
            f"UPDATE {ticket_id} changed={diff.changed_fields} "
            f"priority={priority.value} remediation={assign_to_remediation_queue}"
        )
        self.events.append(msg)
        print(f"  [handler] {msg}")

    def cancel_ticket(
        self,
        ticket_id: str,
        notification: MaintenanceNotification,
        diff: NotificationDiff,
    ) -> None:
        msg = f"CANCEL {ticket_id} seq={notification.sequence}"
        self.events.append(msg)
        print(f"  [handler] {msg}")

    def open_ticket(
        self,
        ticket_id: str,
        notification: MaintenanceNotification,
        diff: NotificationDiff,
    ) -> None:
        msg = f"OPEN {ticket_id} -> drain BGP peers for {notification.scoped_object_ids}"
        self.events.append(msg)
        print(f"  [handler] {msg}")

    def close_ticket(
        self,
        ticket_id: str,
        notification: MaintenanceNotification,
        diff: NotificationDiff,
    ) -> None:
        msg = f"CLOSE {ticket_id} -> restore BGP peers for {notification.scoped_object_ids}"
        self.events.append(msg)
        print(f"  [handler] {msg}")


class AllowlistPortalVerifier:
    """Section 5.2 OutOfBandVerifier checking trusted provider/maintenance IDs."""

    def __init__(self, trusted_providers: set[str]) -> None:
        self._trusted_providers = trusted_providers

    def verify(self, notification: MaintenanceNotification) -> bool:
        return notification.provider in self._trusted_providers


def main() -> None:
    carrier_a = MaintenanceProvider(provider="carrier-a.example", organizer="noc@carrier-a.example")
    carrier_b = MaintenanceProvider(provider="carrier-b.example", organizer="noc@carrier-b.example")
    spoofed = MaintenanceProvider(provider="untrusted.example", organizer="spoof@untrusted.example")

    store = SQLiteStateStore(":memory:")
    handler = BGPDrainAutomationHandler()
    verifier = AllowlistPortalVerifier({"carrier-a.example", "carrier-b.example"})
    consumer = MaintenanceConsumer(store=store, handler=handler, verifier=verifier)

    try:
        print("=== 1. Two providers independently use the same CIRCUIT-100 object ID ===")
        # Provider A sends a TENTATIVE notification with a custom vendor impact (X-PACKET-LOSS).
        # Section 2.5.5 defaults unknown impacts to OUTAGE -> CRITICAL priority.
        # Section 3.1.2 holds TENTATIVE tickets out of the remediation queue.
        a_init = carrier_a.create_initial(
            account="CUST-1",
            maintenance_id="CA-1001",
            objects=["CIRCUIT-100"],
            dtstart=datetime(2026, 12, 5, 1, 0, tzinfo=timezone.utc),
            dtend=datetime(2026, 12, 5, 3, 0, tzinfo=timezone.utc),
            summary="Carrier A optical grooming",
            impact="X-PACKET-LOSS",
        )
        res_a0 = consumer.process(a_init)
        assert res_a0.priority is TicketPriority.CRITICAL
        assert res_a0.assign_to_remediation_queue is False

        # Provider A confirms -> now eligible for remediation queue
        a_conf = carrier_a.confirm(a_init)
        res_a1 = consumer.process(a_conf)
        assert res_a1.assign_to_remediation_queue is True

        # Provider B announces REDUCED-REDUNDANCY on its own CIRCUIT-100
        b_init = carrier_b.create_initial(
            account="CUST-1",
            maintenance_id="CB-2002",
            objects=["CIRCUIT-100"],
            dtstart=datetime(2026, 12, 6, 4, 0, tzinfo=timezone.utc),
            dtend=datetime(2026, 12, 6, 5, 0, tzinfo=timezone.utc),
            summary="Carrier B standby supervisor swap",
            impact=Impact.REDUCED_REDUNDANCY,
        )
        consumer.process(b_init)

        # Query scoped objects independently (no cross-provider collision)
        a_records = store.list_by_scoped_object("carrier-a.example", "CIRCUIT-100")
        b_records = store.list_by_scoped_object("carrier-b.example", "CIRCUIT-100")
        worst = Impact.worst(a_records[0].notification.impact, b_records[0].notification.impact)
        print(
            f"  Scoped lookup: carrier-a={len(a_records)} ({a_records[0].maintenance_id}), "
            f"carrier-b={len(b_records)} ({b_records[0].maintenance_id}), "
            f"worst_effective_impact={worst.value}"
        )

        print("\n=== 2. Out-of-band verifier blocks untrusted provider (Section 5.2) ===")
        bad_notif = spoofed.create_initial(
            account="CUST-1",
            maintenance_id="SPOOF-99",
            objects=["CIRCUIT-100"],
            dtstart=datetime(2026, 12, 7, 1, 0, tzinfo=timezone.utc),
            dtend=datetime(2026, 12, 7, 2, 0, tzinfo=timezone.utc),
            summary="Fake emergency outage",
            impact=Impact.OUTAGE,
        )
        try:
            consumer.process(bad_notif)
        except VerificationError as exc:
            print(f"  Rejected before ticket creation: {exc}")

        print("\n=== 3. Open and close Carrier A maintenance window ===")
        a_open = carrier_a.open_window(a_conf)
        a_close = carrier_a.close_window(a_open)
        consumer.process(a_open)
        consumer.process(a_close)
    finally:
        store.close()


if __name__ == "__main__":
    main()
