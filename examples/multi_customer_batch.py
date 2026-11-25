"""Example: Multi-customer provider batch fan-out, METHOD preferences, and cancellation.

Demonstrates Section 2.3.1 (per-recipient METHOD opt-in), Section 3.1.1-3.3.1
(multi-account batch initial -> update -> confirm -> cancel), and terminal-state
protection against mutating a cancelled maintenance window.
"""

from __future__ import annotations

from datetime import datetime, timezone

from maintnote import (
    Impact,
    MaintenanceProvider,
    Organizer,
    RecipientPreference,
    ServiceObject,
    WorkflowError,
    dumps,
)


def main() -> None:
    provider = MaintenanceProvider(
        provider="carrier.example.net",
        organizer=Organizer("noc@carrier.example.net", cn="Carrier NOC"),
    )

    # Section 2.3.1: acct-shared-cal explicitly opts into METHOD for a shared team calendar;
    # acct-automation-only keeps the safe default (METHOD omitted).
    provider.set_recipient_preference(
        "acct-shared-cal",
        RecipientPreference(include_method=True, method="PUBLISH", cancel_method="CANCEL"),
    )

    affected_accounts: dict[str, list[ServiceObject | str]] = {
        "acct-shared-cal": [
            ServiceObject(
                object_id="ckt-100",
                altrep="https://portal.carrier.example.net/circuits/ckt-100.json",
            ),
            "ckt-101",
        ],
        "acct-automation-only": ["ckt-200"],
    }

    print("=== 1. Initial multi-customer batch (Section 3.1.1) ===")
    initial_batch = provider.create_batch_initial(
        maintenance_id="WO-2026-441",
        affected_accounts=affected_accounts,
        dtstart=datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 11, 20, 3, 0, tzinfo=timezone.utc),
        summary="Metro ring fiber splice",
        impact=Impact.OUTAGE,
    )
    for account, notif in initial_batch.items():
        print(
            f"  account={account} uid={notif.uid} seq={notif.sequence} "
            f"status={notif.status} method={notif.method} objects={notif.object_ids}"
        )

    print("\n=== 2. Reschedule & confirm across all accounts (Section 3.2.1) ===")
    provider.update_batch(
        "WO-2026-441",
        dtstart=datetime(2026, 11, 21, 1, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc),
        description="Window shifted by 24 hours due to municipal permit.",
    )
    confirmed_batch = provider.confirm_batch("WO-2026-441")
    for account, notif in confirmed_batch.items():
        print(
            f"  account={account} uid={notif.uid} seq={notif.sequence} "
            f"status={notif.status} start={notif.dtstart.isoformat()}"
        )

    print("\n=== 3. Cancel batch across all accounts (Section 3.3.1) ===")
    cancelled_batch = provider.cancel_batch(
        "WO-2026-441",
        description="Work deferred indefinitely; circuits remain unaffected.",
    )
    for account, notif in cancelled_batch.items():
        ical = dumps(notif)
        has_method = "METHOD:" in ical
        print(
            f"  account={account} seq={notif.sequence} status={notif.status} "
            f"method={notif.method} serialized_has_METHOD={has_method}"
        )

    print("\n=== 4. Terminal-state guard prevents accidental post-cancel updates ===")
    try:
        provider.update_window(
            cancelled_batch["acct-automation-only"],
            summary="Accidental update after cancellation",
        )
    except WorkflowError as exc:
        print(f"  Blocked as expected: {exc}")


if __name__ == "__main__":
    main()
