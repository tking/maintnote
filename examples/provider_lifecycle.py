"""Example: Provider-side full maintenance notification lifecycle (Sections 3.1.1-3.5.1)."""

from __future__ import annotations

from datetime import datetime, timezone

from maintnote import (
    Impact,
    MaintenanceProvider,
    Organizer,
    RecipientPreference,
    ServiceObject,
    dumps,
)


def main() -> None:
    provider = MaintenanceProvider(
        provider="example.com",
        organizer=Organizer("noc@example.com", cn="Example NOC"),
    )

    # Section 2.3.1: individual recipient opts into METHOD for a shared calendar
    provider.set_recipient_preference(
        "137.035999173",
        RecipientPreference(include_method=False),
    )

    initial = provider.create_initial(
        account="137.035999173",
        maintenance_id="WorkOrder-31415",
        objects=[
            ServiceObject(
                object_id="2718281828459",
                altrep="https://example.org/maintenance?id=2718281828459",
            ),
            ServiceObject(object_id="acme-widgets-as-a-service"),
        ],
        dtstart=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc),
        summary="Maint Note Example",
        impact=Impact.OUTAGE,
    )

    confirmed = provider.confirm(
        initial,
        dtstart=datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc),
    )
    opened = provider.open_window(confirmed, description="Maintenance window is now open.")
    closed = provider.close_window(opened, description="Maintenance complete; all services normal.")

    for label, notif in [
        ("3.1 Initial", initial),
        ("3.2 Confirmed", confirmed),
        ("3.4 Open", opened),
        ("3.5 Closed", closed),
    ]:
        print(f"=== {label} (UID={notif.uid}, SEQ={notif.sequence}, STATUS={notif.status}) ===")
        print(dumps(notif))


if __name__ == "__main__":
    main()
