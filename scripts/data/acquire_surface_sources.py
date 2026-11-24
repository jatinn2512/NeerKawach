"""Archive original WorldCover and SoilGrids files intersecting the Bellandur working DEM."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from uuid import uuid4
from urllib.parse import urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import numpy as np
import rasterio
from affine import Affine
from rasterio.warp import transform, transform_bounds
from rasterio.windows import Window, from_bounds

from run_manifest import checksum

ROOT = Path(__file__).resolve().parents[2]
DEM = ROOT / "data/surface_routing/input/dem_working.tif"
RAW = ROOT / "data/landcover/raw"
ESA = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N12E075_Map.tif"
ISRIC = "https://files.isric.org/soilgrids/latest/data/"
SOIL_LAYERS = ["sand_0-5cm_mean", "sand_0-5cm_Q0.05", "sand_0-5cm_Q0.95",
               "silt_0-5cm_mean", "clay_0-5cm_mean", "bdod_0-5cm_mean", "soc_0-5cm_mean"]


@contextmanager
def publish_directory(target):
    """Inherit workspace permissions and expose files only after successful preparation."""
    folder = target.parent / f".partial-{uuid4()}"
    folder.mkdir()
    try:
        yield folder
        if target.exists():
            raise FileExistsError(target)
        folder.rename(target)
    finally:
        if folder.exists():
            for file in folder.iterdir():
                file.unlink()
            folder.rmdir()


def fetch(url, folder):
    path = folder / url.rsplit("/", 1)[1]
    with urlopen(url, timeout=90) as response, path.open("xb") as stream:
        while chunk := response.read(1024 * 1024):
            stream.write(chunk)
        length = response.headers.get("Content-Length")
        if length and stream.tell() != int(length):
            raise IOError(f"Incomplete download from {url}")
        return path, {"url": url, "file": path.name,
                      "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                      "last_modified": response.headers.get("Last-Modified"), "etag": response.headers.get("ETag")}


def native_cover_window(folder):
    """Preserve original categorical values and native grid for the buffered DEM plus one pixel."""
    path = folder / "ESA_WorldCover_10m_2021_v200_N12E075_Map_Bellandur.tif"
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_TIMEOUT="60"), rasterio.open(ESA) as src:
        with rasterio.open(DEM) as dem:
            bounds = transform_bounds(dem.crs, src.crs, *dem.bounds, densify_pts=41)
        win = from_bounds(*bounds, transform=src.transform)
        left, top = math.floor(win.col_off)-1, math.floor(win.row_off)-1
        right, bottom = math.ceil(win.col_off+win.width)+1, math.ceil(win.row_off+win.height)+1
        win = Window(left, top, right-left, bottom-top)
        values = src.read(1, window=win)
        with rasterio.open(path, "w", driver="GTiff", width=win.width, height=win.height, count=1,
                           dtype=src.dtypes[0], nodata=src.nodata, transform=src.window_transform(win),
                           crs=src.crs, compress="deflate") as dest:
            dest.write(values, 1)
        source_grid = {"shape": list(src.shape), "bounds": list(src.bounds), "native_window": list(win.flatten())}
    with urlopen(Request(ESA, method="HEAD"), timeout=45) as response:
        return path, {"url": ESA, "file": path.name, "source_grid": source_grid,
                      "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                      "last_modified": response.headers.get("Last-Modified"), "etag": response.headers.get("ETag"),
                      "extraction": "Native pixel window of the provider COG, read without resampling"}


def soil_vrt_url(key):
    """Return the authoritative mosaic index, never a guessed individual tile."""
    property_name = key.split("_")[0]
    return f"{ISRIC}{property_name}/{key}.vrt"


def intersecting_vrt_tiles(vrt_path):
    """Return VRT sources whose declared destination rectangles meet the DEM.

    SoilGrids distributes a global mosaic through a VRT plus many GeoTIFFs.
    Selecting one tile by name silently turns a tile-edge acquisition mistake
    into apparent soil NoData, so the VRT is the authority for selection.
    """
    root = ET.parse(vrt_path).getroot()
    affine = Affine.from_gdal(*map(float, root.findtext("GeoTransform").split(",")))
    with rasterio.open(DEM) as dem:
        bounds = transform_bounds(dem.crs, root.findtext("SRS"), *dem.bounds, densify_pts=41)
    window = from_bounds(*bounds, transform=affine)
    selected = []
    for source in root.findall(".//ComplexSource") + root.findall(".//SimpleSource"):
        rect = source.find("DstRect")
        filename = source.findtext("SourceFilename")
        if rect is None or not filename:
            continue
        x, y, w, h = (float(rect.get(name)) for name in ("xOff", "yOff", "xSize", "ySize"))
        if x < window.col_off + window.width and x+w > window.col_off and y < window.row_off + window.height and y+h > window.row_off:
            selected.append(filename)
    if not selected:
        raise ValueError(f"SoilGrids VRT contains no tile intersecting {DEM}")
    return root, sorted(set(selected))


def acquire(key, url, soil):
    target = RAW / key
    manifest = target / "source.json"
    if target.exists():
        record = json.loads(manifest.read_text(encoding="utf-8"))
        if any(checksum(target / item["file"]) != item["sha256"] for item in record["files"]):
            raise ValueError(f"Existing archive failed checksum verification: {target}")
        return manifest
    with publish_directory(target) as folder:
        path, origin = fetch(url, folder) if soil else native_cover_window(folder)
        files = [origin]
        selected_tiles = []
        if soil:
            _, selected_tiles = intersecting_vrt_tiles(path)
            for filename in selected_tiles:
                _, item = fetch(urljoin(url, filename), folder)
                files.append(item)
        for item in files:
            f = folder / item["file"]
            item["sha256"] = checksum(f)
            if f.suffix == ".tif":
                with rasterio.open(f) as ds:
                    item.update(crs=ds.crs.to_wkt(), bounds=list(ds.bounds), shape=list(ds.shape),
                                transform=list(ds.transform)[:6], nodata=ds.nodata, dtype=ds.dtypes[0])
        if soil:
            # Coverage is deliberately checked from the full selected mosaic,
            # not required from each individual tile.
            with rasterio.open(DEM) as dem:
                rows, cols = np.where(dem.read_masks(1) != 0)
                xs, ys = rasterio.transform.xy(dem.transform, rows, cols)
            covered = np.zeros(len(rows), dtype=bool)
            for item in files[1:]:
                with rasterio.open(folder / item["file"]) as ds:
                    # Transform centres rather than bounds: this exactly matches
                    # preparation's native-pixel lookup support definition.
                    tx, ty = transform(dem.crs, ds.crs, xs, ys)
                    rr, cc = rasterio.transform.rowcol(ds.transform, tx, ty)
                    covered |= ((rr >= 0) & (cc >= 0) & (rr < ds.height) & (cc < ds.width))
            if not covered.all():
                raise ValueError(f"SoilGrids VRT tile selection does not geometrically cover {int((~covered).sum())} valid DEM centres")
        record = {"key": key, "provider": "ISRIC" if soil else "ESA WorldCover Consortium",
                  "product": "SoilGrids 2.0" if soil else "WorldCover 2021 v200",
                  "reference": "https://docs.isric.org/globaldata/soilgrids/" if soil else
                               "https://doi.org/10.5281/zenodo.7254221",
                  "licence": "CC BY 4.0", "native_resolution_m": 250 if soil else 10,
                  "observation_period": "Multiyear soil-profile synthesis; no event date" if soil else "2021",
                  "depth_cm": [0, 5] if soil else None, "files": files,
                  "tile_selection": ("all VRT tiles intersecting the working DEM; provider NoData is retained" if soil else None),
                  "selected_vrt_sources": selected_tiles if soil else None}
        (folder / "source.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    jobs = [("worldcover_2021_v200", ESA, False)]
    for layer in SOIL_LAYERS:
        jobs.append((layer, soil_vrt_url(layer), True))
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = [pool.submit(acquire, *job) for job in jobs]
        for task in tasks:
            print(task.result(), flush=True)


if __name__ == "__main__":
    main()
