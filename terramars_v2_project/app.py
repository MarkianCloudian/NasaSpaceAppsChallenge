from pathlib import Path
import os, re, tempfile, requests
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.enums import Resampling as RioResampling
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel, Field
from functools import lru_cache
import math
from rasterio.windows import from_bounds
import science
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
EARTH_R = 6371008.8
MARS_R = 3396190.0
app = FastAPI(title="TerraMars Research Prototype", version="2.0")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

@app.get("/")
def home():
    return FileResponse(BASE / "static" / "index.html")

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0", "data_mode": "real rasters via upload / MOLA source downloader"}

@app.get("/api/mola-info")
def mola_info():
    return {
        "source": "NASA PDS Geosciences Node — MGS MOLA MEGDR",
        "url": "https://pds-geosciences.wustl.edu/mgs/urn-nasa-pds-mgs_mola_topography_derived/",
        "note": "MOLA products are distributed as PDS IMG + labels/headers. Select the appropriate MEGDR tile and upload its georeferenced GeoTIFF conversion. Do not treat raw IMG as GeoTIFF."
    }

def _stats_from_array(arr, xres, yres, name, extra=None):
    """arr: masked 2-D array (elevation, m). xres/yres: pixel size in metres."""
    a = np.asarray(arr.compressed()).astype("float64")
    if a.size < 10:
        raise ValueError("Raster contains too few valid pixels.")
    z = np.asarray(arr.astype("float64").filled(np.nan))
    gy, gx = np.gradient(z, yres, xres)
    rough = np.sqrt(gx * gx + gy * gy)
    slope = np.degrees(np.arctan(rough))
    valid_slope = slope[np.isfinite(slope)]
    valid_rough = rough[np.isfinite(rough)]
    out = {
        "name": name,
        "width": int(z.shape[1]), "height": int(z.shape[0]),
        "resolution_m": [float(xres), float(yres)],
        "elevation_mean": float(np.mean(a)),
        "elevation_std": float(np.std(a)),
        "elevation_min": float(np.min(a)),
        "elevation_max": float(np.max(a)),
        "slope_mean": float(np.mean(valid_slope)) if valid_slope.size else None,
        "roughness_mean": float(np.mean(valid_rough)) if valid_rough.size else None,
        "valid_pixels": int(a.size),
    }
    out.update(extra or {})
    return out

def safe_stats(path: Path, radius_m: float = EARTH_R):
    try:
        with rasterio.open(path) as ds:
            arr = ds.read(1, masked=True)
            xres, yres = abs(ds.transform.a), abs(ds.transform.e)
            if ds.crs is not None and ds.crs.is_geographic:
                # degrees -> metres (sphere of the given body radius)
                lat_c = (ds.bounds.top + ds.bounds.bottom) / 2
                m_per_deg = radius_m * math.pi / 180
                xres_m, yres_m = xres * m_per_deg * max(math.cos(math.radians(lat_c)), 1e-3), yres * m_per_deg
            else:
                xres_m, yres_m = xres, yres
            return _stats_from_array(arr, xres_m, yres_m, path.stem,
                                     {"crs": str(ds.crs), "bounds": list(ds.bounds), "resolution": [xres, yres]})
    except Exception as e:
        raise ValueError(f"Cannot read raster: {e}")

SCALES = {"elevation_std": 5000.0, "slope_mean": 45.0, "roughness_mean": 1.0}
# Terrain 0.50, climate 0.30, mineralogy 0.12, spectral 0.08. Terms missing for a
# site are dropped and the remaining weights renormalised.
WEIGHTS = {"elevation_std": .175, "slope_mean": .175, "roughness_mean": .15,
           "temp_K": .12, "pressure_log10": .08, "precip_mm_day": .10,
           "mineral_jaccard": .12, "spectral_bands": .08}

def rank_sites(m, earth):
    # Absolute mean elevation is excluded: Earth sea-level and Mars areoid datums differ.
    results = []
    for e in earth:
        terms = []
        for k, scale in SCALES.items():
            a, b = m.get(k), e.get(k)
            if a is not None and b is not None and np.isfinite(a) and np.isfinite(b):
                terms.append((k, min(abs(a - b) / scale, 1.0)))
        terms += [(k, v) for k, v in science.extra_distances(m, e).items() if v is not None]
        if not terms:
            continue
        wsum = sum(WEIGHTS[k] for k, _ in terms)
        dist = float(np.sqrt(sum(WEIGHTS[k] * d ** 2 for k, d in terms) / wsum))
        results.append({"name": e["name"], "similarity_index": round(100 * (1 - dist), 2),
                        "distance": round(dist, 5), "earth": e,
                        "components": {k: round(d, 4) for k, d in terms},
                        "terms_used": len(terms)})
    results.sort(key=lambda x: x["similarity_index"], reverse=True)
    return results

# ---------------------------------------------------------------------------
# Autonomous mode: fetch DEMs from open sources, no manual uploads.
#  Earth: Copernicus GLO-30 DEM, public AWS Open Data bucket (COG, no account)
#  Mars : MGS MOLA global DEM 463 m (USGS Astropedia), windowed HTTP reads
# Only the requested window is downloaded (HTTP range requests via /vsicurl/).
# ---------------------------------------------------------------------------
COPERNICUS_URL = "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DEM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM/Copernicus_DEM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM.tif"
MOLA_URL = os.environ.get("MOLA_DEM_URL", "https://planetarymaps.usgs.gov/mosaic/Mars/MGS_MOLA/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif")
PIXEL_M = 463.0  # common analysis pixel size = native MOLA resolution
GDAL_ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_TIMEOUT="60", AWS_NO_SIGN_REQUEST="YES")

# Well-known terrestrial Mars-analog areas (used when the user gives no sites).
ANALOG_SITES = [
    {"name": "Atacama Desert, Chile", "lat": -23.5, "lon": -68.0, "minerals": ['gypsum', 'perchlorate', 'chloride', 'hematite']},
    {"name": "Dry Valleys, Antarctica", "lat": -77.5, "lon": 162.5, "minerals": ['pyroxene', 'plagioclase', 'gypsum', 'chloride']},
    {"name": "Devon Island, Canada", "lat": 75.4, "lon": -89.8, "minerals": ['carbonate', 'gypsum', 'silica']},
    {"name": "Death Valley, USA", "lat": 36.5, "lon": -117.1, "minerals": ['carbonate', 'gypsum', 'chloride', 'smectite']},
    {"name": "Dallol / Danakil, Ethiopia", "lat": 14.2, "lon": 40.3, "minerals": ['olivine', 'pyroxene', 'plagioclase', 'gypsum', 'chloride', 'jarosite']},
    {"name": "Krafla / Askja, Iceland", "lat": 65.0, "lon": -16.8, "minerals": ['olivine', 'pyroxene', 'plagioclase', 'smectite', 'silica']},
    {"name": "Hanksville (MDRS), Utah", "lat": 38.4, "lon": -110.8, "minerals": ['smectite', 'gypsum', 'hematite']},
    {"name": "Rio Tinto, Spain", "lat": 37.7, "lon": -6.6, "minerals": ['jarosite', 'hematite', 'gypsum']},
    {"name": "Lut Desert, Iran", "lat": 30.5, "lon": 58.5, "minerals": ['gypsum', 'chloride', 'plagioclase']},
    {"name": "Tibesti, Chad", "lat": 21.0, "lon": 17.5, "minerals": ['olivine', 'pyroxene', 'plagioclase']},
]

class Site(BaseModel):
    name: str = "site"
    minerals: list[str] = []
    lat: float = Field(ge=-85, le=85)
    lon: float = Field(ge=-180, le=180)

class AutoRequest(BaseModel):
    mars_lat: float = Field(ge=-85, le=85)
    mars_lon: float = Field(ge=-180, le=360)
    mars_name: str = "Mars AOI"
    size_km: float = Field(default=50, ge=20, le=200)
    earth_sites: list[Site] = []
    include_presets: bool = True

def _grid(lat, lon, size_km, radius_m):
    """Return (n pixels, degree step, west, north) of a square patch."""
    n = int(round(size_km * 1000 / PIXEL_M))
    step = PIXEL_M / (radius_m * math.pi / 180)
    return n, step, lon - n * step / 2, lat + n * step / 2

def _copernicus_tile_url(lat_i, lon_i):
    return COPERNICUS_URL.format(ns="N" if lat_i >= 0 else "S", lat=abs(lat_i),
                                 ew="E" if lon_i >= 0 else "W", lon=abs(lon_i))

def fetch_earth_patch(site: Site, size_km: float):
    n, step, west, north = _grid(site.lat, site.lon, size_km, EARTH_R)
    dst = np.full((n, n), np.nan, dtype="float32")
    dst_tf = rasterio.transform.from_origin(west, north, step, step)
    east, south = west + n * step, north - n * step
    found = False
    with rasterio.Env(**GDAL_ENV):
        for lat_i in range(math.floor(south), math.floor(north) + 1):
            for lon_i in range(math.floor(west), math.floor(east) + 1):
                try:
                    with rasterio.open(_copernicus_tile_url(lat_i, lon_i)) as src:
                        tmp = np.full((n, n), np.nan, dtype="float32")
                        reproject(rasterio.band(src, 1), tmp, dst_transform=dst_tf, dst_crs="EPSG:4326",
                                  resampling=Resampling.average, dst_nodata=np.nan)
                        m = np.isfinite(tmp)
                        dst[m] = tmp[m]
                        found = found or bool(m.any())
                except rasterio.errors.RasterioIOError:
                    continue  # tile does not exist (ocean) or is unreachable
    if not found:
        raise ValueError("No Copernicus DEM data for this location (ocean or source unreachable).")
    arr = np.ma.masked_invalid(dst)
    lat_c = site.lat
    return _stats_from_array(arr, PIXEL_M * math.cos(math.radians(lat_c)), PIXEL_M, site.name,
                             {"lat": site.lat, "lon": site.lon, "size_km": size_km,
                              "source": "Copernicus GLO-30 DEM (AWS Open Data), resampled to 463 m"})

def fetch_mars_patch(lat, lon, size_km, name):
    n, step, west, north = _grid(lat, lon, size_km, MARS_R)
    with rasterio.Env(**GDAL_ENV):
        try:
            src = rasterio.open(MOLA_URL)
        except rasterio.errors.RasterioIOError as e:
            raise ValueError(f"MOLA source unreachable: {e}")
        with src:
            # match the file's longitude convention (0..360 or -180..180)
            if src.bounds.right > 180:
                west = west % 360
            elif west < -180 or west + n * step > 180:
                raise ValueError("Mars patch crosses the antimeridian; shift the AOI.")
            if west + n * step > src.bounds.right or north > src.bounds.top or north - n * step < src.bounds.bottom:
                raise ValueError("Mars patch is outside the MOLA raster extent; shift the AOI.")
            win = from_bounds(west, north - n * step, west + n * step, north, src.transform)
            arr = src.read(1, window=win, out_shape=(n, n), masked=True, resampling=RioResampling.average)
    return _stats_from_array(arr, PIXEL_M * math.cos(math.radians(lat)), PIXEL_M, name,
                             {"lat": lat, "lon": lon, "size_km": size_km,
                              "source": "MGS MOLA global DEM 463 m (USGS Astropedia / NASA)"})

def enrich(stats, planet, notes):
    """Attach climate + mineralogy + spectral descriptors; failures are non-fatal."""
    lat, lon = stats["lat"], stats["lon"]
    try:
        stats.update(science.earth_climate(lat, lon) if planet == "earth"
                     else science.mars_climate(lat, stats["elevation_mean"]))
    except ValueError as e:
        notes.append({"name": stats["name"], "warning": str(e)})
    if planet == "mars":
        stats.update(science.mars_minerals(lat, lon if lon <= 180 else lon - 360))
    return science.add_descriptors(stats)

@app.get("/api/earth-presets")
def earth_presets():
    return ANALOG_SITES

@app.post("/api/auto-compare")
def auto_compare(req: AutoRequest):
    """Fully autonomous: download Mars + Earth DEM windows from open sources and rank."""
    try:
        mars = fetch_mars_patch(req.mars_lat, req.mars_lon, req.size_km, req.mars_name)
    except ValueError as e:
        raise HTTPException(502, str(e))
    errors = []
    enrich(mars, "mars", errors)
    sites = list(req.earth_sites)
    if req.include_presets or not sites:
        sites += [Site(**s) for s in ANALOG_SITES]
    earth = []
    for s in sites:
        try:
            p = fetch_earth_patch(s, req.size_km)
            if s.minerals:
                p["minerals"], p["mineral_source"] = s.minerals, "Literature catalogue (analog site)"
            earth.append(enrich(p, "earth", errors))
        except Exception as e:
            errors.append({"name": s.name, "error": str(e)})
    if not earth:
        raise HTTPException(502, f"No Earth DEM could be fetched: {errors}")
    return {"mars": mars, "method": "Weighted normalized distance: terrain 0.50, climate 0.30, mineralogy 0.12, spectral 0.08 (missing terms dropped, weights renormalised)",
            "caveat": "Prototype. Climate for Mars is a parametric approximation, not a GCM; mineralogy/spectral terms use curated literature mineral lists and diagnostic band centres, only for catalogued Mars regions and preset analog sites (not measured CRISM spectra). Absolute elevation is excluded because planetary vertical datums differ. Similarity index is not a probability. Both patches are resampled to 463 m/pixel and the same physical size.",
            "results": rank_sites(mars, earth), "errors": errors}

@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), label: str = "uploaded"):
    if not file.filename.lower().endswith((".tif", ".tiff")):
        raise HTTPException(400, "Upload a GeoTIFF (.tif/.tiff).")
    dest = DATA / (re.sub(r"[^a-zA-Z0-9_.-]", "_", file.filename))
    content = await file.read()
    if len(content) > 300 * 1024 * 1024:
        raise HTTPException(413, "File exceeds 300 MB limit.")
    dest.write_bytes(content)
    try:
        stats = safe_stats(dest)
    except ValueError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, str(e))
    stats["label"] = label
    stats["source_file"] = dest.name
    stats["source_type"] = "user-provided real GeoTIFF"
    return stats

@app.post("/api/compare")
async def compare(mars: UploadFile = File(...), earth_files: list[UploadFile] = File(...)):
    if len(earth_files) == 0:
        raise HTTPException(400, "Upload at least one Earth GeoTIFF.")
    async def save_and_stats(f):
        if not f.filename.lower().endswith((".tif", ".tiff")):
            raise HTTPException(400, f"{f.filename}: expected GeoTIFF.")
        p = DATA / re.sub(r"[^a-zA-Z0-9_.-]", "_", f.filename)
        p.write_bytes(await f.read())
        try: return safe_stats(p)
        except ValueError as e: raise HTTPException(422, f"{f.filename}: {e}")
    m = await save_and_stats(mars)
    earth = [await save_and_stats(f) for f in earth_files]
    results = rank_sites(m, earth)
    return {"mars": m, "method": "Weighted normalized terrain distance",
            "caveat": "Terrain-only prototype. Absolute elevation is excluded because planetary vertical datums differ. Similarity index is not a probability.",
            "results": results}

@app.get("/api/sources")
def sources():
    return [
      {"name":"NASA MOLA MEGDR","url":"https://pds-geosciences.wustl.edu/missions/mgs/mola.html","type":"Mars DEM"},
      {"name":"Copernicus DEM","url":"https://dataspace.copernicus.eu/","type":"Earth DEM"},
      {"name":"PDS Orbital Data Explorer","url":"https://ode.rsl.wustl.edu/","type":"Planetary data catalogue"}
    ]
