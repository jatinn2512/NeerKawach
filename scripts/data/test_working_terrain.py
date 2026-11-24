import json
import math
from pathlib import Path
import shutil

import numpy as np
import pytest
import rasterio
from affine import Affine

from assess_catchments import path_statistics
from derive_terrain import (INTEGER_NODATA, classify_depressions, contributing_cells_and_terminals,
                            sha256, steepest_d8, write_low_points)
from working_terrain import connected_flats, write_working_terrain


@pytest.mark.parametrize("affine", [Affine(1,0,77,0,-1,13), Affine(2,.25,77,.5,-3,13)])
def test_low_points_at_affine_centres(tmp_path, affine):
    f = dict(row=1, column=3, elevation_m=871., sink_type="local_minimum", neighbor_count=8)
    path = tmp_path / "points.geojson"
    write_low_points([f], affine, dict(min_lon=0,min_lat=0,max_lon=100,max_lat=100), path)
    data = json.loads(path.read_text())
    point, = data["features"]
    assert data["crs"]["properties"]["name"] == "EPSG:4326"
    assert point["properties"] == f and point["id"] == "sink-1-3"
    x, y = rasterio.transform.xy(affine, 1, 3, offset="center")
    assert point["geometry"]["coordinates"] == [x, y]


@pytest.mark.parametrize("affine,expected", [(Affine.scale(1,-1),1), (Affine(2,1,7,.5,-1,9),8)])
def test_steepest_gradient_in_physical_distance(affine, expected):
    bed = np.full((3,3), 11.)
    bed[1,1], bed[1,2], bed[2,0] = 10., 8., 8.1
    valid = np.ones(bed.shape, dtype=bool)
    assert steepest_d8(bed, valid, affine)[1,1] == expected
    valid[2,0] = False
    d = steepest_d8(bed, valid, affine)
    assert d[1,1] == 1 and d[2,0] == INTEGER_NODATA


def test_unresolved_flat_with_draining_lip_and_boundary_sink():
    bed = np.full((5,5), 3.)
    bed[1:4,1:4] = 2.
    bed[0,0] = 1.
    valid = np.ones(bed.shape, dtype=bool)
    d = steepest_d8(bed, valid, Affine.scale(30,-30))
    classes, _ = classify_depressions(bed, valid, d)
    flats, groups = connected_flats(bed, valid, d)
    group = groups[flats[2,2]-1]
    assert group["cells"] == 9 and group["cells_with_direct_descent"] == 1
    assert d[1,1] == 32 and d[2,2] == 0 and classes[2,2] == 2
    assert d[0,0] == 0 and classes[0,0] == 3
    counts, terminal = contributing_cells_and_terminals(d, valid)
    assert terminal[1,1] == terminal[0,0] and terminal[2,2] != terminal[0,0]
    assert counts[d == 0].sum() == valid.sum()


@pytest.mark.parametrize("direction,valid,error", [
    ([[1,16]], [[True,True]], "cycle"), ([[1,0]], [[True,False]], "leaves valid"),
    ([[64]], [[True]], "leaves valid"), ([[7]], [[True]], "Invalid D8")])
def test_invalid_graph_rejected(direction, valid, error):
    with pytest.raises(ValueError, match=error):
        contributing_cells_and_terminals(np.array(direction), np.array(valid))


def test_contributing_area_products_and_unknown_terminals(tmp_path):
    path = tmp_path / "dem.tif"
    affine = Affine(2,1,100,.5,-1,120)
    dem = np.array([[3,3,3],[3,0,3],[3,3,3]], dtype=np.float32)
    with rasterio.open(path, "w", driver="GTiff", width=3,height=3,count=1,dtype="float32",
                       crs="EPSG:32643",transform=affine,nodata=-9999) as ds:
        ds.write(dem,1)
    meta = write_working_terrain(tmp_path,path,tmp_path / "out")
    def read(key):
        product = meta["products"][key]
        f = tmp_path / product["file"]
        assert product["sha256"] == sha256(f)
        with rasterio.open(f) as ds:
            assert ds.transform == affine and ds.tags()["SOURCE_DEM_SHA256"] == sha256(path)
            return ds.read(1)
    np.testing.assert_array_equal(read("flow_direction"), [[2,4,8],[1,0,16],[128,64,32]])
    counts = np.ones((3,3),int)
    counts[1,1] = 9
    np.testing.assert_array_equal(read("flow_accumulation"), counts)
    np.testing.assert_array_equal(read("contributing_area"), counts*2.5)
    assert np.all(read("terminal_cell") == 5) and read("depressions")[1,1] == 1
    assert meta["unresolved_cells"] == 1 and meta["terminal_contributing_cells"] == 9
    assert meta["outlet_status"] == "unverified terrain terminals"


def test_boundary_paths_and_nodata_partition():
    valid = np.array([[True, True, True, False]])
    study = np.array([[True,True,False,False]])
    dem = np.array([[3.,2.,1.,-9999.]])
    d = steepest_d8(dem,valid,Affine.scale(1,-1))
    counts, terminal = contributing_cells_and_terminals(d,valid)
    np.testing.assert_array_equal(counts, [[1,2,3,INTEGER_NODATA]])
    np.testing.assert_array_equal(terminal, [[3,3,3,INTEGER_NODATA]])
    stats = path_statistics(d,dem,valid,study)
    assert stats["study_paths_leaving_study"] == 2
    assert stats["source_path_destinations"] == {"unresolved_terminal": 3}
    assert stats["directed_edges"] == {"downhill": 2}


def test_bellandur_directions_and_areas_from_independent_paths(tmp_path):
    root = Path(__file__).resolve().parents[2]
    path = tmp_path / "dem.tif"
    shutil.copyfile(root / "data/surface_routing/input/dem_working.tif", path)
    with rasterio.open(path) as ds:
        bed = ds.read(1).astype(float)
        valid = ds.read_masks(1) != 0
        affine = ds.transform
    meta = write_working_terrain(tmp_path, path, tmp_path / "terrain")
    products = {}
    for name, record in meta["products"].items():
        with rasterio.open(tmp_path / record["file"]) as ds:
            np.testing.assert_array_equal(ds.read_masks(1) != 0, valid)
            products[name] = ds.read(1)

    # Rank drops using actual transformed cell centres, then walk from each
    # source separately to count all visits without a topological traversal.
    offsets = [(-1, 0, 64), (-1, 1, 128), (0, 1, 1), (1, 1, 2),
               (1, 0, 4), (1, -1, 8), (0, -1, 16), (-1, -1, 32)]
    rows, columns = np.where(valid)
    xs, ys = rasterio.transform.xy(affine, rows, columns, offset="center")
    centres = dict(zip(zip(rows, columns), zip(xs, ys)))
    receivers = {}
    for cell in centres:
        r, c = cell
        choices = []
        for dr, dc, code in offsets:
            neighbour = (r + dr, c + dc)
            if neighbour in centres and bed[neighbour] < bed[cell]:
                slope = (bed[cell] - bed[neighbour]) / math.dist(centres[cell], centres[neighbour])
                choices.append((slope, code, neighbour))
        expected = 0
        if choices:
            _, expected, receivers[cell] = max(choices, key=lambda entry: entry[0])
        assert products["flow_direction"][cell] == expected

    visits = np.zeros(valid.shape, dtype=int)
    for source in centres:
        cell = source
        while cell in receivers:
            visits[cell] += 1
            cell = receivers[cell]  # Elevation strictly decreases on every step.
        visits[cell] += 1
        assert products["terminal_cell"][source] == 1 + cell[0] * valid.shape[1] + cell[1]
    np.testing.assert_array_equal(products["flow_accumulation"][valid], visits[valid])
    np.testing.assert_array_equal(products["contributing_area"][valid], visits[valid] * 900)
    assert len(centres) == 8914 and len(receivers) == 7625
