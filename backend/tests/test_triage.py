from __future__ import annotations

from shapely.geometry import box

from geointx.cases.triage import ExistingCase, decide

A = box(0, 0, 10, 10)
MOSTLY_A = box(1, 1, 10, 10)  # 81% of A
ELSEWHERE = box(50, 50, 60, 60)


def test_new_loss_in_encroachment_area_is_queued() -> None:
    assert decide("water_loss", "P2", "encroachment", A, []) == ("queued", None)


def test_low_priority_is_recorded_not_queued() -> None:
    assert decide("water_loss", "P3", "encroachment", A, [])[0] == "recorded_low_priority"


def test_gain_in_encroachment_area_is_not_queued() -> None:
    assert (
        decide("water_gain", "P1", "encroachment", A, [])[0] == "recorded_not_encroachment_relevant"
    )
    assert decide("water_gain", "P2", "lulc", A, [])[0] == "queued"
    assert decide("revegetation", "P1", "lulc", A, [])[0] == "recorded_gain"


def test_same_change_reobserved_updates_existing_case() -> None:
    ex = [ExistingCase("CASE-0001", "water_loss", A)]
    d, match = decide("water_loss", "P1", "encroachment", MOSTLY_A, ex)
    assert d == "re_observed" and match is not None and match.case_id == "CASE-0001"


def test_vegetation_loss_family_counts_as_same_change() -> None:
    ex = [ExistingCase("CASE-0002", "cropland_to_bare_or_built", A)]
    assert decide("vegetation_to_bare_or_built", "P2", "lulc", A, ex)[0] == "re_observed"


def test_opposite_change_is_recorded_as_reversal() -> None:
    ex = [ExistingCase("CASE-0003", "water_loss", A)]
    d, match = decide("water_gain", "P1", "lulc", MOSTLY_A, ex)
    assert d == "reversal_observed" and match is not None and match.case_id == "CASE-0003"


def test_unrelated_location_opens_new_case() -> None:
    ex = [ExistingCase("CASE-0001", "water_loss", A)]
    assert decide("water_loss", "P1", "encroachment", ELSEWHERE, ex) == ("queued", None)
