# Security & Transport

Section 2.3.1, Section 2.5.4, and Section 5.2 of the Internet-Draft discuss calendar interaction safety, external `ALTREP` metadata, email authentication with OpenPGP, CalDAV over TLS, and out-of-band verification.

## 1. Preventing Unwanted Calendar Auto-Population (Section 2.3.1)

By default, `maintnote` omits the `METHOD` calendar property when serializing notifications.
If an upstream provider sends `METHOD:PUBLISH` or `METHOD:REQUEST`, you can sanitize either raw `.ics` payloads or complete `.eml` messages (removing both `METHOD:` inside the `.ics` attachment and the `method=...` MIME `Content-Type` header parameter):

```python
from maintnote import (
    strip_method_from_ical,
    strip_method_from_email,
    extract_notifications_from_email,
)

safe_ical = strip_method_from_ical(raw_ical)
safe_email = strip_method_from_email(raw_email_bytes)
notifications = extract_notifications_from_email(raw_email_bytes, strip_method=True)
```

## 2. Email Authentication with OpenPGP (RFC 3156, Section 5.2)

`maintnote.email_utils` supports both **provider-side signing** (`OpenPGPSigner` + `sign_notification_email`) and **consumer-side raw-byte verification** (`OpenPGPVerifier` + `verify_email_signature`). When raw `bytes` or `str` input is passed to `extract_pgp_signed_parts` / `verify_email_signature`, the signed entity is sliced verbatim between the outer `multipart/signed` MIME boundaries (canonicalized to CRLF per RFC 3156 §5) so re-serialization cannot break cryptographic signatures:

```python
from maintnote import (
    build_notification_email,
    extract_notifications_from_email,
    sign_notification_email,
)

# Provider side: wrap outgoing email in RFC 3156 multipart/signed
eml = build_notification_email(notification, sender="noc@example.com", recipient="ops@client.example")
signed_eml = sign_notification_email(eml, signer=my_pgp_signer, micalg="pgp-sha256")

# Consumer side: verify raw bytes before parsing attachments
notifications = extract_notifications_from_email(
    signed_eml.as_bytes(),
    pgp_verifier=my_pgp_verifier,
    require_pgp_signature=True,
)
```

## 3. Pulling and Publishing via CalDAV over TLS (RFC 4791, Section 5.2)

`CalDAVClient` enforces HTTPS with TLS 1.2+ by default and supports `PROPFIND` collection discovery, `REPORT` queries with time-range & `X-MAINTNOTE-*` `<C:prop-filter>`s, single-resource `GET`, and `ETag` (`If-Match` / `If-None-Match`) concurrency control on `PUT`/`DELETE`:

```python
from datetime import datetime, timezone
from maintnote import CalDAVClient, Status

client = CalDAVClient(
    "https://caldav.example.com/calendars/maintenance/",
    bearer_token="...",
)

# Discover collection metadata & CTag
info = client.discover_collection()

# Pull events with ETag & server-side X-MAINTNOTE-* filtering
events = client.fetch_events(
    start=datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc),
    end=datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc),
    provider="example.com",
    status=Status.CONFIRMED,
)

# Fetch single resource or publish with optimistic concurrency
single = client.get_notification("maint-001.ics")
client.publish_notification(single.notifications[0], if_match=single.etag)
```

## 4. Hardened External `ALTREP` Metadata Retrieval (Section 2.5.4 & RFC 7159)

`fetch_altrep_metadata()` enforces HTTPS by default, re-validates every HTTP redirect hop against scheme downgrades and private/loopback IP addresses (`block_private_ips=True`), and caps response size (`max_bytes=5 MiB`):

```python
from maintnote import fetch_altrep_metadata

for obj in notification.objects:
    if obj.altrep:
        resource = fetch_altrep_metadata(obj)
        print(resource.data)
```

## 5. Out-of-Band Verification (Section 5.2)

Attach an `OutOfBandVerifier` to `MaintenanceConsumer` to verify notifications against an authoritative portal or API before executing automated actions.
