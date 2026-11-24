"""Tests for email/MIME helpers, METHOD stripping, and RFC 3156 OpenPGP hooks."""

from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart

import pytest

from maintnote.email_utils import (
    build_notification_email,
    extract_notifications_from_email,
    extract_pgp_signed_parts,
    strip_method_from_ical,
    verify_email_signature,
)
from maintnote.exceptions import VerificationError
from maintnote.models import Impact, MaintenanceNotification, Status
from maintnote.parser import parse
from maintnote.serializer import dumps


def _sample_notification() -> MaintenanceNotification:
    return MaintenanceNotification.create(
        uid="email-test-1@example.com",
        dtstart=datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc),
        summary="POP power maintenance",
        organizer="noc@example.com",
        provider="example.com",
        account="ACC-500",
        maintenance_id="WO-500",
        objects=["ckt-500"],
        impact=Impact.REDUCED_REDUNDANCY,
        status=Status.CONFIRMED,
        method="PUBLISH",
    )


def test_build_and_extract_email_roundtrip_and_method_stripping() -> None:
    notif = _sample_notification()
    msg = build_notification_email(
        notif,
        sender="noc@example.com",
        recipient="ops@customer.example",
        include_method=True,
    )
    raw_bytes = msg.as_bytes()

    extracted = extract_notifications_from_email(raw_bytes)
    assert len(extracted) == 1
    assert extracted[0].uid == notif.uid
    assert extracted[0].method == "PUBLISH"

    # Recipient pre-processing: strip METHOD per Section 2.3.1
    stripped = extract_notifications_from_email(raw_bytes, strip_method=True)
    assert len(stripped) == 1
    assert stripped[0].method is None


def test_strip_method_from_ical() -> None:
    ical = dumps(_sample_notification(), include_method=True, method="REQUEST")
    assert "METHOD:REQUEST" in ical
    cleaned = strip_method_from_ical(ical)
    assert "METHOD:" not in cleaned
    assert parse(cleaned).method is None


def test_rfc3156_openpgp_signature_verification() -> None:
    inner = build_notification_email(
        _sample_notification(),
        sender="noc@example.com",
        recipient="ops@customer.example",
    )

    signed = MIMEMultipart(
        "signed",
        micalg="pgp-sha256",
        protocol="application/pgp-signature",
    )
    signed["From"] = "noc@example.com"
    signed["To"] = "ops@customer.example"
    signed["Subject"] = "Signed Maintenance Notice"
    signed.attach(inner)

    sig_part = MIMEApplication(
        b"-----BEGIN PGP SIGNATURE-----\nFAKE-SIG\n-----END PGP SIGNATURE-----\n",
        _subtype="pgp-signature",
    )
    signed.attach(sig_part)

    parts = extract_pgp_signed_parts(signed)
    assert parts is not None
    assert parts.micalg == "pgp-sha256"
    assert b"FAKE-SIG" in parts.signature

    class AcceptingVerifier:
        def verify(self, signed_payload: bytes, detached_signature: bytes) -> bool:
            return b"X-MAINTNOTE-PROVIDER" in signed_payload and b"FAKE-SIG" in detached_signature

    class RejectingVerifier:
        def verify(self, signed_payload: bytes, detached_signature: bytes) -> bool:
            return False

    assert verify_email_signature(signed, AcceptingVerifier()) is True
    extracted = extract_notifications_from_email(
        signed, pgp_verifier=AcceptingVerifier(), require_pgp_signature=True
    )
    assert len(extracted) == 1

    with pytest.raises(VerificationError, match="verification failed"):
        extract_notifications_from_email(
            signed, pgp_verifier=RejectingVerifier(), require_pgp_signature=True
        )

    unsigned = EmailMessage()
    unsigned.set_content("Hello")
    with pytest.raises(VerificationError, match="not signed"):
        verify_email_signature(unsigned, AcceptingVerifier(), require_signature=True)
    assert verify_email_signature(unsigned, AcceptingVerifier(), require_signature=False) is False
