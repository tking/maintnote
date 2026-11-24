# API Reference

All public symbols are re-exported from the top-level `maintnote` package.

## Models (`maintnote.models`)

- **`Impact`** (`Enum`): `NO_IMPACT`, `REDUCED_REDUNDANCY`, `DEGRADED`, `OUTAGE`. Provides `.severity` (`0..3`) and `Impact.worst(*impacts)`.
- **`ImpactValue`**: Wraps standard or custom (`x-name`/`iana-token`) `X-MAINTNOTE-IMPACT` values with optional property parameters. `.effective` returns `Impact.OUTAGE` for unrecognized custom values (Section 2.5.5).
- **`Status`** (`Enum`): `TENTATIVE`, `CONFIRMED`, `CANCELLED`, `IN_PROCESS`, `COMPLETED`.
- **`StatusValue`**: Wraps standard or custom (`x-name`/`iana-token`) `X-MAINTNOTE-STATUS` values with optional property parameters.
- **`LocalizationStrings`**: Configurable localized prefixes (`open_prefix`, `closed_prefix`) and email body labels (Section 5.1).
- **`Organizer`**: Represents `ORGANIZER` (`address`, `cn`, `params`, `.email`). Automatically prefixes bare emails with `mailto:`.
- **`ServiceObject`**: Represents `X-MAINTNOTE-OBJECT-ID` (`object_id`, `altrep`, `language`, `params`, `.scoped_id(provider)`).
- **`MaintenanceNotification`**: Frozen dataclass representing a complete notification (`MaintenanceNotification.create(...)`, `.duration`, `.effective_impact`, `.standard_status`, `.is_tentative`, `.is_confirmed`, `.is_cancelled`, `.is_open`, `.is_closed`, `.scoped_object_ids`, `.with_updates(...)`, `.to_dict()`, plus `extra_*_properties` and `extra_*_subcomponents`).
- **`CalendarDocument`**: Multi-event `VCALENDAR` container preserving `extra_calendar_properties` and `extra_calendar_subcomponents`.

## Parsing, Validation & Serialization (`maintnote.parser`, `maintnote.serializer`, `maintnote.ical`)

- **`parse(ical_text, *, strict=True) -> MaintenanceNotification`**
- **`parse_calendar(ical_text, *, strict=True) -> CalendarDocument`**
- **`parse_with_diagnostics(ical_text, *, strict=True) -> ParseResult`**
- **`load(fp, *, strict=True) -> MaintenanceNotification`**
- **`validate(notification) -> list[ValidationIssue]`**
- **`dumps(notification, *, include_method=None, method=None, fold_lines=True, validate_before_dump=True) -> str`**
- **`dumps_calendar(document, ...) -> str`**
- **`dump(notification, fp, ...) -> None`**
- **`ContentLine`**, **`ICalComponent`**

## Workflow Engine (`maintnote.workflow`)

- **`MaintenanceProvider`**: Single & stateful batch lifecycle methods: `.create_initial(...)`, `.create_batch_initial(...)`, `.get_batch(...)`, `.update_window(...)`, `.update_batch(...)`, `.confirm(...)`, `.confirm_batch(...)`, `.cancel(...)`, `.cancel_batch(...)`, `.open_window(...)`, `.open_batch(...)`, `.close_window(...)`, `.close_batch(...)`, `.set_recipient_preference(...)`. Supports `LocalizationStrings`.
- **`RecipientPreference`**: Per-recipient `METHOD` delivery policy (`include_method`, `method`, `cancel_method`).
- **`MaintenanceConsumer`**: `.process(incoming, *, strict=True) -> ProcessingResult` with `(provider, uid)` correlation, monotonic `SEQUENCE` tracking, and `skip_noop_ticket_updates=True` (`WorkflowAction.NO_OP_UPDATE`).
- **`StateStore`**, **`InMemoryStateStore`**, **`SQLiteStateStore`** (composite `(provider, uid)` primary key), **`TrackedMaintenance`**.
- **`TicketHandler`**, **`InMemoryTicketHandler`**, **`TicketRecord`**, **`TicketPriority`**.
- **`OutOfBandVerifier`**, **`WorkflowAction`**, **`NotificationDiff`**, **`compute_diff(...)`**.

## Email & OpenPGP (`maintnote.email_utils`)

- **`build_notification_email(..., localization=...) -> EmailMessage`**
- **`attach_notification(...) -> None`**
- **`extract_notifications_from_email(...) -> list[MaintenanceNotification]`**
- **`strip_method_from_ical(ical_text) -> str`**
- **`strip_method_from_email(message) -> Message`**
- **`sign_notification_email(message, signer, *, micalg="pgp-sha256") -> MIMEMultipart`**
- **`extract_pgp_signed_parts(message) -> PGPSignedParts | None`** (raw-byte boundary slicing for `bytes`/`str`)
- **`verify_email_signature(message, verifier, *, require_signature=True) -> bool`**
- **`OpenPGPSigner`**, **`OpenPGPVerifier`**, **`PGPSignedParts`**

## ALTREP & CalDAV (`maintnote.transport`)

- **`fetch_altrep_metadata(service_object, *, timeout=10.0, allowed_schemes=("https",), block_private_ips=True, max_bytes=..., ...) -> AltrepResource`**
- **`CalDAVClient`**: `.discover_collection() -> CalDAVCollectionInfo`, `.fetch_events(...) -> list[CalDAVEvent]`, `.fetch_notifications(...) -> list[MaintenanceNotification]`, `.get_notification(...) -> CalDAVEvent`, `.publish_notification(..., if_match=..., if_none_match=...)`, `.delete_notification(..., if_match=...)`.
- **`CalDAVEvent`**, **`CalDAVCollectionInfo`**, **`AltrepResource`**

## Exceptions (`maintnote.exceptions`)

`MaintNoteError` (base) → `ICalSyntaxError`, `ParseError`, `ValidationError` (carries `.issues: tuple[ValidationIssue, ...]`), `WorkflowError` → `SequenceError`, `VerificationError`, `TransportError`.
