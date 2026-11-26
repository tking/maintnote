"""Tests for maintnote domain models and draft Section 2.5 semantics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from maintnote.exceptions import ValidationError
from maintnote.models import (
    Impact,
    ImpactValue,
    MaintenanceNotification,
    Organizer,
    ServiceObject,
    Status,
    StatusValue,
)


def test_impact_standard_and_outage_fallback() -> None:
    # Standard values preserve exact label and severity order
    impacts = [
        ImpactValue.from_impact(Impact.NO_IMPACT),
        ImpactValue.from_impact(Impact.REDUCED_REDUNDANCY),
        ImpactValue.from_impact(Impact.DEGRADED),
        ImpactValue.from_impact(Impact.OUTAGE),
    ]
    assert [i.severity for i in impacts] == [0, 1, 2, 3]
    assert all(i.is_standard for i in impacts)

    # Per Section 2.5.5: unrecognized x-name and iana-token values default to OUTAGE
    custom_x = ImpactValue("X-VENDOR-PARTIAL-BGP-FLAP")
    assert not custom_x.is_standard
    assert custom_x.raw == "X-VENDOR-PARTIAL-BGP-FLAP"
    assert custom_x.effective is Impact.OUTAGE
    assert custom_x.severity == Impact.OUTAGE.severity

    custom_iana = ImpactValue("PACKET-LOSS")
    assert not custom_iana.is_standard
    assert custom_iana.effective is Impact.OUTAGE

    assert Impact.worst(Impact.NO_IMPACT, Impact.DEGRADED, custom_x) is Impact.OUTAGE
    assert Impact.worst(Impact.NO_IMPACT, Impact.REDUCED_REDUNDANCY) is Impact.REDUCED_REDUNDANCY


def test_impact_rejects_invalid_tokens() -> None:
    with pytest.raises(ValidationError):
        ImpactValue("")
    with pytest.raises(ValidationError):
        ImpactValue("BAD VALUE WITH SPACES")


def test_status_standard_and_custom_extensions() -> None:
    for st in Status:
        sv = StatusValue.from_status(st)
        assert sv.standard is st
        assert sv.is_standard

    custom = StatusValue("X-POSTPONED")
    assert not custom.is_standard
    assert custom.standard is None
    assert str(custom) == "X-POSTPONED"

    # Leading/trailing whitespace is trimmed (e.g., draft Example 4.5)
    assert StatusValue(" COMPLETED").standard is Status.COMPLETED

    with pytest.raises(ValidationError):
        StatusValue("   ")


def test_organizer_normalizes_mailto() -> None:
    org = Organizer(address="noc@example.com", cn="Example NOC")
    assert org.address == "mailto:noc@example.com"
    assert org.email == "noc@example.com"
    assert org.cn == "Example NOC"

    org2 = Organizer(address="mailto:ops@example.net")
    assert org2.address == "mailto:ops@example.net"
    assert org2.email == "ops@example.net"


def test_service_object_scoped_id_prevents_provider_collision() -> None:
    obj_a = ServiceObject(
        object_id="circuit-100",
        altrep="https://provider-a.example/api/circuits/100",
        language="en-US",
    )
    obj_b = ServiceObject(object_id="circuit-100")
    assert obj_a.scoped_id("provider-a.example") != obj_b.scoped_id("provider-b.example")
    assert obj_a.all_params() == {
        "ALTREP": ("https://provider-a.example/api/circuits/100",),
        "LANGUAGE": ("en-US",),
    }


def test_notification_create_helpers_and_to_dict() -> None:
    start = datetime(2026, 6, 1, 2, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 1, 4, 30, tzinfo=timezone.utc)
    notif = MaintenanceNotification.create(
        uid="maint-001@example.com",
        dtstart=start,
        dtend=end,
        summary="Core router linecard replacement",
        organizer=Organizer("noc@example.com", cn="Example NOC"),
        provider="example.com",
        account="acct-42",
        maintenance_id="WO-999",
        objects=["2001:db8::d06:f00d", "198.51.100.13"],
        impact=Impact.OUTAGE,
        status=Status.TENTATIVE,
        language="en",
    )
    assert notif.duration == timedelta(hours=2, minutes=30)
    assert notif.is_tentative
    assert not notif.is_confirmed
    assert notif.effective_impact is Impact.OUTAGE
    assert notif.scoped_object_ids == (
        ("example.com", "2001:db8::d06:f00d"),
        ("example.com", "198.51.100.13"),
    )
    as_dict = notif.to_dict()
    assert as_dict["provider"] == "example.com"
    assert as_dict["effective_impact"] == "OUTAGE"
    assert len(as_dict["objects"]) == 2


def test_models_edge_cases_and_validation_errors() -> None:
    # Impact.worst() with no arguments defaults conservatively to OUTAGE
    assert Impact.worst() is Impact.OUTAGE

    # ImpactValue and StatusValue merge parameters when coercing existing instances
    base_impact = ImpactValue(Impact.DEGRADED.value, params={"X-A": ("1",)})
    merged_impact = ImpactValue.from_impact(base_impact, params={"x-b": ("2",)})
    assert merged_impact.params == {"X-A": ("1",), "X-B": ("2",)}
    assert str(merged_impact) == "DEGRADED"

    base_status = StatusValue(Status.CONFIRMED.value, params={"X-A": ("1",)})
    merged_status = StatusValue.from_status(base_status, params={"x-b": ("2",)})
    assert merged_status.params == {"X-A": ("1",), "X-B": ("2",)}

    with pytest.raises(ValidationError):
        StatusValue("BAD VALUE WITH SPACES")

    # Organizer validation and non-mailto URI handling
    with pytest.raises(ValidationError):
        Organizer("   ")
    urn_org = Organizer("urn:uuid:12345")
    assert urn_org.email == "urn:uuid:12345"

    # ServiceObject rejects blank object_id
    with pytest.raises(ValidationError):
        ServiceObject("   ")

    # MaintenanceNotification.with_updates coerces string organizer
    notif = MaintenanceNotification.create(
        uid="maint-002@example.com",
        dtstart=datetime(2026, 6, 1, 2, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 6, 1, 3, 0, tzinfo=timezone.utc),
        summary="Switch firmware update",
        organizer="noc@example.com",
        provider="example.com",
        account="acct-42",
        maintenance_id="WO-1000",
        objects=["ckt-1"],
        impact=Impact.NO_IMPACT,
    )
    updated = notif.with_updates(organizer="ops2@example.com")
    assert updated.organizer.address == "mailto:ops2@example.com"
