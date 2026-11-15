# Basemap

`land_110m.svgpath` is SVG path data of the world's land outline, drawn under the candidate
markers on the site map.

- **Source:** Natural Earth 1:110m physical vectors, `ne_110m_land` (public domain),
  GeoJSON from <https://github.com/nvkelso/natural-earth-vector> `geojson/ne_110m_land.geojson`,
  branch `master` at commit `ca96624a56bd` (VERSION file: 5.2.0-pre), retrieved 2026-11-15.
- **Projection:** equirectangular on a 3600 × 1800 viewBox, `x = (lon + 180) × 10`,
  `y = (90 − lat) × 10`, integer coordinates (0.1°). Candidate markers use the same formula.
- **Regenerate:** see the docstring of `make_basemap.py`.

Natural Earth: "Made with Natural Earth. Free vector and raster map data @ naturalearthdata.com."
