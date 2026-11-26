# Provider and Consumer Workflows

Section 3 of `draft-gunter-calext-maintenance-notifications-00` defines five maintenance workflows.
`maintnote.workflow` implements both the provider side (`MaintenanceProvider`) and the consumer side (`MaintenanceConsumer`).

## Lifecycle State Machine

Each maintenance window starts with an initial notification at `SEQUENCE=0` (usually `TENTATIVE` or `CONFIRMED`).
Each subsequent transition keeps the same `UID`, increases `SEQUENCE` by 1, and updates `DTSTAMP`:

```text
  [Initial: TENTATIVE or CONFIRMED, SEQ=0]
            |
            +-- update_window() or confirm() --> [Updated: SEQ+1]
            |                                          |
            +-- cancel() ------------------------------+--> [CANCELLED: SEQ+1] (terminal)
            |                                          |
            +-- open_window() -------------------------+--> [IN-PROCESS: SEQ+1]
                                                                  |
                                                                  +-- close_window() --> [COMPLETED: SEQ+1] (terminal)
```

`CANCELLED` and `COMPLETED` are terminal states.
If you try to update a notification in a terminal state, `MaintenanceProvider` raises `WorkflowError` by default.

## Provider Side (`MaintenanceProvider`)

### Send One Maintenance to More Than One Account (Section 3.1.1)

When one physical maintenance affects more than one customer, each customer must get a separate notification with its own `UID`.
All notifications in that batch share the same `X-MAINTNOTE-MAINTENANCE-ID`.

Call `create_batch_initial()` to generate those per-account notifications:

```python
from datetime import datetime, timezone
from maintnote import Impact, MaintenanceProvider, Organizer, RecipientPreference

provider = MaintenanceProvider(
    provider="carrier.example.net",
    organizer=Organizer("noc@carrier.example.net", cn="Carrier NOC"),
)

# Section 2.3.1: allow one account to include METHOD for a shared calendar
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

### Advance Single Notifications and Batches (Sections 3.2.1 to 3.5.1)

Call the single-notification or batch method for each lifecycle event:

| Lifecycle Action | Single Notification Method | Batch Method | New Status |
| --- | --- | --- | --- |
| Reschedule or change details | `update_window(prev, ...)` | `update_batch(id, ...)` | Unchanged or specified status |
| Confirm a tentative window | `confirm(prev, ...)` | `confirm_batch(id, ...)` | `CONFIRMED` |
| Cancel an active window | `cancel(prev, ...)` | `cancel_batch(id, ...)` | `CANCELLED` |
| Declare work started | `open_window(prev, ...)` | `open_batch(id, ...)` | `IN-PROCESS` |
| Declare work finished | `close_window(prev, ...)` | `close_batch(id, ...)` | `COMPLETED` |

To see complete provider scripts, run `examples/provider_lifecycle.py` and `examples/multi_customer_batch.py`.

## Consumer Side (`MaintenanceConsumer`)

### Track State and Automate Tickets (Sections 3.1.2 to 3.5.2)

`MaintenanceConsumer` connects received notifications to two pluggable interfaces:

- **`StateStore`:** Stores the latest notification and `SEQUENCE` number for each `(provider, uid)` pair. Use `SQLiteStateStore` for persistent storage in services or cron jobs, and `InMemoryStateStore` for tests.
- **`TicketHandler`:** Receives lifecycle callbacks so your code can create, update, cancel, open, or close tickets in Jira, ServiceNow, PagerDuty, or a DevOps automation pipeline.

Implement `TicketHandler` to connect your own system:

```python
from maintnote import MaintenanceConsumer, SQLiteStateStore, TicketPriority


class MyTicketingAdapter:
    def create_ticket(
        self,
        notification,
        *,
        priority: TicketPriority,
        assign_to_remediation_queue: bool,
    ) -> str:
        # Unknown impacts map to OUTAGE -> TicketPriority.CRITICAL (Section 2.5.5).
        # TENTATIVE notifications set assign_to_remediation_queue=False (Section 3.1.2).
        return f"INC-{notification.maintenance_id}"

    def update_ticket(
        self, ticket_id, notification, diff, *, priority, assign_to_remediation_queue
    ) -> None:
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

### How `MaintenanceConsumer` Protects Automation

When you call `consumer.process(received)`, the consumer applies five safety checks automatically:

1. **Duplicate protection:** If `received.sequence == stored.sequence`, `process()` returns `WorkflowAction.IGNORED_DUPLICATE`. It does not change the store or ticket.
2. **Out-of-order protection:** If `received.sequence < stored.sequence`, `process()` returns `WorkflowAction.IGNORED_STALE`. It keeps the newer state.
3. **No-change update filter:** If `SEQUENCE` increases but `diff.has_changes` is `False`, `process()` returns `WorkflowAction.NO_OP_UPDATE`. It skips unnecessary ticket edits.
4. **Tentative queue control:** If `status` is `TENTATIVE`, `assign_to_remediation_queue` is `False`. This prevents traffic changes before the provider confirms the maintenance (Section 3.1.2).
5. **Cross-provider object isolation:** Different carriers can use the same circuit ID (for example, `CIRCUIT-100`). Query with `store.list_by_scoped_object(provider, object_id)` so objects stay isolated by `(provider, object_id)` (Section 2.5.4).

To see complete consumer scripts, run `examples/consumer_pipeline.py` and `examples/multi_provider_automation.py`.
