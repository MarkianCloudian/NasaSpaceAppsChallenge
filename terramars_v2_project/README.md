# TerraMars v2 — local research prototype

## What this version does
- Leaflet map for selecting Earth coordinates (OpenStreetMap basemap).
- Accepts real, georeferenced GeoTIFF DEM files for Mars and Earth.
- Uses Rasterio/NumPy to calculate elevation statistics, mean slope and terrain roughness.
- Ranks Earth DEMs against the Mars DEM using a transparent weighted normalized distance.
- Does not use synthetic example scores.

## Important scientific limitation
This is a **terrain-only prototype**. It does not yet compare climate, mineralogy, soil chemistry or spectral signatures. Earth and Mars elevation datums are not interchangeable, so absolute mean elevation is deliberately excluded from the similarity metric. DEMs should cover comparable physical areas and be projected/resampled consistently before comparison. Roughness is currently a simple gradient-derived descriptor and depends on raster resolution.

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

## API
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
