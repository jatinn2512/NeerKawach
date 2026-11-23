# Spatial rainfall mapping

From the repository root, run the offline mapper with the existing data-processing Python environment.

```powershell
python -B scripts/data/map_rainfall.py
```

The default maps every available MOSDAC and IMD native file. To map one product, pass `--source mosdac_insat3dr` or `--source imd_ncmrwf_gpm_merged_daily`. An optional `--output-root` selects a different local destination. The mapper reads the working DEM named in `data/surface_routing/input/working_grid.json` and checks its CRS, shape, affine and cell area against that metadata. The DEM band mask and finite elevations define the valid domain, including the buffer.

## Measurements and coverage

The Task 2.2 raw-file readers supply `RainfallRecord` objects. The mapper uses the row, column, CRS and full native cell footprint from the GeoTIFF or GrADS control definition. Source selection uses the geographic bounding box of the complete target grid. Mapping and integration use only valid DEM cells.

`FootprintMap(grid, records)` computes overlap areas for a native layout. Geographic cell edges are sampled at most 0.00025° apart and transformed with Rasterio/GDAL. The projected polygons are clipped against individual target rectangles. Material overlaps between different native footprints on the valid domain raise an error, including overlapping pixels whose summed areas would still fit inside one target cell. Areas are projected square metres. The supported target is a north-up metre grid.

`weights.map(records, measurement)` processes one source label. Its return value includes the mean over covered area, valid covered area, coverage fraction, source-validity mask, contributing native pixels, both conservation integrals and their units. A missing pixel contributes no area or rainfall. A measured zero contributes its area with zero rainfall. A cell with no valid source contribution has an undefined rainfall value. Partial coverage retains the mean over the actual covered area.

| Measurement | Value | Spatial integral |
|---|---|---|
| MOSDAC `rate` | Native rate interpreted as mm/h | m³/h |
| MOSDAC `derived_depth` | mm under the existing rate × 0.5 h assumption | m³ |
| IMD `daily_depth` | Native daily accumulation in mm | m³ |

For each field, the mapper integrates the saved mean times its valid covered area, divided by 1,000. A second calculation integrates each source footprint directly against contiguous valid runs in the DEM mask using a boundary integral, independently of the cell weights. The comparisons allow 1e−6 m² absolute for areas, 1e−7 m³ or m³/h absolute for measurements, and 1e−11 relative. Tests also check the real MOSDAC boundary by inverse-projecting target-cell corners. That independent geometry check allows 0.0005 m² per cell for linearization along a 30 m edge.

## Reading the products

Open `data/rainfall/mapped/<source>/latest.json`. Its relative `manifest` path identifies a complete snapshot. Compare the manifest's SHA-256 digest with `manifest_sha256` to verify its contents. A successful rerun with identical artifacts reuses the snapshot. The mapper updates the pointer after all files close and receive checksums.

| File in the snapshot | Contents |
|---|---|
| `rate.tif`, `derived_depth.tif`, or `daily_depth.tif` | Float64 measurements. One band per available source label in chronological order. Band descriptions contain UTC labels. NaN is nodata. |
| `coverage_N.tif` | Bands 1–3 contain covered area in m², coverage fraction, and a 0/1 source-validity mask. Uncovered valid terrain has zeros. All three bands are nodata on invalid terrain. |
| `overlap_N.tif` | One band per native pixel in that layout. Values are geometric overlap areas in m². Use the coverage product's valid pixel list to identify contributors for that frame. |
| `dem_valid.tif` | Explicit terrain mask, 1 valid and 0 terrain nodata. |
| `manifest.json` | Input and raster SHA-256 hashes, processing status, software versions, target grid, native geometries, source records, original labels, missing labels, units, derivations, coverage products, and per-band conservation results. |

Follow `frames[].band` and `frames[].measurements[measurement].coverage` together. Frames with identical spatial support share a coverage raster. Bounds and pixel centres keep their native CRS, and transforms use GDAL coefficient order. The MOSDAC records retain their nominal 4 km resolution. Both native footprints contribute along their common boundary. Missing labels have no raster band. The unknown MOSDAC time anchor and IMD daily cutoff remain explicit in the source records.

Electronic City has station support only. Open-Meteo lacks model cell boundaries. RainViewer supplies visualization references, and the local IMERG archive has no observations. Their eligibility reasons are recorded in each manifest. The output contains no temporal disaggregation and is independent of the P3 runner.
