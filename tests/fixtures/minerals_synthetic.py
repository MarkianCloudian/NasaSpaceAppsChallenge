"""Tiny synthetic EMIT L2B MIN granule and CRISM summary-parameter file with known content."""
from pathlib import Path

import h5py
import numpy as np

EMIT_NAMES = ["sulfate_gypsum", "smectite_montmorillonite_ca_swelling",
              "carbonate_calcite", "fe3+_hematite.fine.gr.gds76", "organic_plastic-pete"]
EMIT_CENTER = (30.0, 10.0)   # lat, lon of the scene centre
EMIT_STEP = 0.001            # deg per ortho pixel
EMIT_N = 40                  # ortho grid is N x N; raw grid is the same, mapped 1:1


def write_emit_granule(path: Path):
    """Group 2: gypsum everywhere except a 10x10 montmorillonite block (rows/cols 15-24) and a
    2-pixel calcite cluster; band depth 0.05. Group 1: 5x5 hematite block, band depth 0.01.
    Bottom-right 5x5 pixels are outside the scene (GLT = 0)."""
    n = EMIT_N
    g2 = np.full((n, n), 1, np.int16)
    g2[15:25, 15:25] = 2
    g2[5, 5:7] = 3
    g1 = np.zeros((n, n), np.int16)
    g1[30:35, 5:10] = 4
    bd2 = np.full((n, n), 0.05, np.float32)
    bd1 = np.where(g1 > 0, 0.01, 0).astype(np.float32)
    rr, cc = np.mgrid[1:n + 1, 1:n + 1]
    glt_x, glt_y = cc.astype(np.int32), rr.astype(np.int32)
    glt_x[-5:, -5:] = 0
    glt_y[-5:, -5:] = 0
    lat0, lon0 = EMIT_CENTER
    gt = [lon0 - n / 2 * EMIT_STEP, EMIT_STEP, 0.0, lat0 + n / 2 * EMIT_STEP, 0.0, -EMIT_STEP]
    with h5py.File(path, "w") as h:
        h.attrs["geotransform"] = np.array(gt)
        h["group_1_mineral_id"], h["group_2_mineral_id"] = g1, g2
        h["group_1_band_depth"], h["group_2_band_depth"] = bd1, bd2
        loc = h.create_group("location")
        loc["glt_x"], loc["glt_y"] = glt_x, glt_y
        mm = h.create_group("mineral_metadata")
        mm["index"] = np.arange(1, len(EMIT_NAMES) + 1)
        mm["name"] = np.array([s.encode() for s in EMIT_NAMES])
    return path


CRISM_BANDS = ["R770", "D2300", "BD2210_2", "MIN2295_2480", "SINDEX2", "OLINDEX3"]
CRISM_N, CRISM_PX = 50, 100.0
CRISM_WKT = ('PROJCS["Mars Equirectangular",GEOGCS["GCS_Mars",DATUM["D_Mars",SPHEROID["Mars",3396190.0,0.0]],'
             'PRIMEM["Reference_Meridian",0.0],UNIT["Degree",0.0174532925199433]],PROJECTION["Equidistant_Cylindrical"],'
             'PARAMETER["False_Easting",0.0],PARAMETER["False_Northing",0.0],PARAMETER["Central_Meridian",0.0],'
             'PARAMETER["Standard_Parallel_1",0.0],UNIT["Meter",1.0]]')


def write_crism_su(directory: Path, name="frt0000abcd_07_su165j_mtr3"):
    """50x50 px of 100 m centred on (0°, 0°). D2300 = 0.02 in the top-left 10x10 block,
    OLINDEX3 = 0.2 in a 5x5 block at rows/cols 20-24; bottom 5 rows = 65535 (no data)."""
    n = CRISM_N
    cube = np.zeros((len(CRISM_BANDS), n, n), np.float32)
    cube[CRISM_BANDS.index("D2300"), :10, :10] = 0.02
    cube[CRISM_BANDS.index("OLINDEX3"), 20:25, 20:25] = 0.2
    cube[:, -5:, :] = 65535.0
    img = Path(directory) / f"{name}.img"
    cube.tofile(img)
    ul = -n / 2 * CRISM_PX
    img.with_suffix(".hdr").write_text(
        "ENVI\n"
        f"samples = {n}\nlines = {n}\nbands = {len(CRISM_BANDS)}\nheader offset = 0\n"
        "file type = ENVI Standard\ndata type = 4\ninterleave = bsq\nbyte order = 0\n"
        f"map info = {{Mars Equirectangular, 1.0, 1.0, {ul}, {-ul}, {CRISM_PX}, {CRISM_PX}, units=Meters}}\n"
        f"coordinate system string = {{{CRISM_WKT}}}\n"
        "data ignore value = 6.55350000e+04\n"
        "band names = {\n " + ", ".join(CRISM_BANDS) + "}\n")
    return img
