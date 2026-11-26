# API Reference

Import any public symbol directly from the top-level `maintnote` package.
For CLI subcommands and flags, see [Getting Started](getting-started.md#run-the-command-line-interface).

## Models (`maintnote.models`)

- **`Impact`** (`Enum`): Defines `NO_IMPACT`, `REDUCED_REDUNDANCY`, `DEGRADED`, and `OUTAGE`. Use `.severity` (`0` to `3`) and `Impact.worst(*impacts)` to compare severity.
- **`ImpactValue`**: Stores a standard or custom (`x-name` or `iana-token`) `X-MAINTNOTE-IMPACT` value and its parameters. `.effective` returns `Impact.OUTAGE` for unknown values (Section 2.5.5).
- **`Status`** (`Enum`): Defines `TENTATIVE`, `CONFIRMED`, `CANCELLED`, `IN-PROCESS`, and `COMPLETED`.
- **`StatusValue`**: Stores a standard or custom (`x-name` or `iana-token`) `X-MAINTNOTE-STATUS` value and its parameters.
- **`LocalizationStrings`**: Configures localized summary prefixes (`open_prefix`, `closed_prefix`) and email body labels (Section 5.1).
- **`Organizer`**: Represents the `ORGANIZER` property (`address`, `cn`, `params`, and `.email`). Adds `mailto:` to bare email addresses automatically.
- **`ServiceObject`**: Represents one `X-MAINTNOTE-OBJECT-ID` entry (`object_id`, `altrep`, `language`, `params`, and `.scoped_id(provider)`).
- **`MaintenanceNotification`**: Frozen dataclass for one maintenance notification. Provides `MaintenanceNotification.create(...)`, `.duration`, `.effective_impact`, `.standard_status`, `.is_tentative`, `.is_confirmed`, `.is_cancelled`, `.is_open`, `.is_closed`, `.scoped_object_ids`, `.with_updates(...)`, `.to_dict()`, `extra_*_properties`, and `extra_*_subcomponents`.
- **`CalendarDocument`**: Container for a `VCALENDAR` with one or more `MaintenanceNotification` objects. Keeps `extra_calendar_properties` and `extra_calendar_subcomponents`.

## Parsing, Validation, and Serialization (`maintnote.parser`, `maintnote.serializer`, `maintnote.ical`)

- **`parse(ical_text, *, strict=True) -> MaintenanceNotification`**: Parse a single-event `.ics` payload.
- **`parse_calendar(ical_text, *, strict=True) -> CalendarDocument`**: Parse a single-event or multi-event `VCALENDAR` payload.
- **`parse_with_diagnostics(ical_text, *, strict=True) -> ParseResult`**: Parse a payload and return structured warnings in `.warnings`.
- **`load(fp, *, strict=True) -> MaintenanceNotification`**: Parse a single-event `.ics` payload from a file-like object.
- **`validate(notification) -> list[ValidationIssue]`**: Validate a `MaintenanceNotification` and return all error and warning issues.
- **`dumps(notification, *, include_method=None, method=None, fold_lines=True, validate_before_dump=True) -> str`**: Serialize a notification to an RFC 5545 string.
- **`dumps_calendar(document, ...) -> str`**: Serialize a `CalendarDocument` to an RFC 5545 string.
- **`dump(notification, fp, ...) -> None`**: Write a serialized notification to a file-like object.
- **`ContentLine`**, **`ICalComponent`**: Low-level iCalendar line and component models for custom properties and subcomponents.

## Workflow Engine (`maintnote.workflow`)

- **`MaintenanceProvider`**: Creates and transitions single notifications and multi-account batches. Methods: `.create_initial(...)`, `.create_batch_initial(...)`, `.get_batch(...)`, `.update_window(...)`, `.update_batch(...)`, `.confirm(...)`, `.confirm_batch(...)`, `.cancel(...)`, `.cancel_batch(...)`, `.open_window(...)`, `.open_batch(...)`, `.close_window(...)`, `.close_batch(...)`, and `.set_recipient_preference(...)`.
- **`RecipientPreference`**: Configures per-account `METHOD` behavior (`include_method`, `method`, and `cancel_method`).
- **`MaintenanceConsumer`**: Processes received notifications with `.process(incoming, *, strict=True) -> ProcessingResult`. Tracks `(provider, uid)` and `SEQUENCE`, and skips no-change ticket edits when `skip_noop_ticket_updates=True`.
- **`StateStore`**, **`InMemoryStateStore`**, **`SQLiteStateStore`**, **`TrackedMaintenance`**: Storage protocol and built-in stores keyed by `(provider, uid)`.
- **`TicketHandler`**, **`InMemoryTicketHandler`**, **`TicketRecord`**, **`TicketPriority`**: Ticketing protocol, reference adapter, and priority mapping.
- **`OutOfBandVerifier`**, **`WorkflowAction`**, **`NotificationDiff`**, **`compute_diff(...)`**: Verification hook, workflow outcomes, and structured field diffs.

## Email and OpenPGP (`maintnote.email_utils`)

- **`build_notification_email(..., localization=...) -> EmailMessage`**: Build an RFC 5322 email with a plain-text summary and `.ics` attachment.
- **`attach_notification(...) -> None`**: Attach a `MaintenanceNotification` to an existing `EmailMessage`.
- **`extract_notifications_from_email(...) -> list[MaintenanceNotification]`**: Extract and parse all `.ics` attachments from an email, with optional OpenPGP verification and `METHOD` removal.
- **`strip_method_from_ical(ical_text) -> str`**: Remove `METHOD` from raw iCalendar text.
- **`strip_method_from_email(message) -> Message`**: Remove `METHOD` from both MIME headers and `.ics` parts in an email.
- **`sign_notification_email(message, signer, *, micalg="pgp-sha256") -> MIMEMultipart`**: Wrap an email in an RFC 3156 `multipart/signed` OpenPGP envelope.
- **`extract_pgp_signed_parts(message) -> PGPSignedParts | None`**: Extract the raw signed payload and detached signature from an RFC 3156 email.
- **`verify_email_signature(message, verifier, *, require_signature=True) -> bool`**: Verify an RFC 3156 OpenPGP signature.
- **`OpenPGPSigner`**, **`OpenPGPVerifier`**, **`PGPSignedParts`**: Signing and verification protocols and extracted signature container.

## `ALTREP` and CalDAV (`maintnote.transport`)

- **`fetch_altrep_metadata(service_object, *, timeout=10.0, allowed_schemes=("https",), block_private_ips=True, max_bytes=..., ...) -> AltrepResource`**: Get external `ALTREP` metadata over HTTPS with redirect, SSRF, and size checks.
- **`CalDAVClient`**: TLS-enforced CalDAV client with `.discover_collection()`, `.fetch_events(...)`, `.fetch_notifications(...)`, `.get_notification(...)`, `.publish_notification(..., if_match=..., if_none_match=...)`, and `.delete_notification(..., if_match=...)`.
- **`CalDAVEvent`**, **`CalDAVCollectionInfo`**, **`AltrepResource`**: Result dataclasses for CalDAV and `ALTREP` operations.

## Exceptions (`maintnote.exceptions`)

All library exceptions inherit from `MaintNoteError`:

- `ICalSyntaxError`: Invalid RFC 5545 syntax.
- `ParseError`: Absent or malformed iCalendar structure.
- `ValidationError`: Specification rule violation (contains `.issues: tuple[ValidationIssue, ...]`).
- `WorkflowError` (and subclass `SequenceError`): Invalid lifecycle transition or sequence error.
- `VerificationError`: Failed OpenPGP or out-of-band verification.
- `TransportError`: Network, TLS, SSRF, `ALTREP`, or CalDAV failure.
