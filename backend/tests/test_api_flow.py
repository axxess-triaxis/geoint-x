"""End-to-end API flow against a small synthetic pack (no network, no LLM key)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box, mapping

from geointx.imagery.pack import write_scene, write_single
from geointx.settings import Settings
from tests.synthetic import BAND_ORDER, CODES, GRID, SURFACES, surface_map

SCL = {1: 4, 2: 5, 3: 6}
REVIEWER = {"X-Demo-User": "r.das", "X-Demo-Role": "reviewer"}
SUPERVISOR = {"X-Demo-User": "s.bora", "X-Demo-Role": "supervisor"}


def _dn(surfaces: np.ndarray) -> dict[str, np.ndarray]:
    out = {b: np.zeros(surfaces.shape, dtype=np.uint16) for b in BAND_ORDER}
    for name, code in CODES.items():
        m = surfaces == code
        for b, refl in zip(BAND_ORDER, SURFACES[name], strict=True):
            out[b][m] = round((refl + 0.1) / 1e-4)
    out["scl"] = np.vectorize(SCL.get)(surfaces).astype(np.uint16)
    return out


def _scene(sid: str, dt: str) -> dict[str, Any]:
    return {
        "scene_id": sid,
        "collection": "synthetic",
        "datetime": dt,
        "cloud_cover": 0.0,
        "aoi_valid_fraction": 1.0,
    }


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    pack = tmp_path / "pack"
    before = surface_map("veg")
    before[20:40, 20:40] = 3  # 4 ha water inside the wetland polygon
    mid = before.copy()
    mid[20:40, 20:40] = 2  # water lost
    mid[120:140, 100:130] = 2  # 6 ha vegetation to bare, outside
    late = mid.copy()
    scenes = [
        ("S1", "2020-01-15T04:40:00Z", before),
        ("S2", "2025-01-15T04:40:00Z", mid),
        ("S3", "2026-01-15T04:40:00Z", late),
    ]
    entries = []
    for sid, dt, surf in scenes:
        rel = f"aoi1/scenes/{sid}.tif"
        sha = write_scene(pack / rel, GRID, _dn(surf))
        entries.append({"season": dt[:4], "scene": _scene(sid, dt), "file": rel, "sha256": sha})
    wc = np.full(before.shape, 40, dtype=np.uint8)
    wc[0:60, 0:60] = 90
    write_single(pack / "aoi1/worldcover_2020.tif", GRID, wc)
    x0, y0 = GRID.origin_x, GRID.origin_y
    wetland = GRID.to_wgs84(box(x0, y0 - 600, x0 + 600, y0))
    (pack / "aoi1/polygons.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": mapping(wetland),
                        "properties": {
                            "id": "w1",
                            "name": "Test Beel",
                            "kind": "wetland",
                            "source": "synthetic",
                        },
                    }
                ],
            }
        )
    )
    (pack / "aoi1/catalog.json").write_text(
        json.dumps(
            [
                {"scene_id": s, "datetime": d, "cloud_cover": 3.0, "contains_aoi": True}
                for s, d, _ in scenes
            ]
        )
    )
    district = GRID.to_wgs84(box(*GRID.bounds)).buffer(0.05)
    (pack / "districts.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": mapping(district),
                        "properties": {"name": "Kamrup Metro"},
                    }
                ],
            }
        )
    )
    bbox = list(GRID.lonlat_bounds())
    manifest = {
        "aois": {
            "aoi1": {
                "name": "Test wetland area",
                "mode": "encroachment",
                "bbox": bbox,
                "description": "synthetic",
                "grid": GRID.to_dict(),
                "scenes": entries,
                "worldcover": {"2020": {"file": "aoi1/worldcover_2020.tif"}},
                "polygons": "aoi1/polygons.geojson",
                "catalog": "aoi1/catalog.json",
            }
        },
        "districts": {"file": "districts.geojson"},
        "built_at": "2026-09-28T00:00:00Z",
    }
    (pack / "manifest.json").write_text(json.dumps(manifest))
    from geointx.api.app import create_app

    settings = Settings(
        pack_dir=pack,
        var_dir=tmp_path / "var",
        gemini_api_key=None,
        frontend_dist=tmp_path / "none",
    )
    return TestClient(create_app(settings))


def test_full_verification_flow(client: TestClient) -> None:
    meta = client.get("/api/meta").json()
    assert meta["ai"]["enabled"] is False

    aois = client.get("/api/aois").json()
    assert aois[0]["id"] == "aoi1" and aois[0]["district"] == "Kamrup Metro"

    r = client.post("/api/runs", json={"aoi_id": "aoi1", "t1_scene_id": "S1", "t2_scene_id": "S2"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["finding_count"] == 2 and len(body["case_ids"]) == 2

    cases = client.get("/api/cases").json()["features"]
    top = cases[0]["properties"]
    assert top["transition"] == "water_loss" and top["priority_band"] == "P1"
    assert top["area_ha"] == pytest.approx(4.0)
    case_id = top["case_id"]

    detail = client.get(f"/api/cases/{case_id}", headers=REVIEWER).json()
    assert detail["case"]["status"] == "UNVERIFIED"
    assert detail["audit_chain"]["ok"] and len(detail["events"]) == 1
    assert detail["finding"]["persistence"] == pytest.approx(1.0)
    assert "start_review" in detail["allowed_actions"]

    interp = client.post(f"/api/cases/{case_id}/interpret").json()
    assert interp["interpretation"]["source"] == "template"

    # Analyst may not confirm.
    r = client.post(f"/api/cases/{case_id}/actions", json={"action": "confirm", "note": "x"})
    assert r.status_code == 409
    assert (
        client.post(
            f"/api/cases/{case_id}/actions", json={"action": "start_review"}, headers=REVIEWER
        ).status_code
        == 200
    )
    r = client.post(
        f"/api/cases/{case_id}/actions",
        json={"action": "confirm", "note": "Filling visible in field photo"},
        headers=REVIEWER,
    )
    assert r.status_code == 200 and r.json()["status"] == "CONFIRMED"

    files = {"file": ("site.jpg", b"fake-jpeg-bytes", "image/jpeg")}
    r = client.post(
        f"/api/cases/{case_id}/attachments",
        files=files,
        data={"note": "Field visit photo", "kind": "field_note"},
        headers=REVIEWER,
    )
    assert r.status_code == 200

    detail = client.get(f"/api/cases/{case_id}").json()
    assert [e["action"] for e in detail["events"]] == [
        "created",
        "start_review",
        "confirm",
        "attach",
    ]
    assert detail["audit_chain"]["ok"]

    other = cases[1]["properties"]["case_id"]
    client.post(f"/api/cases/{other}/actions", json={"action": "start_review"}, headers=REVIEWER)
    r = client.post(
        f"/api/cases/{other}/actions",
        json={
            "action": "reject",
            "note": "Harvested field",
            "reject_reason": "seasonal_or_phenology",
        },
        headers=REVIEWER,
    )
    assert r.json()["status"] == "REJECTED"

    a = client.get("/api/analytics").json()
    assert a["totals"]["confirmed"] == 1 and a["totals"]["rejected"] == 1
    assert a["totals"]["rejection_rate"] == pytest.approx(0.5)
    assert len(a["land_composition"]["aoi1"]) == 3

    ans = client.post("/api/assistant", json={"question": f"Why was {case_id} prioritised?"}).json()
    assert ans["tool"] == "get_case" and case_id in ans["answer"]
    ans = client.post(
        "/api/assistant",
        json={"question": "Which monitored wetlands have the largest detected changes?"},
    ).json()
    assert ans["tool"] == "wetland_ranking" and "Test Beel" in ans["answer"]

    plan = client.get("/api/scheduler/plan").json()
    assert [c["next_scene_id"] for c in plan["candidates"]] == ["S3"]
    cyc = client.post("/api/scheduler/cycle", json={"strategy": "marginal_value"}).json()
    assert cyc["decision"]["chosen_scene_id"] == "S3" and cyc["run"]["triggered_by"] == "scheduler"
    cyc2 = client.post("/api/scheduler/cycle", json={}).json()
    assert cyc2["decision"]["decision_source"] == "no_candidates" and cyc2["run"] is None

    report = client.get(f"/api/cases/{case_id}/report")
    assert report.status_code == 200 and "not a legal determination" in report.text
    assert "intact" in report.text
    csv_text = client.get("/api/export/cases.csv").text
    assert csv_text.splitlines()[0].startswith("case_id,status")
    gj = client.get("/api/export/cases.geojson").json()
    assert len(gj["features"]) >= 2


def test_run_rejects_reversed_dates(client: TestClient) -> None:
    r = client.post("/api/runs", json={"aoi_id": "aoi1", "t1_scene_id": "S2", "t2_scene_id": "S1"})
    assert r.status_code == 400


def test_polygon_import_validates_geometry(client: TestClient) -> None:
    r = client.post(
        "/api/aois/aoi1/polygons",
        json={"name": "Bad", "geometry": {"type": "Point", "coordinates": [91.6, 26.1]}},
    )
    assert r.status_code == 400
    ring = GRID.to_wgs84(
        box(GRID.origin_x + 900, GRID.origin_y - 1500, GRID.origin_x + 1400, GRID.origin_y - 1100)
    )
    r = client.post(
        "/api/aois/aoi1/polygons",
        json={
            "name": "Govt parcel 12 (demo)",
            "kind": "government_land",
            "geometry": mapping(ring),
        },
    )
    assert r.status_code == 200 and r.json()["official"] is False


def test_rerun_over_same_change_reobserves_instead_of_duplicating(client: TestClient) -> None:
    first = client.post(
        "/api/runs", json={"aoi_id": "aoi1", "t1_scene_id": "S1", "t2_scene_id": "S2"}
    ).json()
    assert len(first["case_ids"]) == 2
    second = client.post(
        "/api/runs", json={"aoi_id": "aoi1", "t1_scene_id": "S1", "t2_scene_id": "S3"}
    ).json()
    assert second["case_ids"] == []
    assert second["run"]["reobserved_count"] == 2
    detail = client.get(f"/api/cases/{first['case_ids'][0]}").json()
    assert [e["action"] for e in detail["events"]] == ["created", "re_observed"]
    assert detail["audit_chain"]["ok"]
