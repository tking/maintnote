# Specification Compliance Matrix

This matrix maps every section of [`draft-gunter-calext-maintenance-notifications-00`](https://datatracker.ietf.org/doc/html/draft-gunter-calext-maintenance-notifications-00) to its implementation in `maintnote`.

| Draft Section | Requirement | `maintnote` Implementation |
| --- | --- | --- |
| **2.2 / 2.3** | RFC 5545 `VCALENDAR` with `VERSION:2.0` (1), `PRODID` (1), `METHOD` (0..1) | `maintnote.ical`, `maintnote.parser`, `maintnote.serializer` |
| **2.3.1** | Omit `METHOD` by default; per-recipient provider opt-in; recipient pre-processing | `dumps(include_method=...)`, `RecipientPreference`, `strip_method_from_ical()` |
| **2.4** | Mandatory `VEVENT` properties (`DTSTAMP`, `DTSTART`, `DTEND`, `UID`, `SUMMARY`, `ORGANIZER`, `SEQUENCE`, `X-MAINTNOTE-*`) and non-conflicting extra properties | `MaintenanceNotification`, `validate()`, `extra_calendar_properties`, `extra_event_properties` |
| **2.5.1** | `X-MAINTNOTE-PROVIDER` (`TEXT`, IANA/x-name/`LANGUAGE` params) | `MaintenanceNotification.provider`, `provider_params` |
| **2.5.2** | `X-MAINTNOTE-ACCOUNT` (`TEXT`, IANA/x-name/`LANGUAGE` params) | `MaintenanceNotification.account`, `account_params` |
| **2.5.3** | `X-MAINTNOTE-MAINTENANCE-ID` (`TEXT`, IANA/x-name/`LANGUAGE` params) | `MaintenanceNotification.maintenance_id`, `maintenance_id_params` |
| **2.5.4** | `X-MAINTNOTE-OBJECT-ID` (1 or more instances, `ALTREP` URI parameter, `(provider, object_id)` scoping) | `ServiceObject`, `ServiceObject.scoped_id()`, `fetch_altrep_metadata()` |
| **2.5.5** | `X-MAINTNOTE-IMPACT` (`NO-IMPACT`, `REDUCED-REDUNDANCY`, `DEGRADED`, `OUTAGE`, extensible `x-name`/`iana-token` defaulting to `OUTAGE`) | `Impact`, `ImpactValue`, `ImpactValue.effective` |
| **2.5.6** | `X-MAINTNOTE-STATUS` (optional 0..1; `TENTATIVE`, `CONFIRMED`, `CANCELLED`, `IN-PROCESS`, `COMPLETED`, extensible `x-name`/`iana-token`) | `Status`, `StatusValue` |
| **3.1** | Initial Maintenance Notification (Provider & Consumer) | `MaintenanceProvider.create_initial()`, `create_batch_initial()`, `MaintenanceConsumer.process()` (`WorkflowAction.INITIAL`) |
| **3.2** | Updated Maintenance Notification Window (UID match, incremented `SEQUENCE`, out-of-order rejection) | `MaintenanceProvider.update_window()`, `confirm()`, `MaintenanceConsumer.process()` (`WorkflowAction.UPDATED`, `IGNORED_STALE`, `IGNORED_DUPLICATE`) |
| **3.3** | Canceled Maintenance Notification Window (`CANCELLED`) | `MaintenanceProvider.cancel()`, `TicketHandler.cancel_ticket()` (`WorkflowAction.CANCELLED`) |
| **3.4** | Open Maintenance Notification Window (`IN-PROCESS`) | `MaintenanceProvider.open_window()`, `TicketHandler.open_ticket()` (`WorkflowAction.OPENED`) |
| **3.5** | Closed Maintenance Notification Window (`COMPLETED`) | `MaintenanceProvider.close_window()`, `TicketHandler.close_ticket()` (`WorkflowAction.CLOSED`) |
| **4.1–4.5** | Verbatim draft examples | Tested directly in `tests/test_parser.py` and `tests/test_workflow.py` |
| **5.1** | Localization (`LANGUAGE` parameter, UTF-8 text) | `language` parameter support + UTF-8 octet-safe RFC 5545 line folding |
| **5.2** | Email + OpenPGP (RFC 3156), CalDAV over TLS (RFC 4791 / RFC 5246+), out-of-band verification | `maintnote.email_utils`, `CalDAVClient`, `OutOfBandVerifier` |

## Draft Quirks Handled Cleanly

1. **Table 2 typo (`X-MAINTENOTE-*`)**: Rejected in strict mode (`strict=True`), automatically mapped with a `LEGACY_TYPO_PROPERTY` warning in lenient mode (`strict=False`).
2. **Example 4.5 whitespace (`X-MAINTNOTE-STATUS: COMPLETED`)**: Trimmed cleanly to `Status.COMPLETED` while emitting a `WHITESPACE_VALUE` warning in diagnostics.
