"""External metadata (ALTREP) and CalDAV over TLS (RFC 4791) transport helpers.

Implements Section 2.5.4 (fetching external JSON metadata referenced via the
``ALTREP`` parameter on ``X-MAINTNOTE-OBJECT-ID``, e.g., PeeringDB APIs) and
Section 5.2 (pulling and publishing maintenance notifications via CalDAV over
TLS as an authenticated alternative to email distribution).
"""

from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from maintnote.exceptions import TransportError
from maintnote.models import MaintenanceNotification, ServiceObject
from maintnote.parser import parse_calendar
from maintnote.serializer import dumps

_DAV_NS = "DAV:"
_CALDAV_NS = "urn:ietf:params:xml:ns:caldav"


@dataclass(frozen=True, slots=True)
class AltrepResource:
    """Result returned by :func:`fetch_altrep_metadata`."""

    uri: str
    content_type: str
    raw_body: bytes
    data: Any = None


def fetch_altrep_metadata(
    service_object: ServiceObject,
    *,
    timeout: float = 10.0,
    allowed_schemes: tuple[str, ...] = ("https",),
    headers: dict[str, str] | None = None,
    opener: urllib.request.OpenerDirector | None = None,
) -> AltrepResource:
    """Fetch external metadata referenced by ``service_object.altrep`` (Section 2.5.4).

    Enforces ``allowed_schemes`` (``https`` only by default) and automatically
    parses RFC 7159 JSON payloads when returned.
    """
    if not service_object.altrep:
        raise TransportError(
            f"ServiceObject {service_object.object_id!r} does not define an ALTREP URI"
        )

    uri = service_object.altrep
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme.lower() not in tuple(s.lower() for s in allowed_schemes):
        raise TransportError(
            f"ALTREP URI scheme {parsed.scheme!r} is not in allowed schemes {allowed_schemes!r}"
        )

    req_headers = {"Accept": "application/json, */*;q=0.8", "User-Agent": "maintnote/0.1"}
    if headers:
        req_headers.update(headers)

    request = urllib.request.Request(uri, headers=req_headers, method="GET")
    resolved_opener = opener or _default_tls_opener()

    try:
        with resolved_opener.open(request, timeout=timeout) as response:
            raw_body: bytes = response.read()
            content_type = str(response.headers.get("Content-Type", "application/octet-stream"))
    except (urllib.error.URLError, OSError) as exc:
        raise TransportError(f"Failed to retrieve ALTREP URI {uri!r}: {exc}") from exc

    decoded_json: Any = None
    if "json" in content_type.lower():
        try:
            decoded_json = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TransportError(f"ALTREP URI {uri!r} returned invalid JSON: {exc}") from exc
    else:
        # Attempt opportunistic RFC 7159 JSON decoding if payload looks like JSON
        stripped = raw_body.lstrip()
        if stripped.startswith((b"{", b"[")):
            try:
                decoded_json = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                decoded_json = None

    return AltrepResource(
        uri=uri,
        content_type=content_type,
        raw_body=raw_body,
        data=decoded_json,
    )


class CalDAVClient:
    """Minimal pure-stdlib CalDAV client over TLS (RFC 4791 + Section 5.2).

    Supports querying maintenance notification events via ``REPORT``
    (``calendar-query``), publishing notifications via ``PUT``, and deleting
    resources via ``DELETE``.
    """

    def __init__(
        self,
        calendar_url: str,
        *,
        username: str | None = None,
        password: str | None = None,
        bearer_token: str | None = None,
        require_tls: bool = True,
        timeout: float = 15.0,
        ssl_context: ssl.SSLContext | None = None,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        parsed = urllib.parse.urlparse(calendar_url)
        if require_tls and parsed.scheme.lower() != "https":
            raise TransportError(
                f"CalDAV requires HTTPS/TLS by default per Section 5.2; got {calendar_url!r}"
            )
        if parsed.scheme.lower() not in ("https", "http"):
            raise TransportError(f"Unsupported CalDAV URL scheme: {parsed.scheme!r}")

        self.calendar_url = calendar_url.rstrip("/") + "/"
        self._timeout = timeout
        self._auth_header = _build_auth_header(username, password, bearer_token)
        self._opener = opener or _default_tls_opener(ssl_context=ssl_context)

    def fetch_notifications(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        strict: bool = True,
    ) -> list[MaintenanceNotification]:
        """Pull maintenance notifications from the CalDAV collection via ``REPORT``."""
        query_xml = _build_calendar_query_xml(start=start, end=end)
        headers = {
            "Content-Type": "application/xml; charset=utf-8",
            "Depth": "1",
            "User-Agent": "maintnote/0.1",
        }
        if self._auth_header:
            headers["Authorization"] = self._auth_header

        request = urllib.request.Request(
            self.calendar_url,
            data=query_xml.encode("utf-8"),
            headers=headers,
            method="REPORT",
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body: bytes = response.read()
        except (urllib.error.URLError, OSError) as exc:
            raise TransportError(f"CalDAV REPORT failed for {self.calendar_url!r}: {exc}") from exc

        ical_blobs = _extract_calendar_data_from_multistatus(body)
        notifications: list[MaintenanceNotification] = []
        for blob in ical_blobs:
            doc = parse_calendar(blob, strict=strict)
            notifications.extend(doc.notifications)
        return notifications

    def publish_notification(
        self,
        notification: MaintenanceNotification,
        *,
        resource_name: str | None = None,
        include_method: bool = False,
    ) -> str:
        """Publish or update a maintenance notification on the CalDAV server via ``PUT``."""
        slug = resource_name or f"{urllib.parse.quote(notification.uid, safe='')}.ics"
        target_url = urllib.parse.urljoin(self.calendar_url, slug)
        payload = dumps(notification, include_method=include_method).encode("utf-8")

        headers = {
            "Content-Type": "text/calendar; charset=utf-8",
            "User-Agent": "maintnote/0.1",
        }
        if self._auth_header:
            headers["Authorization"] = self._auth_header

        request = urllib.request.Request(
            target_url,
            data=payload,
            headers=headers,
            method="PUT",
        )
        try:
            with self._opener.open(request, timeout=self._timeout):
                return target_url
        except (urllib.error.URLError, OSError) as exc:
            raise TransportError(f"CalDAV PUT failed for {target_url!r}: {exc}") from exc

    def delete_notification(self, resource_name: str) -> None:
        """Delete a maintenance notification resource from the CalDAV server."""
        target_url = urllib.parse.urljoin(self.calendar_url, resource_name)
        headers = {"User-Agent": "maintnote/0.1"}
        if self._auth_header:
            headers["Authorization"] = self._auth_header

        request = urllib.request.Request(target_url, headers=headers, method="DELETE")
        try:
            with self._opener.open(request, timeout=self._timeout):
                return
        except (urllib.error.URLError, OSError) as exc:
            raise TransportError(f"CalDAV DELETE failed for {target_url!r}: {exc}") from exc


def _default_tls_opener(
    *, ssl_context: ssl.SSLContext | None = None
) -> urllib.request.OpenerDirector:
    ctx = ssl_context or ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def _build_auth_header(
    username: str | None, password: str | None, bearer_token: str | None
) -> str | None:
    if bearer_token:
        return f"Bearer {bearer_token}"
    if username is not None and password is not None:
        raw = f"{username}:{password}".encode()
        return f"Basic {base64.b64encode(raw).decode('ascii')}"
    return None


def _build_calendar_query_xml(*, start: datetime | None, end: datetime | None) -> str:
    time_range = ""
    if start is not None or end is not None:
        attrs: list[str] = []
        if start is not None:
            attrs.append(f'start="{start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}"')
        if end is not None:
            attrs.append(f'end="{end.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}"')
        time_range = f"<C:time-range {' '.join(attrs)}/>"

    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
        "<D:prop><D:getetag/><C:calendar-data/></D:prop>"
        "<C:filter>"
        '<C:comp-filter name="VCALENDAR">'
        f'<C:comp-filter name="VEVENT">{time_range}</C:comp-filter>'
        "</C:comp-filter>"
        "</C:filter>"
        "</C:calendar-query>"
    )


def _extract_calendar_data_from_multistatus(xml_bytes: bytes) -> list[str]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise TransportError(f"Invalid CalDAV XML multistatus response: {exc}") from exc

    blobs: list[str] = []
    for elem in root.iter(f"{{{_CALDAV_NS}}}calendar-data"):
        if elem.text and elem.text.strip():
            blobs.append(elem.text)
    return blobs
