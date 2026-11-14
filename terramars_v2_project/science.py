"""Non-terrain descriptors: climate, mineralogy and spectral (VNIR/SWIR) signatures.

Honesty notes (also shown in API caveats):
 * Earth climate: NASA POWER climatology (open, no key), 2 m air temperature,
   precipitation and surface pressure at the patch centre.
 * Mars climate: simple parametric approximation (no live Mars Climate Database
   query): annual-mean temperature from latitude, pressure from MOLA elevation
   and a 11.1 km scale height, precipitation = 0.
 * Mineralogy: curated lists from the literature for known Mars regions and
   Earth analog sites. Points outside the catalogue get no mineral/spectral term.
 * Spectral: diagnostic VNIR/SWIR absorption band centres of those minerals
   (not measured CRISM/spectral-library spectra).
"""
import math
from functools import lru_cache
import requests

POWER_URL = "https://power.larc.nasa.gov/api/temporal/climatology/point"

@lru_cache(maxsize=256)
def earth_climate(lat: float, lon: float):
    """Annual climatology from NASA POWER. Returns dict or raises ValueError."""
    try:
        r = requests.get(POWER_URL, params={"parameters": "T2M,PRECTOTCORR,PS", "community": "RE",
                                            "latitude": round(lat, 3), "longitude": round(lon, 3),
                                            "format": "JSON"}, timeout=30)
        r.raise_for_status()
        p = r.json()["properties"]["parameter"]
        t, pr, ps = p["T2M"]["ANN"], p["PRECTOTCORR"]["ANN"], p["PS"]["ANN"]
        if min(t, pr, ps) < -900:  # POWER fill value
            raise ValueError("fill value")
    except Exception as e:
        raise ValueError(f"NASA POWER climate unavailable: {e}")
    return {"temp_K": t + 273.15, "precip_mm_day": pr, "pressure_Pa": ps * 1000.0,
            "climate_source": "NASA POWER climatology (Earth)"}

def mars_climate(lat: float, mean_elev_m: float):
    s = math.sin(math.radians(lat)) ** 2
    return {"temp_K": 218.0 - 63.0 * s,
            "precip_mm_day": 0.0,
            "pressure_Pa": 610.0 * math.exp(-mean_elev_m / 11100.0),
            "climate_source": "Parametric Mars approximation (latitude/elevation), not a GCM"}

# --- Mineralogy -----------------------------------------------------------
MARS_REGIONS = [
    {"name": "Jezero", "lat": 18.4, "lon": 77.7, "r_km": 250, "minerals": ["olivine", "carbonate", "smectite", "pyroxene"]},
    {"name": "Gale", "lat": -5.4, "lon": 137.8, "r_km": 250, "minerals": ["smectite", "hematite", "gypsum", "pyroxene", "plagioclase"]},
    {"name": "Meridiani Planum", "lat": -2.0, "lon": -5.0, "r_km": 300, "minerals": ["hematite", "jarosite", "gypsum", "mg-sulfate"]},
    {"name": "Nili Fossae", "lat": 21.0, "lon": 74.5, "r_km": 300, "minerals": ["olivine", "carbonate", "smectite", "serpentine"]},
    {"name": "Mawrth Vallis", "lat": 24.0, "lon": -19.0, "r_km": 250, "minerals": ["smectite", "kaolinite", "silica"]},
    {"name": "Juventae / Valles Marineris", "lat": -4.0, "lon": -62.0, "r_km": 400, "minerals": ["mg-sulfate", "gypsum", "hematite"]},
    {"name": "Syrtis Major", "lat": 8.4, "lon": 69.5, "r_km": 400, "minerals": ["pyroxene", "plagioclase", "olivine"]},
    {"name": "Gusev / Columbia Hills", "lat": -14.6, "lon": 175.5, "r_km": 250, "minerals": ["olivine", "pyroxene", "silica", "hematite"]},
]

BANDS_UM = {  # diagnostic VNIR/SWIR absorption band centres (um)
    "olivine": [1.05], "pyroxene": [0.95, 1.9], "plagioclase": [1.25],
    "hematite": [0.53, 0.86], "jarosite": [0.43, 0.93, 1.47, 2.27],
    "gypsum": [1.45, 1.75, 1.94, 2.22], "mg-sulfate": [1.43, 1.97, 2.4],
    "smectite": [1.41, 1.91, 2.30], "kaolinite": [1.41, 2.17, 2.21],
    "carbonate": [2.30, 2.51], "perchlorate": [1.43, 1.93],
    "silica": [1.4, 1.91, 2.21], "serpentine": [1.39, 2.32], "chloride": [],
}

def _km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 3396.19 * math.asin(math.sqrt(a))

def mars_minerals(lat, lon):
    best = min(MARS_REGIONS, key=lambda g: _km(lat, lon, g["lat"], g["lon"]))
    if _km(lat, lon, best["lat"], best["lon"]) <= best["r_km"]:
        return {"minerals": best["minerals"], "mineral_source": f"Literature catalogue: {best['name']}"}
    return {}

def bands(minerals):
    return sorted({round(round(b / 0.05) * 0.05, 2) for m in minerals for b in BANDS_UM.get(m, [])})

def _jaccard_dist(a, b):
    a, b = set(a), set(b)
    return None if not (a | b) else 1 - len(a & b) / len(a | b)

def add_descriptors(d):
    """Derive band list and return d (in place)."""
    if d.get("minerals"):
        d["spectral_bands_um"] = bands(d["minerals"])
    return d

def extra_distances(m, e):
    """Per-term distances in [0,1] for climate/mineral/spectral terms (only those available)."""
    out = {}
    if m.get("temp_K") is not None and e.get("temp_K") is not None:
        out["temp_K"] = min(abs(m["temp_K"] - e["temp_K"]) / 100.0, 1.0)
    if m.get("pressure_Pa") and e.get("pressure_Pa"):
        out["pressure_log10"] = min(abs(math.log10(m["pressure_Pa"]) - math.log10(e["pressure_Pa"])) / 3.0, 1.0)
    if m.get("precip_mm_day") is not None and e.get("precip_mm_day") is not None:
        out["precip_mm_day"] = min(abs(m["precip_mm_day"] - e["precip_mm_day"]) / 2.0, 1.0)
    if m.get("minerals") and e.get("minerals"):
        out["mineral_jaccard"] = _jaccard_dist(m["minerals"], e["minerals"])
    if m.get("spectral_bands_um") and e.get("spectral_bands_um"):
        d = _jaccard_dist(m["spectral_bands_um"], e["spectral_bands_um"])
        if d is not None:
            out["spectral_bands"] = d
    return out
