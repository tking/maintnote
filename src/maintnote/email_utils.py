"""Email/MIME, METHOD pre-processing, and RFC 3156 OpenPGP signing & verification helpers.

Covers Section 2.3.1 (pre-processing to avoid unwanted human calendar auto-population),
Section 3 (routing iCalendar email attachments), Section 5.1 (localization), and
Section 5.2 (OpenPGP RFC 3156 authentication of maintenance notification emails).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from email import message_from_bytes, message_from_string, policy
from email.message import EmailMessage, Message
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from typing import Protocol, runtime_checkable

from maintnote.exceptions import ParseError, VerificationError
from maintnote.ical import parse_ical_components
from maintnote.models import LocalizationStrings, MaintenanceNotification
from maintnote.parser import parse_calendar
from maintnote.serializer import dumps


@runtime_checkable
class OpenPGPVerifier(Protocol):
    """Protocol for verifying RFC 3156 ``multipart/signed`` OpenPGP signatures."""

    def verify(self, signed_payload: bytes, detached_signature: bytes) -> bool:
        """Return True if *detached_signature* is a valid OpenPGP signature over *signed_payload*."""


@runtime_checkable
class OpenPGPSigner(Protocol):
    """Protocol for producing detached OpenPGP signatures per RFC 3156 Section 5."""

    def sign(self, payload: bytes) -> bytes:
        """Return an ASCII-armored detached OpenPGP signature over canonical CRLF *payload*."""


@dataclass(frozen=True, slots=True)
class PGPSignedParts:
    """Extracted RFC 3156 ``multipart/signed`` body and detached OpenPGP signature."""

    signed_payload: bytes
    signature: bytes
    micalg: str | None = None


def strip_method_from_ical(ical_text: str) -> str:
    """Remove the ``METHOD`` property from a ``VCALENDAR`` object (Section 2.3.1).

    Recipients can apply this pre-processing step before delivering maintenance
    notifications to human calendaring systems so events do not auto-populate
    personal calendars unexpectedly.
    """
    components = parse_ical_components(ical_text)
    for comp in components:
        if comp.name == "VCALENDAR":
            comp.properties = [prop for prop in comp.properties if prop.name != "METHOD"]
    return "".join(comp.to_ical() for comp in components)


def strip_method_from_email(message: Message | bytes | str) -> Message:
    """Return a copy of *message* with ``METHOD`` removed from both MIME headers and ``.ics`` parts.

    Implements Section 2.3.1 email-level pre-processing so human calendaring clients
    do not treat forwarded maintenance emails as automatic scheduling transactions.
    """
    cloned = copy.deepcopy(_coerce_message(message))
    for part in cloned.walk():
        if part.is_multipart():
            continue
        content_type = part.get_content_type().lower()
        filename = (part.get_filename() or "").lower()
        if content_type != "text/calendar" and not filename.endswith(".ics"):
            continue

        # Remove MIME Content-Type `method=...` parameter if present
        if part.get_param("method") is not None:
            part.del_param("method")

        raw_payload = part.get_payload(decode=True)
        charset = part.get_content_charset() or "utf-8"
        if isinstance(raw_payload, bytes):
            ical_text = raw_payload.decode(charset, errors="replace")
        else:
            str_payload = part.get_payload()
            if not isinstance(str_payload, str):
                continue
            ical_text = str_payload

        cleaned = strip_method_from_ical(ical_text)
        # Preserve clean text payload and drop stale transfer encoding header if re-setting
        if "Content-Transfer-Encoding" in part:
            del part["Content-Transfer-Encoding"]
        part.set_payload(cleaned, charset=charset)

    return cloned


def attach_notification(
    message: EmailMessage,
    notification: MaintenanceNotification,
    *,
    filename: str = "maintenance.ics",
    include_method: bool | None = None,
    method: str | None = None,
) -> None:
    """Attach a :class:`MaintenanceNotification` as a ``text/calendar`` MIME part."""
    ical_str = dumps(notification, include_method=include_method, method=method)
    resolved_method: str | None = None
    if include_method is not False:
        resolved_method = (
            method.strip().upper()
            if method is not None
            else (
                notification.method.strip().upper()
                if notification.method is not None
                else ("PUBLISH" if include_method is True else None)
            )
        )

    params: dict[str, str] = {}
    if resolved_method is not None:
        params["method"] = resolved_method

    message.add_attachment(
        ical_str,
        subtype="calendar",
        charset="utf-8",
        filename=filename,
        params=params,
    )


def build_notification_email(
    notification: MaintenanceNotification,
    *,
    sender: str,
    recipient: str,
    body: str | None = None,
    subject: str | None = None,
    filename: str = "maintenance.ics",
    include_method: bool | None = None,
    method: str | None = None,
    localization: LocalizationStrings | None = None,
) -> EmailMessage:
    """Create a complete RFC 5322 email with plain-text body and ``.ics`` attachment."""
    loc = localization or LocalizationStrings()
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject if subject is not None else notification.summary

    status_label = (
        notification.status.raw if notification.status is not None else loc.email_status_unspecified
    )
    default_body = (
        f"{loc.email_title}: {notification.summary}\n"
        f"{loc.email_provider}: {notification.provider}\n"
        f"{loc.email_account}: {notification.account}\n"
        f"{loc.email_maintenance_id}: {notification.maintenance_id}\n"
        f"{loc.email_window}: {notification.dtstart.isoformat()} "
        f"{loc.email_window_separator} {notification.dtend.isoformat()}\n"
        f"{loc.email_impact}: {notification.impact.raw}\n"
        f"{loc.email_status}: {status_label}\n"
        f"{loc.email_objects}: {', '.join(notification.object_ids)}\n"
    )
    msg.set_content(body if body is not None else default_body)
    attach_notification(
        msg,
        notification,
        filename=filename,
        include_method=include_method,
        method=method,
    )
    return msg


def sign_notification_email(
    message: Message,
    signer: OpenPGPSigner,
    *,
    micalg: str = "pgp-sha256",
) -> MIMEMultipart:
    """Wrap *message* in an RFC 3156 ``multipart/signed`` OpenPGP envelope (Section 5.2).

    Copies top-level transport headers (``From``, ``To``, ``Cc``, ``Subject``,
    ``Date``, ``Message-ID``) onto the outer signed envelope and computes the
    detached OpenPGP signature over the canonical CRLF MIME entity bytes.
    """
    inner = copy.deepcopy(message)
    outer = MIMEMultipart(
        "signed",
        micalg=micalg,
        protocol="application/pgp-signature",
    )
    for header in ("From", "To", "Cc", "Subject", "Date", "Message-ID"):
        if header in inner:
            outer[header] = inner[header]
            del inner[header]

    canonical_payload = _canonicalize_crlf(inner.as_bytes(policy=policy.SMTP))
    detached_sig = signer.sign(canonical_payload)

    outer.attach(inner)
    sig_part = MIMEApplication(
        detached_sig,
        _subtype="pgp-signature",
        name="signature.asc",
    )
    sig_part.add_header("Content-Description", "OpenPGP digital signature")
    outer.attach(sig_part)
    return outer


def extract_pgp_signed_parts(message: Message | bytes | str) -> PGPSignedParts | None:
    """Extract the signed payload and detached PGP signature from an RFC 3156 email.

    When raw ``bytes`` or ``str`` input is provided, the signed entity is sliced
    verbatim from the raw bytes between the outer ``multipart/signed`` boundary
    delimiters (canonicalized to CRLF per RFC 3156 §5) so re-serialization cannot
    invalidate the cryptographic signature.

    Returns ``None`` if the message is not ``multipart/signed`` with
    ``protocol="application/pgp-signature"``.
    """
    raw_bytes: bytes | None = None
    if isinstance(message, bytes):
        raw_bytes = message
    elif isinstance(message, str):
        raw_bytes = message.encode("utf-8")

    msg = _coerce_message(message)
    if msg.get_content_type().lower() != "multipart/signed":
        return None

    raw_protocol = msg.get_param("protocol")
    protocol = (
        raw_protocol[2] if isinstance(raw_protocol, tuple) else (raw_protocol or "")
    ).lower()
    if protocol != "application/pgp-signature":
        return None

    parts = msg.get_payload()
    if not isinstance(parts, list) or len(parts) != 2:
        raise ParseError("RFC 3156 multipart/signed message must contain exactly 2 MIME parts")

    signed_entity, sig_entity = parts[0], parts[1]
    if not isinstance(signed_entity, Message) or not isinstance(sig_entity, Message):
        raise ParseError("RFC 3156 multipart/signed parts must be valid MIME messages")

    if sig_entity.get_content_type().lower() != "application/pgp-signature":
        raise ParseError(
            f"Expected second multipart/signed part to be application/pgp-signature, "
            f"got {sig_entity.get_content_type()!r}"
        )

    signed_bytes: bytes | None = None
    boundary = msg.get_boundary()
    if raw_bytes is not None and boundary:
        signed_bytes = _slice_raw_signed_entity(raw_bytes, boundary)

    if signed_bytes is None:
        # Fallback when caller passed an already-constructed in-memory Message
        signed_bytes = _canonicalize_crlf(signed_entity.as_bytes(policy=policy.SMTP))

    sig_payload = sig_entity.get_payload(decode=True)
    if not isinstance(sig_payload, bytes):
        raw_sig = sig_entity.get_payload()
        sig_payload = raw_sig.encode("utf-8") if isinstance(raw_sig, str) else b""

    raw_micalg = msg.get_param("micalg")
    micalg = (
        raw_micalg[2]
        if isinstance(raw_micalg, tuple)
        else (str(raw_micalg) if raw_micalg is not None else None)
    )
    return PGPSignedParts(
        signed_payload=signed_bytes,
        signature=sig_payload,
        micalg=micalg,
    )


def verify_email_signature(
    message: Message | bytes | str,
    verifier: OpenPGPVerifier,
    *,
    require_signature: bool = True,
) -> bool:
    """Verify an email's RFC 3156 OpenPGP signature using *verifier* (Section 5.2).

    Raises :class:`VerificationError` if verification fails or if
    ``require_signature=True`` and the message is unsigned.
    """
    signed_parts = extract_pgp_signed_parts(message)
    if signed_parts is None:
        if require_signature:
            raise VerificationError("Email is not signed with RFC 3156 OpenPGP multipart/signed")
        return False

    if not verifier.verify(signed_parts.signed_payload, signed_parts.signature):
        raise VerificationError("OpenPGP signature verification failed")
    return True


def extract_notifications_from_email(
    message: Message | bytes | str,
    *,
    strict: bool = True,
    strip_method: bool = False,
    pgp_verifier: OpenPGPVerifier | None = None,
    require_pgp_signature: bool = False,
) -> list[MaintenanceNotification]:
    """Extract and parse all maintenance notifications attached to an email message."""
    if pgp_verifier is not None:
        verify_email_signature(message, pgp_verifier, require_signature=require_pgp_signature)
    elif require_pgp_signature:
        raise VerificationError("require_pgp_signature=True requires a pgp_verifier")

    msg = _coerce_message(message)

    notifications: list[MaintenanceNotification] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        content_type = part.get_content_type().lower()
        filename = (part.get_filename() or "").lower()
        is_calendar = content_type == "text/calendar" or filename.endswith(".ics")
        if not is_calendar:
            continue

        raw_payload = part.get_payload(decode=True)
        if isinstance(raw_payload, bytes):
            charset = part.get_content_charset() or "utf-8"
            ical_text = raw_payload.decode(charset, errors="replace")
        else:
            str_payload = part.get_payload()
            if not isinstance(str_payload, str):
                continue
            ical_text = str_payload

        if strip_method:
            ical_text = strip_method_from_ical(ical_text)

        doc = parse_calendar(ical_text, strict=strict)
        notifications.extend(doc.notifications)

    return notifications


def _coerce_message(message: Message | bytes | str) -> Message:
    if isinstance(message, Message):
        return message
    if isinstance(message, bytes):
        return message_from_bytes(message, policy=policy.default)
    return message_from_string(message, policy=policy.default)


def _canonicalize_crlf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n").replace(b"\n", b"\r\n")


def _slice_raw_signed_entity(raw_bytes: bytes, boundary: str) -> bytes | None:
    """Extract the exact raw signed MIME entity between the first two boundary markers."""
    canonical = _canonicalize_crlf(raw_bytes)
    delim = b"--" + boundary.encode("ascii", errors="ignore")
    first = canonical.find(delim + b"\r\n")
    if first == -1:
        return None
    start = first + len(delim) + 2  # skip first delimiter + CRLF
    second = canonical.find(b"\r\n" + delim, start)
    if second == -1:
        return None
    # Per RFC 3156 Section 5, the CRLF preceding the second boundary belongs to the delimiter,
    # NOT to the signed entity.
    return canonical[start:second]
