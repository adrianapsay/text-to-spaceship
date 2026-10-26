"""Named target regions and ground stations for the CubeSat Builder.

Regions are latitude/longitude boxes (degrees, west negative). A box is a simplification of the true outline: it also
covers some land and sea around the region, which the coverage analysis says. Each entry names its source.
"""
from __future__ import annotations

REGIONS = {
    "california": {
        "name": "California", "lat_min": 32.5, "lat_max": 42.0, "lon_min": -124.4, "lon_max": -114.1,
        "source": "the rounded extent of the state of California, approved as the demo target box (2026-10-25)",
        "note": "a box around the state: it also covers parts of Nevada, Arizona, Mexico and the Pacific",
    },
}

STATIONS = {
    "uc-berkeley": {
        "name": "UC Berkeley", "lat": 37.87, "lon": -122.26, "alt_m": 0.0, "min_elev_deg": 10.0,
        "source": "UC Berkeley campus, approved as the demo ground station with a 10° elevation mask (2026-10-25)",
        "note": "altitude taken as sea level (ASSUMED; a few tens of metres change nothing here)",
    },
}

# names that mean the whole region (a city or part of a state is not mapped to the state's box)
ALIASES = {"california": "california", "calif.": "california", "calif": "california"}


def region(key: str) -> dict | None:
    r = REGIONS.get(key)
    return None if r is None else {"key": key, **r}


def custom_region(lat_min: float, lat_max: float, lon_min: float, lon_max: float, name: str = "Custom region") -> dict:
    """A user-defined box; raises ValueError when it is not a valid box."""
    vals = [float(lat_min), float(lat_max), float(lon_min), float(lon_max)]
    if not (-90 <= vals[0] < vals[1] <= 90) or not (-180 <= vals[2] < vals[3] <= 180):
        raise ValueError("a region is lat_min < lat_max within ±90° and lon_min < lon_max within ±180°")
    return {"key": "custom", "name": name or "Custom region", "lat_min": vals[0], "lat_max": vals[1],
            "lon_min": vals[2], "lon_max": vals[3], "source": "entered by the user", "note": "a box"}


def station(key: str) -> dict | None:
    s = STATIONS.get(key)
    return None if s is None else {"key": key, **s}


def custom_station(lat: float, lon: float, min_elev_deg: float = 10.0, name: str = "Ground station") -> dict:
    lat, lon, mask = float(lat), float(lon), float(min_elev_deg)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180 and 0 <= mask < 90):
        raise ValueError("a station is lat within ±90°, lon within ±180°, an elevation mask from 0 to 90°")
    return {"key": "custom", "name": name or "Ground station", "lat": lat, "lon": lon, "alt_m": 0.0,
            "min_elev_deg": mask, "source": "entered by the user", "note": "altitude taken as sea level (ASSUMED)"}


def find_region(text: str) -> dict | None:
    """A known region named in free text (longest alias first), else None."""
    t = f" {text.lower()} "
    for alias in sorted(ALIASES, key=len, reverse=True):
        if f" {alias} " in t or f" {alias}." in t or f" {alias}," in t or f" {alias}!" in t:
            return region(ALIASES[alias])
    return None
