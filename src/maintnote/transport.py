"""External metadata (ALTREP) and CalDAV over TLS (RFC 4791) transport helpers.

Implements Section 2.5.4 (fetching external JSON metadata referenced via the
``ALTREP`` parameter on ``X-MAINTNOTE-OBJECT-ID``, e.g., PeeringDB APIs) and
Section 5.2 (pulling and publishing maintenance notifications via CalDAV over
TLS as an authenticated alternative to email distribution).
"""

from __future__ import annotations

import base64
import ipaddress
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import quoteattr

from maintnote.exceptions import TransportError
from maintnote.models import MaintenanceNotification, ServiceObject, Status, StatusValue
from maintnote.parser import parse_calendar
from maintnote.serializer import dumps

_DAV_NS = "DAV:"
_CALDAV_NS = "urn:ietf:params:xml:ns:caldav"
_CS_NS = "http://calendarserver.org/ns/"

DEFAULT_MAX_ALTREP_BYTES = 5 * 1024 * 1024  # 5 MiB


@dataclass(frozen=True, slots=True)
class AltrepResource:
    """Result returned by :func:`fetch_altrep_metadata`."""

    uri: str
    content_type: str
    raw_body: bytes
    data: Any = None


@dataclass(frozen=True, slots=True)
class CalDAVEvent:
    """A single CalDAV resource containing parsed maintenance notifications and its ``ETag``."""

    href: str
    etag: str | None
    notifications: tuple[MaintenanceNotification, ...]


@dataclass(frozen=True, slots=True)
class CalDAVCollectionInfo:
    """Metadata discovered for a CalDAV collection via ``PROPFIND``."""

    url: str
    display_name: str | None = None
    ctag: str | None = None


def _validate_url_target(
    uri: str,
    *,
    allowed_schemes: tuple[str, ...],
    block_private_ips: bool,
) -> None:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme.lower() not in tuple(s.lower() for s in allowed_schemes):
        raise TransportError(
            f"URI scheme {parsed.scheme!r} is not in allowed schemes {allowed_schemes!r}"
        )
    if block_private_ips and parsed.hostname:
        host = parsed.hostname.strip().lower()
        if host in ("localhost", "localhost.localdomain"):
            raise TransportError(f"Blocked loopback ALTREP host: {host!r}")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise TransportError(f"Blocked non-public ALTREP IP address: {host!r}")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that re-validates scheme and host rules on every redirect hop."""

    def __init__(self, *, allowed_schemes: tuple[str, ...], block_private_ips: bool) -> None:
        super().__init__()
        self._allowed_schemes = allowed_schemes
        self._block_private_ips = block_private_ips

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        resolved = urllib.parse.urljoin(req.full_url, newurl)
        _validate_url_target(
            resolved,
            allowed_schemes=self._allowed_schemes,
            block_private_ips=self._block_private_ips,
        )
        return super().redirect_request(req, fp, code, msg, headers, resolved)


def fetch_altrep_metadata(
    service_object: ServiceObject,
    *,
    timeout: float = 10.0,
    allowed_schemes: tuple[str, ...] = ("https",),
    block_private_ips: bool = True,
    max_bytes: int = DEFAULT_MAX_ALTREP_BYTES,
    headers: dict[str, str] | None = None,
    opener: urllib.request.OpenerDirector | None = None,
) -> AltrepResource:
    """Fetch external metadata referenced by ``service_object.altrep`` (Section 2.5.4).

    Enforces ``allowed_schemes`` (``https`` only by default), guards redirects
    against scheme downgrades and private/loopback IP SSRF, caps response size
    at ``max_bytes``, and automatically decodes RFC 7159 JSON payloads.
    """
    if not service_object.altrep:
        raise TransportError(
            f"ServiceObject {service_object.object_id!r} does not define an ALTREP URI"
        )

    uri = service_object.altrep
    _validate_url_target(
        uri,
        allowed_schemes=allowed_schemes,
        block_private_ips=block_private_ips,
    )

    req_headers = {"Accept": "application/json, */*;q=0.8", "User-Agent": "maintnote/0.1"}
    if headers:
        req_headers.update(headers)

    request = urllib.request.Request(uri, headers=req_headers, method="GET")
    resolved_opener = opener or _default_tls_opener(
        allowed_schemes=allowed_schemes,
        block_private_ips=block_private_ips,
    )

    try:
        with resolved_opener.open(request, timeout=timeout) as response:
            raw_body: bytes = response.read(max_bytes + 1)
            if len(raw_body) > max_bytes:
                raise TransportError(
                    f"ALTREP response from {uri!r} exceeded max_bytes limit ({max_bytes} bytes)"
                )
            content_type = str(response.headers.get("Content-Type", "application/octet-stream"))
    except TransportError:
        raise
    except (urllib.error.URLError, OSError) as exc:
        raise TransportError(f"Failed to retrieve ALTREP URI {uri!r}: {exc}") from exc

    decoded_json: Any = None
    if "json" in content_type.lower():
        try:
            decoded_json = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TransportError(f"ALTREP URI {uri!r} returned invalid JSON: {exc}") from exc
    else:
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
    """Pure-stdlib CalDAV client over TLS (RFC 4791 + Section 5.2).

    Supports collection discovery (``PROPFIND``), querying maintenance events
    via ``REPORT`` (``calendar-query`` with time-range & ``X-MAINTNOTE-*``
    ``prop-filter``s), single-resource ``GET``, ``PUT`` with ``ETag``
    concurrency control, and ``DELETE``.
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
        self._opener = opener or _default_tls_opener(
            ssl_context=ssl_context,
            allowed_schemes=("https",) if require_tls else ("https", "http"),
            block_private_ips=False,
        )

    def discover_collection(self) -> CalDAVCollectionInfo:
        """Inspect CalDAV collection display name and CTag via ``PROPFIND``."""
        propfind_xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:propfind xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/">'
            "<D:prop><D:displayname/><CS:getctag/></D:prop>"
            "</D:propfind>"
        )
        headers = self._base_headers(
            {"Content-Type": "application/xml; charset=utf-8", "Depth": "0"}
        )
        request = urllib.request.Request(
            self.calendar_url,
            data=propfind_xml.encode("utf-8"),
            headers=headers,
            method="PROPFIND",
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body: bytes = response.read()
        except (urllib.error.URLError, OSError) as exc:
            raise TransportError(
                f"CalDAV PROPFIND failed for {self.calendar_url!r}: {exc}"
            ) from exc

        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise TransportError(f"Invalid CalDAV PROPFIND XML response: {exc}") from exc

        display_elem = root.find(f".//{{{_DAV_NS}}}displayname")
        ctag_elem = root.find(f".//{{{_CS_NS}}}getctag")
        return CalDAVCollectionInfo(
            url=self.calendar_url,
            display_name=display_elem.text.strip()
            if display_elem is not None and display_elem.text
            else None,
            ctag=ctag_elem.text.strip() if ctag_elem is not None and ctag_elem.text else None,
        )

    def fetch_events(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        provider: str | None = None,
        maintenance_id: str | None = None,
        status: Status | StatusValue | str | None = None,
        strict: bool = True,
    ) -> list[CalDAVEvent]:
        """Pull CalDAV event resources (with ``href`` and ``ETag``) via ``REPORT``."""
        status_str: str | None = None
        if status is not None:
            status_str = status.value if isinstance(status, Status) else str(status)

        query_xml = _build_calendar_query_xml(
            start=start,
            end=end,
            provider=provider,
            maintenance_id=maintenance_id,
            status=status_str,
        )
        headers = self._base_headers(
            {"Content-Type": "application/xml; charset=utf-8", "Depth": "1"}
        )
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

        raw_entries = _extract_responses_from_multistatus(body)
        events: list[CalDAVEvent] = []
        for href, etag, blob in raw_entries:
            doc = parse_calendar(blob, strict=strict)
            events.append(
                CalDAVEvent(
                    href=href,
                    etag=etag,
                    notifications=doc.notifications,
                )
            )
        return events

    def fetch_notifications(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        provider: str | None = None,
        maintenance_id: str | None = None,
        status: Status | StatusValue | str | None = None,
        strict: bool = True,
    ) -> list[MaintenanceNotification]:
        """Pull maintenance notifications from the CalDAV collection via ``REPORT``."""
        events = self.fetch_events(
            start=start,
            end=end,
            provider=provider,
            maintenance_id=maintenance_id,
            status=status,
            strict=strict,
        )
        notifications: list[MaintenanceNotification] = []
        for ev in events:
            notifications.extend(ev.notifications)
        return notifications

    def get_notification(self, resource_name: str, *, strict: bool = True) -> CalDAVEvent:
        """Fetch a single ``.ics`` resource and its ``ETag`` via HTTP ``GET``."""
        target_url = urllib.parse.urljoin(self.calendar_url, resource_name)
        headers = self._base_headers({"Accept": "text/calendar, */*;q=0.8"})
        request = urllib.request.Request(target_url, headers=headers, method="GET")
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body: bytes = response.read()
                etag = response.headers.get("ETag")
        except (urllib.error.URLError, OSError) as exc:
            raise TransportError(f"CalDAV GET failed for {target_url!r}: {exc}") from exc

        doc = parse_calendar(body, strict=strict)
        return CalDAVEvent(
            href=target_url,
            etag=str(etag) if etag is not None else None,
            notifications=doc.notifications,
        )

    def publish_notification(
        self,
        notification: MaintenanceNotification,
        *,
        resource_name: str | None = None,
        include_method: bool = False,
        if_match: str | None = None,
        if_none_match: str | None = None,
    ) -> str:
        """Publish or update a maintenance notification on the CalDAV server via ``PUT``.

        Supports ``if_match`` (optimistic update concurrency using an ``ETag``) and
        ``if_none_match`` (e.g., ``"*"`` to prevent overwriting an existing event).
        """
        slug = resource_name or f"{urllib.parse.quote(notification.uid, safe='')}.ics"
        target_url = urllib.parse.urljoin(self.calendar_url, slug)
        payload = dumps(notification, include_method=include_method).encode("utf-8")

        extra: dict[str, str] = {"Content-Type": "text/calendar; charset=utf-8"}
        if if_match is not None:
            extra["If-Match"] = if_match
        if if_none_match is not None:
            extra["If-None-Match"] = if_none_match

        request = urllib.request.Request(
            target_url,
            data=payload,
            headers=self._base_headers(extra),
            method="PUT",
        )
        try:
            with self._opener.open(request, timeout=self._timeout):
                return target_url
        except (urllib.error.URLError, OSError) as exc:
            raise TransportError(f"CalDAV PUT failed for {target_url!r}: {exc}") from exc

    def delete_notification(self, resource_name: str, *, if_match: str | None = None) -> None:
        """Delete a maintenance notification resource from the CalDAV server."""
        target_url = urllib.parse.urljoin(self.calendar_url, resource_name)
        extra: dict[str, str] = {}
        if if_match is not None:
            extra["If-Match"] = if_match

        request = urllib.request.Request(
            target_url,
            headers=self._base_headers(extra),
            method="DELETE",
        )
        try:
            with self._opener.open(request, timeout=self._timeout):
                return
        except (urllib.error.URLError, OSError) as exc:
            raise TransportError(f"CalDAV DELETE failed for {target_url!r}: {exc}") from exc

    def _base_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"User-Agent": "maintnote/0.1"}
        if self._auth_header:
            headers["Authorization"] = self._auth_header
        if extra:
            headers.update(extra)
        return headers


def _default_tls_opener(
    *,
    ssl_context: ssl.SSLContext | None = None,
    allowed_schemes: tuple[str, ...] = ("https",),
    block_private_ips: bool = True,
) -> urllib.request.OpenerDirector:
    ctx = ssl_context or ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ctx),
        _SafeRedirectHandler(
            allowed_schemes=allowed_schemes,
            block_private_ips=block_private_ips,
        ),
    )


def _build_auth_header(
    username: str | None, password: str | None, bearer_token: str | None
) -> str | None:
    if bearer_token:
        return f"Bearer {bearer_token}"
    if username is not None and password is not None:
        raw = f"{username}:{password}".encode()
        return f"Basic {base64.b64encode(raw).decode('ascii')}"
    return None


def _build_calendar_query_xml(
    *,
    start: datetime | None,
    end: datetime | None,
    provider: str | None = None,
    maintenance_id: str | None = None,
    status: str | None = None,
) -> str:
    filters: list[str] = []
    if start is not None or end is not None:
        attrs: list[str] = []
        if start is not None:
            attrs.append(f'start="{start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}"')
        if end is not None:
            attrs.append(f'end="{end.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}"')
        filters.append(f"<C:time-range {' '.join(attrs)}/>")

    for prop_name, value in (
        ("X-MAINTNOTE-PROVIDER", provider),
        ("X-MAINTNOTE-MAINTENANCE-ID", maintenance_id),
        ("X-MAINTNOTE-STATUS", status),
    ):
        if value is not None:
            filters.append(
                f"<C:prop-filter name={quoteattr(prop_name)}>"
                f"<C:text-match>{xml_escape(value)}</C:text-match>"
                "</C:prop-filter>"
            )

    inner_filters = "".join(filters)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
        "<D:prop><D:getetag/><C:calendar-data/></D:prop>"
        "<C:filter>"
        '<C:comp-filter name="VCALENDAR">'
        f'<C:comp-filter name="VEVENT">{inner_filters}</C:comp-filter>'
        "</C:comp-filter>"
        "</C:filter>"
        "</C:calendar-query>"
    )


def _extract_responses_from_multistatus(xml_bytes: bytes) -> list[tuple[str, str | None, str]]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise TransportError(f"Invalid CalDAV XML multistatus response: {exc}") from exc

    entries: list[tuple[str, str | None, str]] = []
    for resp in root.iter(f"{{{_DAV_NS}}}response"):
        href_elem = resp.find(f"{{{_DAV_NS}}}href")
        href = href_elem.text.strip() if href_elem is not None and href_elem.text else ""
        etag_elem = resp.find(f".//{{{_DAV_NS}}}getetag")
        etag = etag_elem.text.strip() if etag_elem is not None and etag_elem.text else None
        cal_elem = resp.find(f".//{{{_CALDAV_NS}}}calendar-data")
        if cal_elem is not None and cal_elem.text and cal_elem.text.strip():
            entries.append((href, etag, cal_elem.text))
    return entries
