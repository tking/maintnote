"""Example: Self-contained offline CalDAV server, CalDAVClient, and ALTREP metadata demo.

Demonstrates Section 2.5.4 (ALTREP external JSON retrieval with SSRF protection) and
Section 5.2 / RFC 4791 (CalDAV collection discovery, PUT with ETag concurrency,
REPORT queries with X-MAINTNOTE-* prop-filters, GET, and DELETE) using an in-process
stdlib HTTP server so the example runs completely offline.
"""

from __future__ import annotations

import json
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from maintnote import (
    CalDAVClient,
    Impact,
    MaintenanceProvider,
    ServiceObject,
    Status,
    TransportError,
    fetch_altrep_metadata,
)

_CALDAV_NS = "urn:ietf:params:xml:ns:caldav"


class _DemoCalDAVState:
    """In-memory backing store for the local mock CalDAV + ALTREP server."""

    def __init__(self) -> None:
        self.resources: dict[str, tuple[str, str]] = {}  # path -> (etag, ical_text)
        self.version = 0

    def next_etag(self) -> str:
        self.version += 1
        return f'"v{self.version}"'


def _make_handler(state: _DemoCalDAVState) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return None

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", "0"))
            return self.rfile.read(length) if length > 0 else b""

        def do_PROPFIND(self) -> None:  # noqa: N802
            xml = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<D:multistatus xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/">'
                "<D:response>"
                f"<D:href>{xml_escape(self.path)}</D:href>"
                "<D:propstat><D:prop>"
                "<D:displayname>Network Maintenance Feed</D:displayname>"
                f"<CS:getctag>ctag-{state.version}</CS:getctag>"
                "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>"
                "</D:response></D:multistatus>"
            ).encode("utf-8")
            self.send_response(207)
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(xml)))
            self.end_headers()
            self.wfile.write(xml)

        def do_PUT(self) -> None:  # noqa: N802
            body = self._read_body().decode("utf-8")
            existing = state.resources.get(self.path)
            if_none_match = self.headers.get("If-None-Match")
            if_match = self.headers.get("If-Match")

            if if_none_match == "*" and existing is not None:
                self.send_response(412)
                self.end_headers()
                return
            if if_match is not None and (existing is None or existing[0] != if_match):
                self.send_response(412)
                self.end_headers()
                return

            etag = state.next_etag()
            state.resources[self.path] = (etag, body)
            self.send_response(201 if existing is None else 204)
            self.send_header("ETag", etag)
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/api/peeringdb"):
                payload = json.dumps(
                    {
                        "object_id": "2718281828459",
                        "facility": "DE-CIX Frankfurt",
                        "asns": [64496, 65536],
                        "ipv4": ["192.0.2.42", "192.0.2.137"],
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            existing = state.resources.get(self.path)
            if existing is None:
                self.send_response(404)
                self.end_headers()
                return
            etag, ical_text = existing
            raw = ical_text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/calendar; charset=utf-8")
            self.send_header("ETag", etag)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_REPORT(self) -> None:  # noqa: N802
            body = self._read_body()
            required_filters: list[tuple[str, str]] = []
            if body:
                root = ET.fromstring(body)
                for pf in root.iter(f"{{{_CALDAV_NS}}}prop-filter"):
                    prop_name = pf.attrib.get("name", "")
                    tm = pf.find(f"{{{_CALDAV_NS}}}text-match")
                    if prop_name and tm is not None and tm.text:
                        required_filters.append((prop_name, tm.text))

            responses: list[str] = []
            for href, (etag, ical_text) in state.resources.items():
                if all(f"{prop}:{val}" in ical_text for prop, val in required_filters):
                    responses.append(
                        "<D:response>"
                        f"<D:href>{xml_escape(href)}</D:href>"
                        "<D:propstat><D:prop>"
                        f"<D:getetag>{xml_escape(etag)}</D:getetag>"
                        f"<C:calendar-data>{xml_escape(ical_text)}</C:calendar-data>"
                        "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>"
                        "</D:response>"
                    )
            xml = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
                f"{''.join(responses)}"
                "</D:multistatus>"
            ).encode("utf-8")
            self.send_response(207)
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(xml)))
            self.end_headers()
            self.wfile.write(xml)

        def do_DELETE(self) -> None:  # noqa: N802
            existing = state.resources.get(self.path)
            if_match = self.headers.get("If-Match")
            if existing is None:
                self.send_response(404)
                self.end_headers()
                return
            if if_match is not None and existing[0] != if_match:
                self.send_response(412)
                self.end_headers()
                return
            del state.resources[self.path]
            self.send_response(204)
            self.end_headers()

    return _Handler


def main() -> None:
    state = _DemoCalDAVState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        base_url = f"http://127.0.0.1:{port}"
        cal_url = f"{base_url}/calendars/maint/"

        print("=== 1. CalDAV enforces HTTPS/TLS by default (Section 5.2) ===")
        try:
            CalDAVClient(cal_url)
        except TransportError as exc:
            print(f"  Blocked plaintext HTTP as expected: {exc}")

        # Disable TLS requirement ONLY for the local loopback demo server
        client = CalDAVClient(cal_url, require_tls=False, bearer_token="demo-token")

        print("\n=== 2. Discover collection metadata via PROPFIND ===")
        info = client.discover_collection()
        print(f"  display_name={info.display_name!r} ctag={info.ctag!r}")

        print("\n=== 3. Publish maintenance notifications with ETag concurrency (PUT) ===")
        provider = MaintenanceProvider(provider="ixp.example.org", organizer="noc@ixp.example.org")
        altrep_url = f"{base_url}/api/peeringdb?object=2718281828459"
        n0 = provider.create_initial(
            account="AS64496",
            maintenance_id="WO-CALDAV-1",
            objects=[ServiceObject(object_id="2718281828459", altrep=altrep_url)],
            dtstart=datetime(2026, 12, 15, 2, 0, tzinfo=timezone.utc),
            dtend=datetime(2026, 12, 15, 4, 0, tzinfo=timezone.utc),
            summary="DE-CIX optical chassis swap",
            impact=Impact.OUTAGE,
            uid="caldav-demo-1@ixp.example.org",
        )
        url = client.publish_notification(n0, if_none_match="*")
        print(f"  Created: {url}")

        fetched = client.get_notification("caldav-demo-1%40ixp.example.org.ics")
        print(f"  GET ETag={fetched.etag} seq={fetched.notifications[0].sequence}")

        # Update using optimistic concurrency (If-Match)
        n1 = provider.confirm(n0)
        client.publish_notification(n1, if_match=fetched.etag)

        # Demonstrate stale ETag conflict (HTTP 412 Precondition Failed)
        try:
            client.publish_notification(n1, if_match='"stale-etag"')
        except TransportError as exc:
            print(f"  Stale ETag rejected as expected: {exc}")

        print("\n=== 4. Pull filtered events via CalDAV REPORT (X-MAINTNOTE-* prop-filter) ===")
        events = client.fetch_events(
            start=datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc),
            end=datetime(2026, 12, 31, 0, 0, tzinfo=timezone.utc),
            provider="ixp.example.org",
            status=Status.CONFIRMED,
        )
        print(
            f"  REPORT matched {len(events)} event(s): "
            f"href={events[0].href} etag={events[0].etag} seq={events[0].notifications[0].sequence}"
        )

        print("\n=== 5. Fetch external ALTREP JSON metadata & SSRF protection (Section 2.5.4) ===")
        service_obj = events[0].notifications[0].objects[0]
        try:
            fetch_altrep_metadata(service_obj, allowed_schemes=("http", "https"))
        except TransportError as exc:
            print(f"  SSRF guard blocked loopback IP by default: {exc}")

        resource = fetch_altrep_metadata(
            service_obj,
            allowed_schemes=("http", "https"),
            block_private_ips=False,
        )
        print(f"  Decoded ALTREP JSON: {resource.data}")

        client.delete_notification(
            "caldav-demo-1%40ixp.example.org.ics",
            if_match=events[0].etag,
        )
        print("  Deleted resource cleanly via DELETE with If-Match.")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
