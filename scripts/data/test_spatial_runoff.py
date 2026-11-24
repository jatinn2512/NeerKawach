import argparse
import json
import shutil

import numpy as np
import pytest
import rasterio
from affine import Affine
import run_surface_routing as runner

from prepare_surface_parameters import cosby_mm_h, fraction_map, read_soil, soil_conversion
import acquire_surface_sources as acquire
from run_manifest import checksum
from spatial_runoff import CLASSES, SCENARIOS, SpatialRunoff, load_parameters
from surface_routing_core import RoutingParameters, RainfallStep, simulate
from test_historical_p3_rainfall import BUNDLE, EVENT, ROOT, archive, runner_root


def raster(path, bands, affine, names=None, unit=None, crs="EPSG:32643"):
    data = np.asarray(bands, dtype=float)
    with rasterio.open(path, "w", driver="GTiff", width=data.shape[2], height=data.shape[1],
                       count=len(data), dtype="float64", transform=affine, crs=crs, nodata=-9999) as ds:
        ds.write(data)
        if names:
            ds.descriptions = tuple(names)
            ds.units = (unit,) * len(names)
    return path


def test_native_overlap_partial_coverage_and_area(tmp_path):
    # Target cells [0,2] and [2,4]. Source pixels have one-metre widths and a half-metre offset.
    source = raster(tmp_path/"source.tif", [[[50, 80, 10, -9999]]], Affine(1,0,.5,0,-2,10))
    dem = raster(tmp_path/"dem.tif", [[[0,0,-9999]]], Affine(2,0,0,0,-2,10))
    with rasterio.open(source) as src, rasterio.open(dem) as dst:
        valid = dst.read_masks(1) > 0
        f = fraction_map(src, dst, valid, {"50":"built_up", "80":"open_water", "10":"vegetated"})
    np.testing.assert_allclose(f[CLASSES.index("built_up"),0,:2], [.5,0])
    np.testing.assert_allclose(f[CLASSES.index("open_water"),0,:2], [.25,.25])
    np.testing.assert_allclose(f[CLASSES.index("vegetated"),0,:2], [0,.5])
    np.testing.assert_allclose(f[CLASSES.index("source_missing"),0,:2], [.25,.25])
    np.testing.assert_allclose(f[:,valid].sum(axis=0), 1)
    assert np.all(f[:,~valid] == -9999) and f[CLASSES.index("vegetated")][:,:2].sum()*4 == 2


@pytest.mark.parametrize("variable,raw,expected,unit", [
    ("sand", 500, 50, "%"), ("silt", 200, 20, "%"), ("clay", 300, 30, "%"),
    ("bdod", 130, 1.3, "g/cm3"), ("soc", 180, 18, "g/kg")])
def test_native_soil_units(variable, raw, expected, unit):
    value, actual_unit = soil_conversion(variable, raw)
    assert value == pytest.approx(expected) and actual_unit == unit


def test_soil_lookup_separates_provider_nodata_from_missing_tile(tmp_path):
    target = raster(tmp_path/"dem.tif", [[[1,1,1]]], Affine(30,0,0,0,-30,30))
    native = raster(tmp_path/"soil.tif", [[[500,-9999]]], Affine(30,0,0,0,-30,30))
    with rasterio.open(target) as dem:
        values, geometry = read_soil([native], dem, dem.read_masks(1) > 0)
    np.testing.assert_array_equal(geometry, [[True,True,False]])
    np.testing.assert_allclose(values[0,:2], [500,np.nan], equal_nan=True)


def test_vrt_selection_uses_all_intersecting_sources(tmp_path, monkeypatch):
    dem = raster(tmp_path/"dem.tif", [[[1,1]]], Affine(100,0,0,0,-100,100), crs="EPSG:32643")
    vrt = tmp_path/"soil.vrt"
    vrt.write_text('''<VRTDataset rasterXSize="2" rasterYSize="1"><SRS>EPSG:32643</SRS>
<GeoTransform>0,100,0,100,0,-100</GeoTransform><VRTRasterBand dataType="Int16" band="1">
<ComplexSource><SourceFilename>a.tif</SourceFilename><DstRect xOff="0" yOff="0" xSize="1" ySize="1"/></ComplexSource>
<ComplexSource><SourceFilename>b.tif</SourceFilename><DstRect xOff="1" yOff="0" xSize="1" ySize="1"/></ComplexSource>
<ComplexSource><SourceFilename>elsewhere.tif</SourceFilename><DstRect xOff="99" yOff="0" xSize="1" ySize="1"/></ComplexSource>
</VRTRasterBand></VRTDataset>''', encoding="utf-8")
    monkeypatch.setattr(acquire, "DEM", dem)
    _, selected = acquire.intersecting_vrt_tiles(vrt)
    assert selected == ["a.tif", "b.tif"]


def test_cosby_units_and_bounds():
    # Published coefficient expressed in cm/day, converted independently to mm/h.
    expected = 60.96 * 10**(-.884 + .0153*50) * 10 / 24
    assert cosby_mm_h(50) == pytest.approx(expected)
    assert 0 < cosby_mm_h(0) < expected < cosby_mm_h(100)
    for invalid in (-1,101,np.nan):
        with pytest.raises(ValueError):
            cosby_mm_h(invalid)


def test_mixed_surface_budget_and_cellwise_caps():
    valid = np.array([[True,True,True,True,False]])
    bed = np.zeros(valid.shape)
    # Sealed, open water, mixed, bare soil, NoData. Rain = 5 mm, soil capacity = 12 mm/h.
    model = SpatialRunoff(np.array([[0.,0.,.25,1.,0.]]), np.full(valid.shape,12.))
    rain = RainfallStep("wet", np.full(valid.shape,.005))
    result = simulate(bed, valid, [rain], 100., RoutingParameters(), spatial_runoff=model)
    np.testing.assert_allclose(model.infiltration(rain.rainfall_depth_m,300), [[0,0,.00025,.001,0]])
    assert result.total_rainfall_input_m3 == pytest.approx(2.)
    assert result.total_coefficient_loss_m3 == 0.
    assert result.total_infiltration_loss_m3 == pytest.approx(.125)
    assert result.final_stored_water_m3 == pytest.approx(1.875)
    assert (result.final_depth_m >= 0).all() and not result.final_depth_m[~valid].any()
    # Low rain caps infiltration on the pervious subarea before spatial averaging.
    assert model.infiltration(np.full(valid.shape,.0004),300)[0,2] == pytest.approx(.0001)
    bounded = SpatialRunoff(model.pervious, np.zeros(valid.shape), valid)
    np.testing.assert_allclose(bounded.infiltration(rain.rainfall_depth_m,300), model.pervious*.005)


def fixture_bundle(root, error, template=None):
    aff = Affine(30,0,700000,0,-30,1200000)
    if template is None:
        dem = raster(root/"dem.tif", [[[10,-9999]]], aff)
    else:
        dem = root/"dem.tif"
        shutil.copyfile(template,dem)
    with rasterio.open(dem) as ds:
        aff = ds.transform
        valid = ds.read_masks(1)>0
    def ref(path):
        return {"path":path.name, "sha256":checksum(path)}
    cfg = {"default_scenario":"mean_texture", "infiltration_eligible_classes":["vegetated","bare_sparse"]}
    (root/"config.json").write_text(json.dumps(cfg))
    raw = root/"raw.bin"
    raw.write_bytes(b"soil")
    products = {}
    def write(name, names, unit, values):
        data = [np.where(valid,value,-9999) for value in values]
        if error == "mask" and name == "runoff":
            data[0][0][1] = 0
        transform = Affine(aff.a,aff.b,aff.c+30,aff.d,aff.e,aff.f) if error == "affine" and name == "runoff" else aff
        crs = "EPSG:32644" if error == "crs" and name == "runoff" else "EPSG:32643"
        products[name] = ref(raster(root/(name+".tif"),data,transform,names,unit,crs))
    write("fractions",CLASSES,"1",[0,0,1,0,0,0,0])
    write("runoff",["direct_surface_fraction","pervious_fraction"],"1",[0,1])
    write("infiltration",SCENARIOS,"mm/h",[1,2,3])
    write("soil_support",SCENARIOS,"1",[1,1,1])
    write("soil_coverage",["sand_geometric_coverage","sand_property_support","infiltration_provenance_code"],"1",[1,1,1])
    bundle = {"assumptions":cfg,"version":"bellandur-fractional-rainfall-excess-v2","source_dem":ref(dem),
              "sources":{"soil":ref(raw)},"raw_tiles":{"soil":[ref(raw)]},"products":products,
              "config":ref(root/"config.json"),"osm":ref(raw)}
    manifest = root/"manifest.json"
    manifest.write_text(json.dumps(bundle))
    if error == "checksum":
        raw.write_bytes(b"changed")
    return manifest,dem


@pytest.mark.parametrize("error", ["affine","crs","mask","checksum",None])
def test_registered_parameter_bundle(tmp_path, error):
    manifest,dem = fixture_bundle(tmp_path,error)
    if error:
        with pytest.raises(ValueError, match="alignment|checksum"):
            load_parameters(tmp_path,manifest,dem)
    else:
        model, record = load_parameters(tmp_path,manifest,dem,"high_capacity")
        assert model.capacity_mm_h.tolist() == [[3.,0.]]
        assert record["parameter_manifest"]["sha256"] == checksum(manifest)
        assert record["scenario"] == "high_capacity" and record["raw_tiles"]["soil"][0]["sha256"] == checksum(tmp_path/"raw.bin")


def test_unknown_soil_provenance_cannot_be_loaded_as_supported(tmp_path):
    manifest, dem = fixture_bundle(tmp_path, None)
    bundle = json.loads(manifest.read_text())
    with rasterio.open(tmp_path/"soil_coverage.tif", "r+") as ds:
        values = ds.read()
        values[1, 0, 0] = 0  # claims unknown while the support raster remains 1
        ds.write(values)
    bundle["products"]["soil_coverage"]["sha256"] = checksum(tmp_path/"soil_coverage.tif")
    manifest.write_text(json.dumps(bundle))
    with pytest.raises(ValueError, match="Invalid surface partition or soil capacity"):
        load_parameters(tmp_path, manifest, dem)


@pytest.mark.parametrize("historical", [False, True])
def test_spatial_runner_inputs_and_manifests(archive, tmp_path, monkeypatch, historical):
    # Use a known all-pervious surface with three distinct capacities. Both runners
    # must charge the selected 3 mm/h band and publish the same parameter hashes.
    bundle_dir = archive/tmp_path.name
    bundle_dir.mkdir()
    manifest, _ = fixture_bundle(bundle_dir, None, archive/"data/surface_routing/input/dem_working.tif")
    bundle = json.loads(manifest.read_text())
    for ref in [bundle["source_dem"], bundle["config"], bundle["osm"], *bundle["sources"].values(),
                *bundle["products"].values(), *bundle["raw_tiles"]["soil"]]:
        ref["path"] = (bundle_dir/ref["path"]).relative_to(archive).as_posix()
    manifest.write_text(json.dumps(bundle))
    runner_root(monkeypatch,archive)
    args = argparse.Namespace(surface_parameters=manifest, soil_scenario="high_capacity", rainfall=None,
                              rainfall_timestep_seconds=None, temporal_manifest=None,event=None)
    if historical:
        args.temporal_manifest, args.event = archive/BUNDLE, EVENT
    else:
        inputs = {k:archive/p.relative_to(ROOT) for k,p in runner.P2_INPUTS.items()}
        for p in [*runner.P2_INPUTS.values(), ROOT/"data/surface_routing/tests/synthetic_rainfall.json"]:
            dest = archive/p.relative_to(ROOT)
            dest.parent.mkdir(exist_ok=True,parents=True)
            if not dest.exists():
                shutil.copyfile(p,dest)
        monkeypatch.setattr(runner,"P2_INPUTS",inputs)
    summary = runner.run(args)
    record = json.loads((archive/"data/runs"/summary["run_id"]/"manifest.json").read_text())
    assert record["surface_parameterization"]["parameter_manifest"]["sha256"] == checksum(manifest)
    assert record["surface_parameterization"]["scenario"] == "high_capacity"
    assert summary["total_coefficient_loss_m3"] == 0 and summary["steps"] == (228 if historical else 12)
    if historical:
        with rasterio.open(archive/summary["rainfall"]["allocated_raster"]) as ds:
            expected = sum(np.nansum(np.minimum(ds.read(band), .25))*.9 for band in ds.indexes)
    else:
        fixture = json.loads((archive/"data/surface_routing/tests/synthetic_rainfall.json").read_text())
        expected = sum(min(row["rainfall_mm"],.25) for row in fixture["records"])*.9*8914
    assert summary["total_infiltration_loss_m3"] == pytest.approx(expected,rel=0,abs=1e-7)
