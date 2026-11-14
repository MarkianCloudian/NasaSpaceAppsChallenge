# TerraMars v2 — local research prototype

## What this version does
- Leaflet map for selecting Earth coordinates (OpenStreetMap basemap).
- Accepts real, georeferenced GeoTIFF DEM files for Mars and Earth.
- Uses Rasterio/NumPy to calculate elevation statistics, mean slope and terrain roughness.
- Ranks Earth DEMs against the Mars DEM using a transparent weighted normalized distance.
- Does not use synthetic example scores.

## Important scientific limitation
The terrain metric is complemented (in `/api/auto-compare`) by climate, mineralogy and spectral terms, but these are coarse proxies: Earth climate comes from NASA POWER climatology; Mars climate is a parametric latitude/elevation approximation (not a GCM); mineralogy uses curated literature mineral lists for catalogued Mars regions and the preset analog sites; the spectral term compares diagnostic VNIR/SWIR band centres of those minerals, not measured CRISM/spectral-library spectra. Soil chemistry is not compared. Terms unavailable for a site are dropped and weights renormalised. Earth and Mars elevation datums are not interchangeable, so absolute mean elevation is deliberately excluded from the similarity metric. DEMs should cover comparable physical areas and be projected/resampled consistently before comparison. Roughness is currently a simple gradient-derived descriptor and depends on raster resolution.

## Data sources
- NASA MOLA / PDS Geosciences Node: https://pds-geosciences.wustl.edu/missions/mgs/mola.html
- NASA PDS MOLA derived bundle: https://pds-geosciences.wustl.edu/mgs/urn-nasa-pds-mgs_mola_topography_derived/
- Copernicus DEM: https://dataspace.copernicus.eu/
- Copernicus DEM API documentation: https://documentation.v1.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM.html

NASA MOLA MEGDR is archived in PDS as IMG products with labels/headers. Do not rename raw `.img` files to `.tif`. Convert with a PDS-aware GIS workflow (for example GDAL with the correct label/header) and verify CRS, pixel scale, no-data and vertical datum. Copernicus DEM access and product availability may depend on account eligibility; GLO-90 is a practical first Earth DEM for public access.

## Run locally (Windows / Linux)
1. Install Python 3.10+.
2. Create a virtual environment:
   - Windows: `py -m venv .venv` then `.venv\\Scripts\\activate`
   - Linux/macOS: `python3 -m venv .venv` then `source .venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Start: `uvicorn app:app --reload`
5. Open: http://127.0.0.1:8000

Rasterio may require platform-specific wheels; use a recent pip and Python version supported by Rasterio.

## GeoTIFF input requirements
- One Mars DEM GeoTIFF and one or more Earth DEM GeoTIFFs.
- Single-band elevation raster, elevation values in metres.
- Georeferencing and CRS metadata must be present.
- Prefer same projected pixel size (metres per pixel), comparable patch dimensions and consistent resampling.
- NoData must be correctly defined.

## Autonomous mode (no manual file uploads)
`POST /api/auto-compare` downloads only the needed DEM windows from open sources:
- Mars: MGS MOLA global DEM 463 m (USGS Astropedia GeoTIFF; override with env `MOLA_DEM_URL`).
- Earth: Copernicus GLO-30 DEM COG tiles on the public AWS Open Data bucket (no account or key).

Both patches are resampled to 463 m/pixel and the same physical size (`size_km`, 20–200), slopes use real metre spacing (geographic degrees are converted using each body's radius), then ranked with the metric below. Candidates are the user's sites plus a built-in list of known Mars-analog areas (`GET /api/earth-presets`). Requires internet access from the server. Example body: `{"mars_lat":-18.4,"mars_lon":77.7,"size_km":50,"earth_sites":[{"name":"X","lat":-23.5,"lon":-68}]}`.

## API
- `POST /api/auto-compare` — autonomous mode (see above)
- `GET /api/earth-presets`
- `GET /api/health`
- `GET /api/sources`
- `GET /api/mola-info`
- `POST /api/analyze` — upload one GeoTIFF
- `POST /api/compare` — multipart form with `mars` and repeated `earth_files`

## Current algorithm
For each raster, calculate:
- elevation standard deviation (m)
- mean slope (degrees)
- gradient-based roughness (dimensionless gradient magnitude)

Weighted normalized distance:
`D = sqrt(sum(w_i * d_i^2) / sum(w_i))`
where each `d_i` is the absolute difference divided by a documented scale constant. Similarity index: `100 * (1 - D)`.

This is a prototype ranking score, not a probability and not a validated planetary similarity measure. Calibrate scales/weights with published analog sites and sensitivity analysis before using it in a scientific conclusion.


## Multi-factor score (auto mode)
Weights: terrain 0.50 (elevation SD, slope, roughness), climate 0.30 (temperature 0.12, log pressure 0.08, precipitation 0.10), mineralogy 0.12 (Jaccard distance of mineral sets), spectral 0.08 (Jaccard distance of binned absorption bands). Each result includes a `components` breakdown. Weights/scales are unvalidated and live in `app.py` (`WEIGHTS`) and `science.py`. The Mars catalogue (`MARS_REGIONS`) and analog minerals should be reviewed by a domain expert. Network calls (NASA POWER, MOLA, Copernicus) were not tested in CI.
