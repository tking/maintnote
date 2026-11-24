# API Reference

All public symbols are re-exported from the top-level `maintnote` package.

## Models (`maintnote.models`)

- **`Impact`** (`Enum`): `NO_IMPACT`, `REDUCED_REDUNDANCY`, `DEGRADED`, `OUTAGE`. Provides `.severity` (`0..3`) and `Impact.worst(*impacts)`.
- **`ImpactValue`**: Wraps standard or custom (`x-name`/`iana-token`) `X-MAINTNOTE-IMPACT` values with optional property parameters. `.effective` returns `Impact.OUTAGE` for unrecognized custom values (Section 2.5.5).
- **`Status`** (`Enum`): `TENTATIVE`, `CONFIRMED`, `CANCELLED`, `IN_PROCESS`, `COMPLETED`.
- **`StatusValue`**: Wraps standard or custom (`x-name`/`iana-token`) `X-MAINTNOTE-STATUS` values with optional property parameters.
- **`Organizer`**: Represents `ORGANIZER` (`address`, `cn`, `params`, `.email`). Automatically prefixes bare emails with `mailto:`.
- **`ServiceObject`**: Represents `X-MAINTNOTE-OBJECT-ID` (`object_id`, `altrep`, `language`, `params`, `.scoped_id(provider)`).
- **`MaintenanceNotification`**: Frozen dataclass representing a complete notification (`MaintenanceNotification.create(...)`, `.duration`, `.effective_impact`, `.standard_status`, `.is_tentative`, `.is_confirmed`, `.is_cancelled`, `.is_open`, `.is_closed`, `.scoped_object_ids`, `.with_updates(...)`, `.to_dict()`).
- **`CalendarDocument`**: Multi-event `VCALENDAR` container.

## Parsing, Validation & Serialization (`maintnote.parser`, `maintnote.serializer`)

- **`parse(ical_text, *, strict=True) -> MaintenanceNotification`**
- **`parse_calendar(ical_text, *, strict=True) -> CalendarDocument`**
- **`parse_with_diagnostics(ical_text, *, strict=True) -> ParseResult`**
- **`load(fp, *, strict=True) -> MaintenanceNotification`**
- **`validate(notification) -> list[ValidationIssue]`**
- **`dumps(notification, *, include_method=None, method=None, fold_lines=True, validate_before_dump=True) -> str`**
- **`dumps_calendar(document, ...) -> str`**
- **`dump(notification, fp, ...) -> None`**

## Workflow Engine (`maintnote.workflow`)

- **`MaintenanceProvider`**: `.create_initial(...)`, `.create_batch_initial(...)`, `.update_window(...)`, `.confirm(...)`, `.cancel(...)`, `.open_window(...)`, `.close_window(...)`, `.set_recipient_preference(...)`.
- **`RecipientPreference`**: Per-recipient `METHOD` delivery policy (`include_method`, `method`, `cancel_method`).
- **`MaintenanceConsumer`**: `.process(incoming, *, strict=True) -> ProcessingResult`.
- **`StateStore`**, **`InMemoryStateStore`**, **`SQLiteStateStore`**, **`TrackedMaintenance`**.
- **`TicketHandler`**, **`InMemoryTicketHandler`**, **`TicketRecord`**, **`TicketPriority`**.
- **`OutOfBandVerifier`**, **`WorkflowAction`**, **`NotificationDiff`**, **`compute_diff(...)`**.

## Email & OpenPGP (`maintnote.email_utils`)

- **`build_notification_email(...) -> EmailMessage`**
- **`attach_notification(...) -> None`**
- **`extract_notifications_from_email(...) -> list[MaintenanceNotification]`**
- **`strip_method_from_ical(ical_text) -> str`**
- **`extract_pgp_signed_parts(message) -> PGPSignedParts | None`**
- **`verify_email_signature(message, verifier, *, require_signature=True) -> bool`**
- **`OpenPGPVerifier`**, **`PGPSignedParts`**

## ALTREP & CalDAV (`maintnote.transport`)

- **`fetch_altrep_metadata(service_object, *, timeout=10.0, allowed_schemes=("https",), ...) -> AltrepResource`**
- **`CalDAVClient`**: `.fetch_notifications(...)`, `.publish_notification(...)`, `.delete_notification(...)`.

## Exceptions (`maintnote.exceptions`)

`MaintNoteError` (base) → `ICalSyntaxError`, `ParseError`, `ValidationError` (carries `.issues: tuple[ValidationIssue, ...]`), `WorkflowError` → `SequenceError`, `VerificationError`, `TransportError`.
