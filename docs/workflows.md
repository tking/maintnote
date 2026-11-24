# Provider & Consumer Workflows

Section 3 of `draft-gunter-calext-maintenance-notifications-00` defines five end-to-end maintenance notification workflows. `maintnote.workflow` provides first-class support for both sides.

## Lifecycle State Machine

```
  [Initial: TENTATIVE / CONFIRMED, SEQ=0]
            │
            ├── update_window() / confirm() ──► [Updated: SEQ+1]
            │                                         │
            ├── cancel() ─────────────────────────────┼──► [CANCELLED: SEQ+1] (terminal)
            │                                         │
            └── open_window() ────────────────────────┴──► [IN-PROCESS: SEQ+1]
                                                                  │
                                                                  └── close_window() ──► [COMPLETED: SEQ+1] (terminal)
```

## Provider Side (`MaintenanceProvider`)

### Multi-Customer Maintenance Fan-Out (Section 3.1.1)

When a network element maintenance affects multiple accounts, generate distinct per-account notifications with a unique `UID` per consumer while sharing the same `X-MAINTNOTE-MAINTENANCE-ID`:

```python
from datetime import datetime, timezone
from maintnote import Impact, MaintenanceProvider, Organizer, RecipientPreference

provider = MaintenanceProvider(
    provider="carrier.example.net",
    organizer=Organizer("noc@carrier.example.net", cn="Carrier NOC"),
)

# Section 2.3.1: allow individual recipients to opt into METHOD
provider.set_recipient_preference(
    "acct-shared-cal",
    RecipientPreference(include_method=True, method="PUBLISH", cancel_method="CANCEL"),
)

notifications = provider.create_batch_initial(
    maintenance_id="WO-2026-441",
    affected_accounts={
        "acct-shared-cal": ["ckt-100", "ckt-101"],
        "acct-automation-only": ["ckt-200"],
    },
    dtstart=datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc),
    dtend=datetime(2026, 11, 20, 3, 0, tzinfo=timezone.utc),
    summary="Metro ring fiber splice",
    impact=Impact.OUTAGE,
)
```

### Subsequent Transitions (Sections 3.2.1–3.5.1)

Every transition preserves `UID`, increments `SEQUENCE` by 1, and refreshes `DTSTAMP`:

- `provider.update_window(prev, dtstart=..., dtend=...)` — reschedule or modify details
- `provider.confirm(prev, ...)` — set `X-MAINTNOTE-STATUS:CONFIRMED`
- `provider.cancel(prev, ...)` — set `X-MAINTNOTE-STATUS:CANCELLED`
- `provider.open_window(prev, ...)` — set `X-MAINTNOTE-STATUS:IN-PROCESS`
- `provider.close_window(prev, ...)` — set `X-MAINTNOTE-STATUS:COMPLETED`

## Consumer Side (`MaintenanceConsumer`)

### Persistence & Ticket Automation (Sections 3.1.2–3.5.2)

Implement the `TicketHandler` protocol to connect to Jira, ServiceNow, PagerDuty, or your internal ticketing system, and pair it with `SQLiteStateStore` (or a custom `StateStore`):

```python
from maintnote import MaintenanceConsumer, SQLiteStateStore, TicketHandler, TicketPriority

class MyTicketingAdapter:
    def create_ticket(self, notification, *, priority: TicketPriority, assign_to_remediation_queue: bool) -> str:
        # Elevated priority automatically reflects effective_impact (unknown -> OUTAGE)
        # assign_to_remediation_queue is False when status is TENTATIVE (Section 3.1.2)
        return f"INC-{notification.maintenance_id}"

    def update_ticket(self, ticket_id, notification, diff, *, priority, assign_to_remediation_queue) -> None:
        ...

    def cancel_ticket(self, ticket_id, notification, diff) -> None:
        ...

    def open_ticket(self, ticket_id, notification, diff) -> None:
        ...

    def close_ticket(self, ticket_id, notification, diff) -> None:
        ...

store = SQLiteStateStore("consumer_state.sqlite3")
consumer = MaintenanceConsumer(store=store, handler=MyTicketingAdapter())
```

### Out-of-Order & Duplicate Protection

- If `incoming.sequence == stored.sequence` → returns `WorkflowAction.IGNORED_DUPLICATE` without mutating ticket or DB state.
- If `incoming.sequence < stored.sequence` → returns `WorkflowAction.IGNORED_STALE` without overwriting newer state.
- Cross-provider object queries always use the composite `(provider, object_id)` key via `store.list_by_scoped_object(provider, object_id)` (Section 2.5.4).
