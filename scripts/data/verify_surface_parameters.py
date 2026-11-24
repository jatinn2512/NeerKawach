"""Independently integrate native land-cover areas and audit two saved spatial P3 regressions."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform

from run_manifest import checksum

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def edge_integral(x, y, u, v):
    """Integrate clamp(x,0,1) dy on the part of an edge between y=0 and y=1."""
    dx, dy = u-x, v-y
    def ratio(n, d):
        return np.divide(n, d, out=np.zeros_like(n), where=d!=0)
    lo, hi = np.sort(np.clip([ratio(-y,dy), ratio(1-y,dy)], 0, 1), axis=0)
    cuts = np.sort([lo, hi, np.clip(ratio(-x,dx),lo,hi), np.clip(ratio(1-x,dx),lo,hi)], axis=0)
    values = np.clip(x + cuts*dx, 0, 1)
    return np.sum(.5*(values[1:]+values[:-1])*np.diff(cuts,axis=0)*dy, axis=0)


def native_fractions(src, dem, names, legend):
    """Green's theorem on projected native boundaries, independent of polygon clipping."""
    rows, cols = np.indices((src.height+1,src.width+1))
    xx, yy = rasterio.transform.xy(src.transform,rows.ravel(),cols.ravel(),offset="ul")
    east, north = transform(src.crs,dem.crs,xx,yy)
    x = (np.reshape(east,rows.shape)-dem.transform.c)/dem.transform.a
    y = (np.reshape(north,rows.shape)-dem.transform.f)/dem.transform.e
    def corners(a):
        return np.stack([a[:-1,:-1],a[:-1,1:],a[1:,1:],a[1:,:-1]]).reshape(4,-1)
    x, y = corners(x), corners(y)
    land = src.read(1,masked=True)
    category = np.full(land.size, names.index("source_missing"))
    for code, name in legend.items():
        category[(land.data.ravel()==int(code)) & ~np.ma.getmaskarray(land).ravel()] = names.index(name)
    f = np.zeros((len(names),*dem.shape))
    left, top = np.floor(x.min(axis=0)).astype(int), np.floor(y.min(axis=0)).astype(int)
    right, bottom = np.floor(x.max(axis=0)).astype(int), np.floor(y.max(axis=0)).astype(int)
    for i in range(int(np.max(bottom-top))+1):
        for j in range(int(np.max(right-left))+1):
            r,c = top+i,left+j
            use = (r>=0)&(r<dem.height)&(r<=bottom)&(c>=0)&(c<dem.width)&(c<=right)
            xx, yy = x[:,use]-c[use], y[:,use]-r[use]
            area = sum(edge_integral(xx[k],yy[k],xx[(k+1)%4],yy[(k+1)%4]) for k in range(4))
            np.add.at(f,(category[use],r[use],c[use]),abs(area))
    # Account for any part of the target outside the source extent.
    f[names.index("source_missing")] += np.maximum(0.,1-f.sum(axis=0))
    return f


def native_soils(bundle,dem,valid,names):
    rows,cols = np.where(valid)
    x,y = rasterio.transform.xy(dem.transform,rows,cols)
    arrays = []
    geometric = []
    for name in names:
        values = np.full(valid.sum(),np.nan)
        inside_any_tile = np.zeros(valid.sum(), dtype=bool)
        for ref in bundle["raw_tiles"][name]:
            with rasterio.open(ROOT/ref["path"]) as native:
                xx,yy = transform(dem.crs,native.crs,x,y)
                rr,cc = rasterio.transform.rowcol(native.transform,xx,yy)
                inside = (rr>=0)&(rr<native.height)&(cc>=0)&(cc<native.width)
                arr = native.read(1,masked=True).astype(float).filled(np.nan)
                values[inside] = arr[rr[inside],cc[inside]]
                inside_any_tile[inside] = True
        divisor = 100 if name.startswith("bdod") else 10
        arrays.append(values/divisor)
        geometric.append(inside_any_tile)
    return np.array(arrays), np.array(geometric)


def verify(synthetic_run,historical_run):
    with ExitStack() as stack:
        summaries = [read(run/"results/summary.json") for run in (synthetic_run,historical_run)]
        parameter_ref = summaries[0]["surface_parameterization"]["parameter_manifest"]
        bundle_path = ROOT/parameter_ref["path"]
        assert checksum(bundle_path)==parameter_ref["sha256"]
        bundle = read(bundle_path)
        for ref in [bundle["config"],bundle["osm"],bundle["source_dem"],*bundle["products"].values(),
                    *bundle["sources"].values(),*bundle["preparation_code"]]:
            assert checksum(ROOT/ref["path"]) == ref["sha256"]
        for src in bundle["sources"].values():
            path = ROOT/src["path"]
            for item in read(path)["files"]:
                assert checksum(path.parent/item["file"]) == item["sha256"]
        dem = stack.enter_context(rasterio.open(ROOT/bundle["source_dem"]["path"]))
        valid = dem.read_masks(1)>0
        assert valid.sum()==8914 and (~valid).sum()==301
        area = abs(dem.transform.determinant)
        def product(name):
            ds = stack.enter_context(rasterio.open(ROOT/bundle["products"][name]["path"]))
            assert (ds.shape,ds.crs,ds.transform)==(dem.shape,dem.crs,dem.transform)
            return ds
        cover = stack.enter_context(rasterio.open(ROOT/bundle["raw_tiles"]["worldcover_2021_v200"][0]["path"]))
        ds = product("fractions")
        names = ds.descriptions
        fractions = native_fractions(cover,dem,names,bundle["assumptions"]["worldcover_classes"])[:,valid]
        saved = ds.read()[:,valid]
        assert np.all((ds.read_masks()>0)==valid)
        np.testing.assert_allclose(saved,fractions,rtol=0,atol=2e-9)
        np.testing.assert_allclose(saved.sum(axis=0),1.,rtol=0,atol=1e-12)
        assert np.all((saved>=0)&(saved<=1+1e-12))
        soil = product("soil_attributes")
        native, native_geometry = native_soils(bundle,dem,valid,soil.descriptions)
        np.testing.assert_allclose(soil.read(masked=True).filled(np.nan)[:,valid],native,atol=1e-12,rtol=0)
        assert not (soil.read_masks()[:,~valid]!=0).any()
        pervious = fractions[names.index("vegetated")]+fractions[names.index("bare_sparse")]
        runoff, rates, support = product("runoff"),product("infiltration"),product("soil_support")
        coverage = product("soil_coverage")
        evidence = product("paved_road_evidence")
        for ds in (runoff,rates,support,evidence,coverage):
            assert np.all((ds.read_masks()>0)==valid)
        np.testing.assert_allclose(runoff.read()[:,valid],[1-pervious,pervious],atol=2e-9,rtol=0)
        scenario_indices = [soil.descriptions.index(bundle["assumptions"]["scenarios"][scenario])
                            for scenario in rates.descriptions]
        scenario_known = np.logical_and.reduce([np.isfinite(native[index]) for index in scenario_indices])
        scenario_geometry = np.logical_and.reduce([native_geometry[index] for index in scenario_indices])
        for i,scenario in enumerate(rates.descriptions):
            sand = native[soil.descriptions.index(bundle["assumptions"]["scenarios"][scenario])]
            known = scenario_known
            # Independent form in cm/day, converted to mm/h.
            k = np.where(known,60.96*10**(-.884+.0153*sand)*10/24,0)
            np.testing.assert_array_equal(support.read(i+1)[valid],known)
            np.testing.assert_allclose(rates.read(i+1)[valid],k,rtol=1e-13)
        expected_provenance = np.where(scenario_known, 1, np.where(scenario_geometry, 2, 3))
        assert coverage.descriptions == ("sand_geometric_coverage", "sand_property_support", "infiltration_provenance_code")
        np.testing.assert_array_equal(coverage.read(1)[valid], scenario_geometry)
        np.testing.assert_array_equal(coverage.read(2)[valid], scenario_known)
        np.testing.assert_array_equal(coverage.read(3)[valid], expected_provenance)
        report = {"max_fraction_error":float(np.max(abs(saved-fractions))),
                  "max_fraction_sum_error":float(np.max(abs(saved.sum(axis=0)-1))),
                  "class_area_m2":dict(zip(names,(fractions.sum(axis=1)*area).tolist())), "runs":[]}
        for run,s in zip((synthetic_run,historical_run),summaries):
            record = read(run/"manifest.json")
            active = s["surface_parameterization"]
            assert record["status"]=="succeeded" and all(v["passed"] for v in record["validations"])
            assert record["surface_parameterization"]["parameter_manifest"]==active["parameter_manifest"]==parameter_ref
            for ref in record["inputs"]+record["outputs"]:
                assert checksum(ROOT/ref["path"])==ref["sha256"]
            idx = rates.descriptions.index(active["scenario"])
            k = rates.read(idx+1)[valid]
            known = support.read(idx+1)[valid]>0
            report["unsupported_pervious_area_m2"] = float(area*pervious[~known].sum())
            hist = run==historical_run
            timeline = s["time_series"]
            if hist:
                rain = stack.enter_context(rasterio.open(ROOT/s["rainfall"]["allocated_raster"]))
                assert (rain.shape,rain.crs,rain.transform)==(dem.shape,dem.crs,dem.transform)
                assert rain.count==len(timeline)==228
            else:
                fixture = read(ROOT/"data/surface_routing/tests/synthetic_rainfall.json")["records"]
                assert len(timeline)==len(fixture)==12
            maxima = np.zeros(valid.sum(),dtype="float32")
            total_rain = total_loss = gap_rain = 0.
            totals = np.zeros(len(rates.descriptions))
            frame_residual = 0.
            for i,row in enumerate(timeline):
                assert row["index"]==i
                if hist:
                    assert row["band"]==i+1 and row["relative_end_seconds"]==(i+1)*300
                    field = rain.read(i+1)
                    np.testing.assert_array_equal(np.isfinite(field),valid)
                    depth = field[valid]/1000.
                else:
                    assert row["timestamp"]==fixture[i]["timestamp"]
                    depth = np.full(valid.sum(),fixture[i]["rainfall_mm"]/1000.)
                potential = np.minimum(depth,k/12000.)
                if active["missing_soil"] == "rainfall-limit":
                    potential[~known] = depth[~known]
                loss = pervious*potential
                gross = float(depth.sum()*area)
                total_rain += gross
                total_loss += float(loss.sum()*area)
                gap_rain += float(depth[~known]@pervious[~known]*area)
                for j in range(len(totals)):
                    totals[j] += float(pervious@np.minimum(depth,rates.read(j+1)[valid]/12000.)*area)
                assert abs(row["rainfall_input_m3"]-gross)<1e-7 and row["coefficient_loss_m3"]==0.
                assert abs(row["infiltration_loss_m3"]-area*loss.sum())<1e-6
                assert abs(row["surface_water_input_m3"]-area*(depth-loss).sum())<1e-6
                frame_residual = max(frame_residual,abs(total_rain-total_loss-row["stored_surface_water_m3"]))
                with rasterio.open(ROOT/row["depth_file"]) as frame:
                    assert (frame.shape,frame.crs,frame.transform)==(dem.shape,dem.crs,dem.transform)
                    assert frame.tags()["TIMESTAMP"]==row["timestamp"]
                    np.testing.assert_array_equal(frame.read_masks(1)>0,valid)
                    water = frame.read(1)[valid]
                    assert np.all(np.isfinite(water)&(water>=0))
                    np.maximum(maxima,water,out=maxima)
            assert frame_residual<1e-6 and abs(s["total_rainfall_input_m3"]-total_rain)<1e-7
            with rasterio.open(ROOT/s["outputs"]["max_depth"]) as ds:
                np.testing.assert_array_equal(ds.read_masks(1)>0,valid)
                np.testing.assert_array_equal(ds.read(1)[valid],maxima)
            peak = timeline[s["maximum_depth_index"]]
            assert peak["timestamp"]==s["maximum_depth_timestamp"] and peak["depth_file"]==s["domain_peak_depth_file"]
            with rasterio.open(ROOT/peak["depth_file"]) as ds:
                assert ds.read(1)[valid].max()==maxima.max()==np.float32(s["maximum_depth_m"])
            report["runs"].append({"run":run.name,"rainfall_m3":total_rain,"infiltration_m3":total_loss,
                "storage_m3":s["final_stored_water_m3"],"max_independent_balance_residual_m3":frame_residual,
                "infiltration_by_texture_scenario_m3":dict(zip(rates.descriptions,totals.tolist())),
                "additional_infiltration_rainfall_limit_m3":gap_rain,"peak_m":s["maximum_depth_m"],
                "peak_timestamp":s["maximum_depth_timestamp"]})
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-run", type=Path, required=True)
    parser.add_argument("--historical-run", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.synthetic_run,args.historical_run),indent=2))
