"""Tests for ALTREP metadata fetching (Section 2.5.4) and CalDAV over TLS (Section 5.2)."""

from __future__ import annotations

import io
import json
import urllib.request
from datetime import datetime, timezone
from typing import Any

import pytest

from maintnote.exceptions import TransportError
from maintnote.models import Impact, MaintenanceNotification, ServiceObject, Status
from maintnote.serializer import dumps
from maintnote.transport import CalDAVClient, fetch_altrep_metadata


class _MockResponse:
    def __init__(
        self, body: bytes, headers: dict[str, str] | None = None, status: int = 200
    ) -> None:
        self._stream = io.BytesIO(body)
        self.headers = headers or {}
        self.status = status

    def read(self) -> bytes:
        return self._stream.read()

    def __enter__(self) -> _MockResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _MockOpener(urllib.request.OpenerDirector):
    def __init__(self, responses: list[_MockResponse]) -> None:
        super().__init__()
        self._responses = list(responses)
        self.requests: list[urllib.request.Request] = []

    def open(self, fullurl: Any, data: Any = None, timeout: Any = None) -> Any:
        assert isinstance(fullurl, urllib.request.Request)
        self.requests.append(fullurl)
        return self._responses.pop(0)


def test_fetch_altrep_metadata_json_and_scheme_validation() -> None:
    peeringdb_payload = {
        "data": [
            {"asn": 64496, "ipaddr4": "192.0.2.42"},
            {"asn": 65536, "ipaddr4": "192.0.2.137"},
        ]
    }
    opener = _MockOpener(
        [
            _MockResponse(
                json.dumps(peeringdb_payload).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        ]
    )
    obj = ServiceObject(
        object_id="2718281828459",
        altrep="https://www.peeringdb.com/api/netixlan?asn__in=64496,65536",
    )

    res = fetch_altrep_metadata(obj, opener=opener)
    assert res.data == peeringdb_payload
    assert opener.requests[0].get_method() == "GET"

    # Rejects insecure http:// by default
    insecure = ServiceObject(object_id="1", altrep="http://example.org/info.json")
    with pytest.raises(TransportError, match="allowed schemes"):
        fetch_altrep_metadata(insecure, opener=opener)

    # Rejects objects without ALTREP
    with pytest.raises(TransportError, match="does not define an ALTREP"):
        fetch_altrep_metadata(ServiceObject(object_id="1"), opener=opener)


def test_caldav_enforces_tls_by_default() -> None:
    with pytest.raises(TransportError, match="HTTPS/TLS"):
        CalDAVClient("http://cal.example.com/maint/")


def test_caldav_fetch_publish_and_delete() -> None:
    notif = MaintenanceNotification.create(
        uid="caldav-uid-1",
        dtstart=datetime(2026, 12, 1, 2, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 12, 1, 4, 0, tzinfo=timezone.utc),
        summary="CalDAV published maintenance",
        organizer="noc@example.com",
        provider="example.com",
        account="ACC-77",
        maintenance_id="WO-77",
        objects=["ckt-77"],
        impact=Impact.OUTAGE,
        status=Status.CONFIRMED,
    )
    ical_blob = dumps(notif)
    multistatus_xml = f"""<?xml version="1.0" encoding="utf-8"?>
    <D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
      <D:response>
        <D:href>/maint/caldav-uid-1.ics</D:href>
        <D:propstat>
          <D:prop>
            <C:calendar-data>{ical_blob}</C:calendar-data>
          </D:prop>
          <D:status>HTTP/1.1 200 OK</D:status>
        </D:propstat>
      </D:response>
    </D:multistatus>
    """.encode()

    opener = _MockOpener(
        [
            _MockResponse(b"", status=201),  # PUT
            _MockResponse(multistatus_xml, headers={"Content-Type": "application/xml"}),  # REPORT
            _MockResponse(b"", status=204),  # DELETE
        ]
    )
    client = CalDAVClient(
        "https://cal.example.com/maint",
        username="ops",
        password="secret",
        opener=opener,
    )

    published_url = client.publish_notification(notif)
    assert published_url == "https://cal.example.com/maint/caldav-uid-1.ics"
    assert opener.requests[0].get_method() == "PUT"
    assert opener.requests[0].headers["Authorization"].startswith("Basic ")

    fetched = client.fetch_notifications(
        start=datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc),
        end=datetime(2026, 12, 2, 0, 0, tzinfo=timezone.utc),
    )
    assert len(fetched) == 1
    assert fetched[0].uid == "caldav-uid-1"
    assert opener.requests[1].get_method() == "REPORT"
    req_data = opener.requests[1].data
    assert isinstance(req_data, bytes)
    assert b"time-range" in req_data

    client.delete_notification("caldav-uid-1.ics")
    assert opener.requests[2].get_method() == "DELETE"
