"""One-off: Natural Earth 1:110m land polygons -> SVG path data for the site map (task T059).

Usage (from the repository root):

    curl -sfLo /tmp/ne_110m_land.geojson \\
      https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_land.geojson
    uv run python src/analogfinder/site/basemap/make_basemap.py /tmp/ne_110m_land.geojson

Projection: equirectangular onto a 3600 x 1800 viewBox, x = (lon + 180) * 10,
y = (90 - lat) * 10, integer coordinates (0.1 degree). The site places candidate markers with the
same formula (`site.build.project`). Writes `land_110m.svgpath` next to this file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).with_name("land_110m.svgpath")
SCALE = 10


def project(lon: float, lat: float) -> tuple[int, int]:
    return round((lon + 180.0) * SCALE), round((90.0 - lat) * SCALE)


def ring_path(ring) -> str:
    pts: list[tuple[int, int]] = []
    for lon, lat, *_ in ring:
        p = project(lon, lat)
        if not pts or p != pts[-1]:
            pts.append(p)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) < 3:
        return ""
    head = f"M{pts[0][0]} {pts[0][1]}"
    return head + "".join(f"L{x} {y}" for x, y in pts[1:]) + "Z"


def main(src: str) -> None:
    data = json.loads(Path(src).read_text(encoding="utf-8"))
    parts: list[str] = []
    for feat in data["features"]:
        geom = feat["geometry"]
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        for poly in polys:
            for ring in poly:
                d = ring_path(ring)
                if d:
                    parts.append(d)
    OUT.write_text("".join(parts) + "\n", encoding="ascii")
    print(f"{OUT}: {OUT.stat().st_size / 1024:.1f} KB, {len(parts)} rings")


if __name__ == "__main__":
    main(sys.argv[1])
