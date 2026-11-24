# Security & Transport

Section 2.3.1, Section 2.5.4, and Section 5.2 of the Internet-Draft discuss calendar interaction safety, external `ALTREP` metadata, email authentication with OpenPGP, CalDAV over TLS, and out-of-band verification.

## 1. Preventing Unwanted Calendar Auto-Population (Section 2.3.1)

By default, `maintnote` omits the `METHOD` calendar property when serializing notifications.
If an upstream provider sends `METHOD:PUBLISH` or `METHOD:REQUEST` and you want to prevent notifications from auto-populating personal calendars, strip `METHOD` before forwarding:

```python
from maintnote import strip_method_from_ical, extract_notifications_from_email

safe_ical = strip_method_from_ical(raw_ical)
notifications = extract_notifications_from_email(raw_email_bytes, strip_method=True)
```

## 2. Email Authentication with OpenPGP (RFC 3156, Section 5.2)

`maintnote.email_utils` extracts RFC 3156 `multipart/signed` (`protocol="application/pgp-signature"`) payloads and delegates cryptographic verification to any implementation of `OpenPGPVerifier` (e.g., `python-gnupg`, `sequoia`, or `gpgme`):

```python
from maintnote import extract_notifications_from_email

class GPGVerifier:
    def verify(self, signed_payload: bytes, detached_signature: bytes) -> bool:
        # Delegate to your OpenPGP implementation
        return verify_with_gpg(signed_payload, detached_signature)

notifications = extract_notifications_from_email(
    raw_email_bytes,
    pgp_verifier=GPGVerifier(),
    require_pgp_signature=True,
)
```

## 3. Pulling and Publishing via CalDAV over TLS (RFC 4791, Section 5.2)

`CalDAVClient` enforces HTTPS with TLS 1.2+ by default:

```python
from datetime import datetime, timezone
from maintnote import CalDAVClient

client = CalDAVClient(
    "https://caldav.example.com/calendars/maintenance/",
    bearer_token="...",
)

# Pull notifications for a time window via CalDAV REPORT
events = client.fetch_notifications(
    start=datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc),
    end=datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc),
)

# Publish / update a notification via PUT
client.publish_notification(events[0])
```

## 4. External `ALTREP` Metadata (Section 2.5.4 & RFC 7159)

Service objects may link structured JSON metadata (such as PeeringDB API endpoints) via the `ALTREP` parameter:

```python
from maintnote import fetch_altrep_metadata

for obj in notification.objects:
    if obj.altrep:
        resource = fetch_altrep_metadata(obj)  # HTTPS only by default
        print(resource.data)
```

## 5. Out-of-Band Verification (Section 5.2)

Before executing automated remediation or ticketing actions, attach an `OutOfBandVerifier` to `MaintenanceConsumer` to cross-check incoming notifications against an authoritative portal/API:

```python
from maintnote import MaintenanceConsumer

class PortalVerifier:
    def verify(self, notification) -> bool:
        return portal_api.maintenance_exists(
            provider=notification.provider,
            maintenance_id=notification.maintenance_id,
        )

consumer = MaintenanceConsumer(verifier=PortalVerifier())
```
