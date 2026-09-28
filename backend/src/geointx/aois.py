"""Seed monitored areas for the Assam demonstration.

Bounding boxes are lon/lat (min_lon, min_lat, max_lon, max_lat). Boundaries for
monitored polygons are fetched from OpenStreetMap by the demo-pack builder and
are explicitly NOT official government records.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from geointx.models import AoiMode


@dataclass(frozen=True)
class OsmBoundary:
    osm_type: str  # "relation" | "way"
    osm_id: int
    name: str
    kind: str  # wetland | protected_area | government_land | water_body | other


@dataclass(frozen=True)
class AoiSeed:
    id: str
    name: str
    mode: AoiMode
    bbox: tuple[float, float, float, float]
    description: str
    osm_boundaries: tuple[OsmBoundary, ...] = field(default_factory=tuple)
    buffer_ring_m: float | None = None  # derive a watch buffer around the first boundary


SEED_AOIS: tuple[AoiSeed, ...] = (
    AoiSeed(
        id="deepor_beel",
        name="Deepor Beel wetland, Guwahati",
        mode="encroachment",
        bbox=(91.595, 26.095, 91.705, 26.165),
        description=(
            "Ramsar-listed freshwater wetland on the south-west edge of Guwahati, with a "
            "wildlife sanctuary inside it. Monitored for changes to water and wetland "
            "vegetation inside the mapped boundary and in a 200 m watch buffer around it."
        ),
        osm_boundaries=(
            OsmBoundary("relation", 9630968, "Deepor Beel (OSM wetland outline)", "wetland"),
            OsmBoundary("way", 677514328, "Deepor Beel Wildlife Sanctuary (OSM)", "protected_area"),
        ),
        buffer_ring_m=200.0,
    ),
    AoiSeed(
        id="north_guwahati",
        name="Amingaon - Changsari corridor, North Guwahati",
        mode="lulc",
        bbox=(91.62, 26.17, 91.74, 26.27),
        description=(
            "Peri-urban corridor on the north bank of the Brahmaputra opposite Guwahati. "
            "Monitored for land-use / land-cover change: agricultural and vegetated land "
            "converting to bare or built-up surfaces."
        ),
    ),
    AoiSeed(
        id="majuli",
        name="Majuli river island, south bank",
        mode="lulc",
        bbox=(94.10, 26.88, 94.25, 26.98),
        description=(
            "Part of Majuli, the Brahmaputra river island. Monitored for bank erosion and "
            "accretion (water to land and land to water change) and land-cover change."
        ),
    ),
)

SEED_BY_ID = {a.id: a for a in SEED_AOIS}
