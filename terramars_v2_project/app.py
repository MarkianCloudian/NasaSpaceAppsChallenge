from pathlib import Path
import os, re, tempfile, requests
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.enums import Resampling as RioResampling
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
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

def safe_stats(path: Path):
    try:
        with rasterio.open(path) as ds:
            arr = ds.read(1, masked=True).astype("float64")
            a = np.asarray(arr.compressed())
            if a.size < 10:
                raise ValueError("Raster contains too few valid pixels.")
            # Basic terrain statistics. Slope/roughness are derived from the DEM.
            xres = abs(ds.transform.a)
            yres = abs(ds.transform.e)
            gy, gx = np.gradient(np.asarray(arr.filled(np.nan)), yres, xres)
            slope = np.degrees(np.arctan(np.sqrt(gx*gx + gy*gy)))
            rough = np.sqrt(gx*gx + gy*gy)
            valid_slope = slope[np.isfinite(slope)]
            valid_rough = rough[np.isfinite(rough)]
            return {
                "name": path.stem,
                "width": ds.width, "height": ds.height,
                "crs": str(ds.crs), "bounds": list(ds.bounds),
                "resolution": [xres, yres],
                "elevation_mean": float(np.mean(a)),
                "elevation_std": float(np.std(a)),
                "elevation_min": float(np.min(a)),
                "elevation_max": float(np.max(a)),
                "slope_mean": float(np.mean(valid_slope)) if valid_slope.size else None,
                "roughness_mean": float(np.mean(valid_rough)) if valid_rough.size else None,
                "valid_pixels": int(a.size)
            }
    except Exception as e:
        raise ValueError(f"Cannot read raster: {e}")

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
    # Compare only physically comparable terrain descriptors, normalized by
    # documented scale constants. Elevation absolute means are excluded because
    # Earth sea-level and Mars areoid datums differ.
    scales = {"elevation_std": 5000.0, "slope_mean": 45.0, "roughness_mean": 1.0}
    weights = {"elevation_std": .35, "slope_mean": .35, "roughness_mean": .30}
    results = []
    for e in earth:
        terms = []
        for k, scale in scales.items():
            a, b = m.get(k), e.get(k)
            if a is not None and b is not None and np.isfinite(a) and np.isfinite(b):
                terms.append((weights[k], min(abs(a-b)/scale, 1.0)))
        if not terms: continue
        wsum = sum(w for w, _ in terms)
        dist = float(np.sqrt(sum(w*(d**2) for w,d in terms)/wsum))
        results.append({"name": e["name"], "similarity_index": round(100*(1-dist), 2),
                        "distance": round(dist, 5), "earth": e})
    results.sort(key=lambda x: x["similarity_index"], reverse=True)
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
