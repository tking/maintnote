"""Example: RFC 3156 OpenPGP email signing/verification and METHOD sanitization.

Demonstrates:
- Wrapping a maintenance email in RFC 3156 multipart/signed (Section 5.2)
- Raw-byte signature verification before parsing attached notifications
- Detecting tampered emails with VerificationError
- Sanitizing upstream METHOD:REQUEST emails before forwarding to human calendars (Section 2.3.1)

Note: Uses a deterministic stdlib HMAC demo signer/verifier so this example runs
offline without requiring a local GPG keyring. In production, delegate ``sign()``
and ``verify()`` to ``gpg --detach-sign --armor`` / ``gpg --verify`` or PGPy.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

from maintnote import (
    Impact,
    MaintenanceProvider,
    Organizer,
    VerificationError,
    build_notification_email,
    extract_notifications_from_email,
    extract_pgp_signed_parts,
    sign_notification_email,
    strip_method_from_email,
    verify_email_signature,
)


class DemoPGPSignerVerifier:
    """Self-contained demo implementation of OpenPGPSigner and OpenPGPVerifier."""

    def __init__(self, shared_secret: bytes) -> None:
        self._secret = shared_secret

    def sign(self, payload: bytes) -> bytes:
        digest = hmac.new(self._secret, payload, hashlib.sha256).hexdigest()
        return (
            f"-----BEGIN PGP SIGNATURE-----\n\n{digest}\n-----END PGP SIGNATURE-----\n".encode(
                "ascii"
            )
        )

    def verify(self, signed_payload: bytes, detached_signature: bytes) -> bool:
        expected = self.sign(signed_payload)
        return hmac.compare_digest(expected.strip(), detached_signature.strip())


def main() -> None:
    provider = MaintenanceProvider(
        provider="ixp.example.org",
        organizer=Organizer("noc@ixp.example.org", cn="Example IXP NOC"),
    )
    notif = provider.create_initial(
        account="AS64496",
        maintenance_id="IXP-2026-09",
        objects=["ixp-switch-fra2-port48"],
        dtstart=datetime(2026, 12, 10, 3, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 12, 10, 5, 0, tzinfo=timezone.utc),
        summary="FRA2 peering switch OS upgrade",
        impact=Impact.OUTAGE,
    )

    crypto = DemoPGPSignerVerifier(shared_secret=b"demo-ixp-signing-key")

    print("=== 1. Provider builds and signs RFC 3156 multipart/signed email ===")
    raw_msg = build_notification_email(
        notif,
        sender="noc@ixp.example.org",
        recipient="peering-ops@member.example",
    )
    signed_msg = sign_notification_email(raw_msg, signer=crypto, micalg="pgp-sha256")
    signed_bytes = signed_msg.as_bytes()

    parts = extract_pgp_signed_parts(signed_bytes)
    assert parts is not None
    print(f"  micalg={parts.micalg} signed_payload_bytes={len(parts.signed_payload)}")

    print("\n=== 2. Consumer verifies signature and extracts notification ===")
    verified = verify_email_signature(signed_bytes, verifier=crypto, require_signature=True)
    extracted = extract_notifications_from_email(
        signed_bytes,
        pgp_verifier=crypto,
        require_pgp_signature=True,
    )
    print(f"  signature_valid={verified} extracted_count={len(extracted)} uid={extracted[0].uid}")

    print("\n=== 3. Tampered payload is rejected before parsing ===")
    tampered_bytes = signed_bytes.replace(b"OUTAGE", b"NO-IMPACT")
    try:
        extract_notifications_from_email(
            tampered_bytes,
            pgp_verifier=crypto,
            require_pgp_signature=True,
        )
    except VerificationError as exc:
        print(f"  Tampering detected as expected: {exc}")

    print("\n=== 4. Sanitize upstream METHOD:REQUEST email for human calendars (Section 2.3.1) ===")
    upstream_with_method = build_notification_email(
        notif,
        sender="noc@ixp.example.org",
        recipient="engineers@member.example",
        include_method=True,
        method="REQUEST",
    )
    raw_upstream = upstream_with_method.as_bytes()
    sanitized = strip_method_from_email(raw_upstream)
    sanitized_bytes = sanitized.as_bytes()
    before_mime_method = any(
        part.get_param("method") is not None for part in upstream_with_method.walk()
    )
    after_mime_method = any(part.get_param("method") is not None for part in sanitized.walk())
    print(
        f"  before: has_METHOD_prop={b'METHOD:REQUEST' in raw_upstream} "
        f"has_mime_method={before_mime_method}"
    )
    print(
        f"  after:  has_METHOD_prop={b'METHOD:' in sanitized_bytes} "
        f"has_mime_method={after_mime_method}"
    )


if __name__ == "__main__":
    main()
