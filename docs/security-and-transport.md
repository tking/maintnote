# Security and Transport

Maintenance notifications can trigger automated actions such as BGP session drains, incident tickets, or deployment freezes.
Because of this risk, Sections 2.3.1, 2.5.4, and 5.2 define strict calendar, email, metadata, and transport controls.

## 1. Prevent Automatic Calendar Entries (Section 2.3.1)

Many email clients automatically add `.ics` attachments to personal calendars when the `METHOD` property is present.
To prevent unwanted calendar entries, `maintnote` omits `METHOD` by default when it serializes a notification.

If an upstream provider sends `METHOD:PUBLISH` or `METHOD:REQUEST`, remove `METHOD` before you forward the notification to users:

```python
from maintnote import (
    extract_notifications_from_email,
    strip_method_from_email,
    strip_method_from_ical,
)

safe_ical = strip_method_from_ical(raw_ical)
safe_email = strip_method_from_email(raw_email_bytes)
notifications = extract_notifications_from_email(raw_email_bytes, strip_method=True)
```

`strip_method_from_email()` removes both the `METHOD:` line in the `.ics` attachment and the `method=...` parameter in the MIME `Content-Type` header.

## 2. Sign and Verify Emails with OpenPGP (RFC 3156, Section 5.2)

Email headers alone do not prove that a notification came from a trusted provider.
`maintnote.email_utils` supports RFC 3156 `multipart/signed` OpenPGP signatures for both providers and consumers.

!!! warning
    Pass raw `bytes` or `str` input to `extract_notifications_from_email()` or `verify_email_signature()`.
    If you parse and serialize the email before verification, whitespace or header changes can break the OpenPGP signature.

`maintnote` extracts the signed entity directly from the raw MIME boundaries and sets line endings to CRLF (RFC 3156 Section 5).

```python
from maintnote import (
    build_notification_email,
    extract_notifications_from_email,
    sign_notification_email,
)

# Provider side: wrap the email in an RFC 3156 multipart/signed envelope
eml = build_notification_email(
    notification,
    sender="noc@example.com",
    recipient="ops@client.example",
)
signed_eml = sign_notification_email(eml, signer=my_pgp_signer, micalg="pgp-sha256")

# Consumer side: verify the raw bytes before you parse any attachments
notifications = extract_notifications_from_email(
    signed_eml.as_bytes(),
    pgp_verifier=my_pgp_verifier,
    require_pgp_signature=True,
)
```

Implement the `OpenPGPSigner` and `OpenPGPVerifier` protocols to connect your GPG binary or cryptographic library.
To see a complete offline example with tamper detection, run `examples/signed_email_and_sanitization.py`.

## 3. Sync Notifications with CalDAV over TLS (RFC 4791, Section 5.2)

Providers can publish notifications to an authenticated CalDAV calendar over HTTPS instead of email.
Consumers can then get those notifications from the CalDAV server.

`CalDAVClient` enforces `https://` with TLS 1.2 or newer by default.
It supports these CalDAV operations:

- **Discover a collection (`PROPFIND`):** Read the collection name (`displayname`) and `CTag`.
- **Query events (`REPORT`):** Filter by time range and `X-MAINTNOTE-*` `prop-filter` rules.
- **Get one event (`GET`):** Download one `.ics` resource and its `ETag`.
- **Publish or update (`PUT`):** Protect concurrent writes with `If-Match` or `If-None-Match`.
- **Delete an event (`DELETE`):** Remove a resource, with optional `If-Match` validation.

```python
from datetime import datetime, timezone
from maintnote import CalDAVClient, Status

client = CalDAVClient(
    "https://caldav.example.com/calendars/maintenance/",
    bearer_token="...",
)

# Discover the collection name and CTag
info = client.discover_collection()

# Get confirmed events for one provider in a time window
events = client.fetch_events(
    start=datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc),
    end=datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc),
    provider="example.com",
    status=Status.CONFIRMED,
)

# Get one event and update it with ETag concurrency checks
single = client.get_notification("maint-001.ics")
client.publish_notification(single.notifications[0], if_match=single.etag)
```

To see a complete offline example with a local mock CalDAV server, run `examples/caldav_and_altrep_demo.py`.

## 4. Get External `ALTREP` Metadata Safely (Section 2.5.4)

A `ServiceObject` can contain an `ALTREP` URI that points to structured JSON data, such as a PeeringDB record or provider circuit page.

!!! warning
    Never get an untrusted `ALTREP` URL without scheme, redirect, and IP address checks.
    A malicious `ALTREP` URL can reach internal network services (SSRF) or fill memory with a large response.

`fetch_altrep_metadata()` applies these protections by default:

- Allows only `https` URIs (`allowed_schemes=("https",)`).
- Blocks loopback, private, link-local, multicast, and reserved IP addresses (`block_private_ips=True`).
- Checks scheme and IP rules again on each HTTP redirect hop.
- Limits response size to 5 MiB (`max_bytes=5 * 1024 * 1024`).
- Decodes RFC 7159 JSON responses into `AltrepResource.data`.

```python
from maintnote import fetch_altrep_metadata

for obj in notification.objects:
    if obj.altrep:
        resource = fetch_altrep_metadata(obj)
        print(resource.data)
```

## 5. Run Out-of-Band Verification (Section 5.2)

Attach an `OutOfBandVerifier` to `MaintenanceConsumer` before your consumer opens tickets or changes routing state.
The verifier checks each received notification against a trusted source, such as a provider API or allowlist.
If `verify()` returns `False`, `MaintenanceConsumer.process()` raises `VerificationError` and makes no changes to the state store or ticket handler.

To see a working example, run `examples/multi_provider_automation.py`.
