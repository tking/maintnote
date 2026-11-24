# Specification Compliance Matrix

This matrix maps every section of [`draft-gunter-calext-maintenance-notifications-00`](https://datatracker.ietf.org/doc/html/draft-gunter-calext-maintenance-notifications-00) to its implementation in `maintnote`.

| Draft Section | Requirement | `maintnote` Implementation |
| --- | --- | --- |
| **2.2 / 2.3** | RFC 5545 `VCALENDAR` with `VERSION:2.0` (1), `PRODID` (1), `METHOD` (0..1), `VTIMEZONE`/`VALARM` interop | `maintnote.ical`, `maintnote.parser`, `maintnote.serializer` (including custom `VTIMEZONE` offset fallback, `VALUE=DATE`, and subcomponent round-trip preservation) |
| **2.3.1** | Omit `METHOD` by default; iTIP method validation; per-recipient provider opt-in; recipient pre-processing | `dumps(include_method=...)`, `RecipientPreference`, RFC 5546 `METHOD`/`ATTENDEE` validation, `strip_method_from_ical()`, `strip_method_from_email()`, `maintnote strip-email-method` |
| **2.4** | Mandatory `VEVENT` properties, UTC `DTSTAMP` (RFC 5545 §3.8.7.2), and non-conflicting extra properties (incl. RFC 5545 `STATUS` conflict check) | `MaintenanceNotification`, `validate()`, `CONFLICTING_ICAL_STATUS`, `NON_UTC_DTSTAMP`, `extra_calendar_properties`, `extra_event_properties`, `extra_*_subcomponents` |
| **2.5.1** | `X-MAINTNOTE-PROVIDER` (`TEXT`, IANA/x-name/`LANGUAGE` params) | `MaintenanceNotification.provider`, `provider_params` |
| **2.5.2** | `X-MAINTNOTE-ACCOUNT` (`TEXT`, IANA/x-name/`LANGUAGE` params) | `MaintenanceNotification.account`, `account_params` |
| **2.5.3** | `X-MAINTNOTE-MAINTENANCE-ID` (`TEXT`, IANA/x-name/`LANGUAGE` params) | `MaintenanceNotification.maintenance_id`, `maintenance_id_params` |
| **2.5.4** | `X-MAINTNOTE-OBJECT-ID` (1+ instances, `ALTREP` URI validation & retrieval, `(provider, object_id)` scoping, duplicate warnings) | `ServiceObject`, `ServiceObject.scoped_id()`, `INVALID_ALTREP_URI`, `DUPLICATE_OBJECT_ID`, hardened `fetch_altrep_metadata()` |
| **2.5.5** | `X-MAINTNOTE-IMPACT` (`NO-IMPACT`, `REDUCED-REDUNDANCY`, `DEGRADED`, `OUTAGE`, extensible `x-name`/`iana-token` defaulting to `OUTAGE`, no `LANGUAGE` param) | `Impact`, `ImpactValue`, `ImpactValue.effective`, `DISALLOWED_LANGUAGE_PARAM` |
| **2.5.6** | `X-MAINTNOTE-STATUS` (optional 0..1; `TENTATIVE`, `CONFIRMED`, `CANCELLED`, `IN-PROCESS`, `COMPLETED`, extensible `x-name`/`iana-token`, no `LANGUAGE` param) | `Status`, `StatusValue`, `DISALLOWED_LANGUAGE_PARAM` |
| **3.1** | Initial Maintenance Notification (Provider & Consumer, multi-account fan-out, `(provider, UID)` isolation) | `MaintenanceProvider.create_initial()`, `create_batch_initial()`, `MaintenanceConsumer.process()` (`WorkflowAction.INITIAL`), `(provider, uid)` `StateStore` |
| **3.2** | Updated Maintenance Notification Window (UID match, incremented `SEQUENCE`, no-op filtering, out-of-order rejection) | `MaintenanceProvider.update_window()`, `update_batch()`, `confirm()`, `confirm_batch()`, `WorkflowAction.UPDATED`, `NO_OP_UPDATE`, `IGNORED_STALE`, `IGNORED_DUPLICATE` |
| **3.3** | Canceled Maintenance Notification Window (`CANCELLED`) | `MaintenanceProvider.cancel()`, `cancel_batch()`, `TicketHandler.cancel_ticket()` (`WorkflowAction.CANCELLED`) |
| **3.4** | Open Maintenance Notification Window (`IN-PROCESS`) | `MaintenanceProvider.open_window()`, `open_batch()`, `TicketHandler.open_ticket()` (`WorkflowAction.OPENED`) |
| **3.5** | Closed Maintenance Notification Window (`COMPLETED`) | `MaintenanceProvider.close_window()`, `close_batch()`, `TicketHandler.close_ticket()` (`WorkflowAction.CLOSED`) |
| **4.1–4.5** | Verbatim draft examples | Tested directly in `tests/test_parser.py` and `tests/test_workflow.py` |
| **5.1** | Localization (`LANGUAGE` parameter, UTF-8 text, localized summary prefixes & email templates) | `LocalizationStrings`, `language` parameter support, UTF-8 octet-safe RFC 5545 line folding |
| **5.2** | Email + OpenPGP (RFC 3156 signing & raw-byte verification), CalDAV over TLS (RFC 4791 `PROPFIND`/`REPORT`/`GET`/`PUT`/`DELETE` + `ETag` + `prop-filter`), out-of-band verification | `maintnote.email_utils`, `CalDAVClient`, `OutOfBandVerifier` |

## Draft Quirks Handled Cleanly

1. **Table 2 typo (`X-MAINTENOTE-*`)**: Rejected in strict mode (`strict=True`), automatically mapped with a `LEGACY_TYPO_PROPERTY` warning in lenient mode (`strict=False`).
2. **Example 4.5 whitespace (`X-MAINTNOTE-STATUS: COMPLETED`)**: Trimmed cleanly to `Status.COMPLETED` while emitting a `WHITESPACE_VALUE` warning in diagnostics.
3. **Section 4 non-globally-unique UIDs (`UID:42`)**: Consumer state stores key records by `(provider, uid)` so identical simple UIDs from different providers never collide.
