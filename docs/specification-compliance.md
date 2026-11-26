# Specification Compliance Matrix

This table maps each section of [`draft-gunter-calext-maintenance-notifications-00`](https://datatracker.ietf.org/doc/html/draft-gunter-calext-maintenance-notifications-00) to its implementation in `maintnote`.

| Draft Section | Requirement | `maintnote` Implementation |
| --- | --- | --- |
| **2.2 and 2.3** | RFC 5545 `VCALENDAR` with `VERSION:2.0`, `PRODID`, optional `METHOD`, `VTIMEZONE`, and `VALARM` | `maintnote.ical`, `maintnote.parser`, `maintnote.serializer` (supports `VTIMEZONE` offsets, `VALUE=DATE`, and subcomponent round-trips) |
| **2.3.1** | Omit `METHOD` by default; validate iTIP methods; support per-recipient opt-in and consumer removal | `dumps(include_method=...)`, `RecipientPreference`, RFC 5546 `METHOD` and `ATTENDEE` checks, `strip_method_from_ical()`, `strip_method_from_email()`, `maintnote strip-email-method` |
| **2.4** | Mandatory `VEVENT` properties, UTC `DTSTAMP` (RFC 5545 Section 3.8.7.2), and extra properties that do not conflict | `MaintenanceNotification`, `validate()`, `CONFLICTING_ICAL_STATUS`, `NON_UTC_DTSTAMP`, `extra_calendar_properties`, `extra_event_properties`, `extra_*_subcomponents` |
| **2.5.1** | `X-MAINTNOTE-PROVIDER` (`TEXT` with IANA, `x-name`, or `LANGUAGE` parameters) | `MaintenanceNotification.provider`, `provider_params` |
| **2.5.2** | `X-MAINTNOTE-ACCOUNT` (`TEXT` with IANA, `x-name`, or `LANGUAGE` parameters) | `MaintenanceNotification.account`, `account_params` |
| **2.5.3** | `X-MAINTNOTE-MAINTENANCE-ID` (`TEXT` with IANA, `x-name`, or `LANGUAGE` parameters) | `MaintenanceNotification.maintenance_id`, `maintenance_id_params` |
| **2.5.4** | `X-MAINTNOTE-OBJECT-ID` (one or more items, `ALTREP` URI validation and download, `(provider, object_id)` scoping, duplicate warnings) | `ServiceObject`, `ServiceObject.scoped_id()`, `INVALID_ALTREP_URI`, `DUPLICATE_OBJECT_ID`, `fetch_altrep_metadata()` |
| **2.5.5** | `X-MAINTNOTE-IMPACT` (`NO-IMPACT`, `REDUCED-REDUNDANCY`, `DEGRADED`, `OUTAGE`; unknown `x-name` or `iana-token` defaults to `OUTAGE`; no `LANGUAGE` parameter) | `Impact`, `ImpactValue`, `ImpactValue.effective`, `DISALLOWED_LANGUAGE_PARAM` |
| **2.5.6** | Optional `X-MAINTNOTE-STATUS` (`TENTATIVE`, `CONFIRMED`, `CANCELLED`, `IN-PROCESS`, `COMPLETED`; extensible `x-name` or `iana-token`; no `LANGUAGE` parameter) | `Status`, `StatusValue`, `DISALLOWED_LANGUAGE_PARAM` |
| **3.1** | Initial notification for providers and consumers, multi-account fan-out, and `(provider, uid)` isolation | `MaintenanceProvider.create_initial()`, `create_batch_initial()`, `MaintenanceConsumer.process()` (`WorkflowAction.INITIAL`), `(provider, uid)` `StateStore` |
| **3.2** | Updated window with stable `UID`, higher `SEQUENCE`, no-change update filter, and stale rejection | `MaintenanceProvider.update_window()`, `update_batch()`, `confirm()`, `confirm_batch()`, `WorkflowAction.UPDATED`, `NO_OP_UPDATE`, `IGNORED_STALE`, `IGNORED_DUPLICATE` |
| **3.3** | Cancelled window (`CANCELLED`) | `MaintenanceProvider.cancel()`, `cancel_batch()`, `TicketHandler.cancel_ticket()` (`WorkflowAction.CANCELLED`) |
| **3.4** | Open window (`IN-PROCESS`) | `MaintenanceProvider.open_window()`, `open_batch()`, `TicketHandler.open_ticket()` (`WorkflowAction.OPENED`) |
| **3.5** | Closed window (`COMPLETED`) | `MaintenanceProvider.close_window()`, `close_batch()`, `TicketHandler.close_ticket()` (`WorkflowAction.CLOSED`) |
| **4.1 to 4.5** | Verbatim draft examples | Verified in `tests/test_parser.py` and `tests/test_workflow.py` |
| **5.1** | Localization (`LANGUAGE` parameters, UTF-8 text, localized summary prefixes, and email labels) | `LocalizationStrings`, `language` parameter support, 75-octet RFC 5545 line folding safe for UTF-8 |
| **5.2** | Email with RFC 3156 OpenPGP, CalDAV over TLS (RFC 4791), and out-of-band verification | `maintnote.email_utils`, `CalDAVClient`, `OutOfBandVerifier` |

## Known Draft Quirks

`maintnote` handles three known edge cases from the Internet-Draft:

1. **Table 2 typo (`X-MAINTENOTE-*`):** Strict mode (`strict=True`) rejects this typo. Lenient mode (`strict=False`) maps it to `X-MAINTNOTE-*` and adds a `LEGACY_TYPO_PROPERTY` warning.
2. **Example 4.5 space at the start (`X-MAINTNOTE-STATUS: COMPLETED`):** `maintnote` trims the extra space to `Status.COMPLETED` and records a `WHITESPACE_VALUE` warning.
3. **Section 4 short UIDs (`UID:42`):** `StateStore` keys records by `(provider, uid)` so simple numeric UIDs from different providers do not collide.
