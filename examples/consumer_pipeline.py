"""Example: Consumer-side email extraction and SQLite-backed workflow automation."""

from __future__ import annotations

from datetime import datetime, timezone

from maintnote import (
    Impact,
    InMemoryTicketHandler,
    MaintenanceConsumer,
    MaintenanceProvider,
    Organizer,
    SQLiteStateStore,
    build_notification_email,
    extract_notifications_from_email,
)


def main() -> None:
    provider = MaintenanceProvider(
        provider="transit.example.net",
        organizer=Organizer("noc@transit.example.net", cn="Transit NOC"),
    )
    store = SQLiteStateStore(":memory:")
    handler = InMemoryTicketHandler(prefix="NETOPS")
    consumer = MaintenanceConsumer(store=store, handler=handler)

    try:
        n0 = provider.create_initial(
            account="CUST-42",
            maintenance_id="CHG-9981",
            objects=["xe-0/0/0.iad1"],
            dtstart=datetime(2026, 11, 1, 2, 0, tzinfo=timezone.utc),
            dtend=datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc),
            summary="IAD1 router firmware upgrade",
            impact=Impact.OUTAGE,
        )
        n1 = provider.confirm(n0)
        n2 = provider.open_window(n1, description="Upgrade started.")
        n3 = provider.close_window(n2, description="Upgrade finished cleanly.")

        # Deliver each notification over RFC 5322 email + text/calendar attachment
        for notif in (n0, n1, n2, n3, n0):  # Final n0 simulates an out-of-order stale email
            eml = build_notification_email(
                notif,
                sender="noc@transit.example.net",
                recipient="automation@customer.example",
            )
            for extracted in extract_notifications_from_email(eml.as_bytes(), strip_method=True):
                result = consumer.process(extracted)
                print(
                    f"seq={extracted.sequence} -> action={result.action.value} "
                    f"ticket={result.ticket_id} priority={result.priority.value} "
                    f"remediation_queue={result.assign_to_remediation_queue}"
                )

        ticket = next(iter(handler.tickets.values()))
        print(f"\nFinal ticket state: {ticket.ticket_id} ({ticket.state})")
        print("History:", " -> ".join(ticket.history))
    finally:
        store.close()


if __name__ == "__main__":
    main()
