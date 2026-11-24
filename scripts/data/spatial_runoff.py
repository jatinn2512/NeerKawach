"""Load registered sub-cell surface fractions and predicted pervious infiltration rates."""
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
import rasterio

from run_manifest import checksum

CLASSES = ("built_up", "paved_road", "vegetated", "bare_sparse", "open_water", "other", "source_missing")
SCENARIOS = ("low_capacity", "mean_texture", "high_capacity")


@dataclass(frozen=True)
class SpatialRunoff:
    pervious: np.ndarray
    capacity_mm_h: np.ndarray
    rain_limited: np.ndarray | None = None

    def infiltration(self, rain_m, seconds):
        infiltrated = np.minimum(rain_m, self.capacity_mm_h * seconds / 3600000.)
        if self.rain_limited is not None:
            infiltrated = np.where(self.rain_limited, rain_m, infiltrated)
        return self.pervious * infiltrated


def load_parameters(root, manifest, dem_path, scenario=None, missing_soil="zero-credit"):
    path = Path(manifest).resolve()
    bundle = json.loads(path.read_text(encoding="utf-8"))
    scenario = scenario or bundle["assumptions"]["default_scenario"]
    idx = SCENARIOS.index(scenario)
    if missing_soil not in ("zero-credit", "rainfall-limit"):
        raise ValueError("Unknown missing soil policy")
    if (bundle["version"] != "bellandur-fractional-rainfall-excess-v2"
            or checksum(dem_path) != bundle["source_dem"]["sha256"]):
        raise ValueError("Spatial parameters require a compatible derivation and source DEM")
    refs = [bundle["config"], bundle["osm"], *bundle["sources"].values(),
            *bundle["products"].values(), *(ref for group in bundle["raw_tiles"].values() for ref in group)]
    for ref in refs:
        if checksum(root / ref["path"]) != ref["sha256"]:
            raise ValueError(f"Spatial parameter checksum mismatch for {ref['path']}")
    settings = json.loads((root / bundle["config"]["path"]).read_text(encoding="utf-8"))
    if settings != bundle["assumptions"]:
        raise ValueError("Spatial assumptions disagree with configuration")
    with rasterio.open(dem_path) as dem:
        valid = dem.read_masks(1) != 0
        def read(name, bands, unit):
            with rasterio.open(root / bundle["products"][name]["path"]) as ds:
                if (ds.shape != dem.shape or ds.crs != dem.crs or ds.transform != dem.transform
                        or ds.descriptions != tuple(bands) or ds.units != (unit,) * len(bands)
                        or not np.all((ds.read_masks() != 0) == valid)):
                    raise ValueError(f"Spatial parameter alignment, bands, units or mask mismatch in {name}")
                data = ds.read().astype(np.float64)
                if not np.isfinite(data[:,valid]).all():
                    raise ValueError(f"Nonfinite spatial parameters in {name}")
                data[:,~valid] = 0.
                return data
        fractions = read("fractions", CLASSES, "1")
        direct, pervious = read("runoff", ["direct_surface_fraction", "pervious_fraction"], "1")
        rates = read("infiltration", SCENARIOS, "mm/h")
        support = read("soil_support", SCENARIOS, "1")
        coverage = read("soil_coverage", ["sand_geometric_coverage", "sand_property_support", "infiltration_provenance_code"], "1")
        expected = sum(fractions[CLASSES.index(k)] for k in settings["infiltration_eligible_classes"])
        if (np.any(fractions < 0) or np.any(fractions > 1+1e-9)
                or not np.allclose(fractions[:,valid].sum(axis=0), 1, rtol=0, atol=1e-9)
                or not np.allclose(pervious, expected, rtol=0, atol=1e-9)
                or not np.allclose((direct+pervious)[valid], 1, rtol=0, atol=1e-9)
                or np.any(rates < 0) or not np.isin(support, [0,1]).all() or np.any(rates[support==0] != 0)
                or not np.isin(coverage[:,valid], [1,2,3]).all()
                or not np.array_equal(support[idx], coverage[1])
                or not np.array_equal((support[idx] == 1), coverage[2] == 1)
                or np.any((coverage[2] == 2) & (coverage[0] != 1))):
            raise ValueError("Invalid surface partition or soil capacity")
    provenance = {"mode": "spatial", "scenario": scenario, "missing_soil": missing_soil, "parameter_manifest": {
        "path": path.relative_to(root).as_posix(), "sha256": checksum(path)}, **bundle}
    rain_limited = (support[idx] == 0) if missing_soil == "rainfall-limit" else None
    return SpatialRunoff(np.clip(pervious, 0, 1), rates[idx], rain_limited), provenance
