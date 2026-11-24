"""Email/MIME, METHOD pre-processing, and RFC 3156 OpenPGP verification helpers.

Covers Section 2.3.1 (pre-processing to avoid unwanted human calendar auto-population),
Section 3 (routing iCalendar email attachments), and Section 5.2 (OpenPGP RFC 3156
authentication of maintenance notification emails).
"""

from __future__ import annotations

from dataclasses import dataclass
from email import message_from_bytes, message_from_string, policy
from email.message import EmailMessage, Message
from typing import Protocol, runtime_checkable

from maintnote.exceptions import ParseError, VerificationError
from maintnote.ical import parse_ical_components
from maintnote.models import MaintenanceNotification
from maintnote.parser import parse_calendar
from maintnote.serializer import dumps


@runtime_checkable
class OpenPGPVerifier(Protocol):
    """Protocol for verifying RFC 3156 ``multipart/signed`` OpenPGP signatures."""

    def verify(self, signed_payload: bytes, detached_signature: bytes) -> bool:
        """Return True if *detached_signature* is a valid OpenPGP signature over *signed_payload*."""


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
) -> EmailMessage:
    """Create a complete RFC 5322 email with plain-text body and ``.ics`` attachment."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject if subject is not None else notification.summary

    default_body = (
        f"Maintenance Notification: {notification.summary}\n"
        f"Provider: {notification.provider}\n"
        f"Account: {notification.account}\n"
        f"Maintenance ID: {notification.maintenance_id}\n"
        f"Window: {notification.dtstart.isoformat()} to {notification.dtend.isoformat()}\n"
        f"Impact: {notification.impact.raw}\n"
        f"Status: {notification.status.raw if notification.status is not None else 'UNSPECIFIED'}\n"
        f"Objects: {', '.join(notification.object_ids)}\n"
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


def extract_pgp_signed_parts(message: Message | bytes | str) -> PGPSignedParts | None:
    """Extract the signed payload and detached PGP signature from an RFC 3156 email.

    Returns ``None`` if the message is not ``multipart/signed`` with
    ``protocol="application/pgp-signature"``.
    """
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

    # Canonicalize signed entity line endings to CRLF per RFC 3156 Section 5
    signed_bytes = signed_entity.as_bytes(policy=policy.SMTP)
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
    msg = _coerce_message(message)

    if pgp_verifier is not None:
        verify_email_signature(msg, pgp_verifier, require_signature=require_pgp_signature)
    elif require_pgp_signature:
        raise VerificationError("require_pgp_signature=True requires a pgp_verifier")

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
