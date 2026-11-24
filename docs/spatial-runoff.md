# P3 spatial runoff for Bellandur

The spatial parameter set covers 8,914 valid 30 m cells (8.0226 km²) on the buffered EPSG:32643 working DEM. SoilGrids provides surface texture at 4,842 cell centres. The remaining 4,072 contain 2.272 km² of mapped pervious area, or 37.35% of the mapped pervious total. For the September 2022 event, changing the infiltration assumption on that area moves final storage from 18,315 to 8,579 m³ and domain peak depth from 0.5730 to 0.4195 m. These are sensitivity results. Predictive accuracy requires field observations.

## Inputs and provenance

The starting inventory contained two land-cover README placeholders, OSM road and drainage linework, and uniform P3 parameters (runoff coefficient 0.75 and infiltration limit 0.5 mm/h). It contained no land-cover raster, soil survey, measured impervious fraction, local conductivity tests or event soil moisture. Input files were acquired on **24 November 2026**. Each source directory contains the native raster and a `source.json` with the exact request URL, retrieval time, ETag, SHA-256, bounds, CRS, transform and NoData. The processed manifest indexes all sources and checksums. [Local parameter manifest](../data/landcover/processed/af7af70b-4fe1-44aa-b68d-74e39956e9fe/manifest.json)

| Source | Native support | Use |
|---|---|---|
| ESA WorldCover Consortium, 2021 v200, CC BY 4.0 | Nominal 10 m, 1/12,000° pixels, EPSG:4326, NoData 0 | Lossless native 322 × 322 window from tile N12E075. Bounds 77.646667–77.673500° E, 12.921500–12.948333° N. Land-cover classes describe 2021. [Product and attribution](https://esa-worldcover.org/en/data-access) · [Legend](https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/docs/WorldCover_PUM_V2.0.pdf) |
| ISRIC SoilGrids 2.0, CC BY 4.0 | 250 m Interrupted Goode Homolosine, top 0–5 cm, NoData −32768 | Multiyear model predictions of sand, silt, clay, bulk density and organic carbon, with sand 5th and 95th percentiles. Each working-cell centre uses its containing native soil pixel. The output retains the native spatial support and depth interval. [Product and licence](https://docs.isric.org/globaldata/soilgrids/) · [Units, uncertainty and soil mask](https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_01.html) |
| OpenStreetMap contributors, local snapshot dated 18 September 2026, ODbL | Road centreline geometries with variable positional accuracy and no supplied road widths | Of 248 ways, 39 carry a paved surface tag and touch 254 valid cells. The evidence band identifies their presence. The snapshot postdates the event. [Local source](../data/roads/raw/bellandur_highways_overpass.json) · [Attribution and licence](https://www.openstreetmap.org/copyright) |

### Archived raster SHA-256

The two local OSM extracts contain no building footprints or mapped water-surface polygons. The drainage extract supplies 11 drain ways. Their centrelines provide drainage context only. [Local OSM drainage extract](../data/drainage/raw/osm_drainage_overpass.json)

| Raster | SHA-256 |
|---|---|
| WorldCover native window | `8a9840f7eed4960be849dd75691e3f3e52652f8c5ac1c070936ad9cbc02ac4f5` |
| Mean sand | `80c4fd34595caee9238aa63a39dd11d03d77e97b77a137ca496d98b1bdffaef4` |
| Sand Q0.05 | `3a909ec091cce6804f50ce700dcba63d148e8029d8601187553e63dd9a8ba4f2` |
| Sand Q0.95 | `09eab201744654b202c32e4e68253e6010b599e52ca08006198c76eab6be3f7e` |
| Mean silt | `b3a6026d57291d7a8309e7c1607252c150fd9d5c84e6412edd36af2be79571e7` |
| Mean clay | `5ad875311461a1375d194172e98cb7b79cea32975215d1cb7c8064bf438b59e5` |
| Mean bulk density | `252e92acfda48bd58ea99cb8d61f5409d8e770125ef7982c95e8c71ef1d1d36f` |
| Mean organic carbon | `45b176e10993d94ca4e1420af2f3ec0cce528ff970fa04fd03053c03b2b7241f` |

## Surface fractions and treatment

The preparation projects native pixel corners into working-grid coordinates, clips each footprint to intersecting valid cells, and sums the overlap area by class. There are no buffers around road centrelines and no building overlay. WorldCover built-up already includes roads and buildings. An independent boundary integral reproduced every class fraction within 6.58 × 10⁻¹². The largest valid-cell fraction sum error was 2.22 × 10⁻¹⁶.

| Fraction band | Domain area | Treatment of current rainfall |
|---|---:|---|
| Built-up (WorldCover 50) | 23.6405% | Sealed-surface assumption. Rain enters surface storage. Actual within-pixel sealing and drainage connectivity are unknown. |
| Separately delineated paved road | 0% delineated | Same sealed treatment. Width and footprint evidence was insufficient to separate any paved area from the source classes. |
| Vegetated (10, 20, 30, 40, 100) | 75.5617% | Apply the selected pervious capacity to current rain. |
| Bare or sparse (60) | 0.2520% | Same capacity where supported. Crusting, bedrock and compaction are unresolved. |
| Permanent open water (80) | 0.3377% | Direct precipitation stays in surface storage. Lake stage and bed seepage are unknown. |
| Other (70, 90, 95) | 0.2081% | Zero infiltration credit under the adopted assumption. This preserves ambiguous wetland behaviour. |
| Missing source coverage | 0% | Store uncovered area separately. Its rainfall receives zero infiltration credit. |

## Soil and equations

On the supported area, predicted means span 49.2–57.2% sand, 19.4–25.7% silt, 22.1–26.9% clay, 1.29–1.39 g/cm³ bulk density and 19.2–54.6 g/kg organic carbon. Texture in g/kg is divided by 10 for percent, bulk density in cg/cm³ by 100 for g/cm³, and carbon in dg/kg by 10 for g/kg. The soil attribute raster preserves missing values. The support raster distinguishes missing soil from a physical zero.

Cosby et al., Table 5, predict the mean log₁₀ saturated conductivity in inches/hour from sand mass percent. The model uses the back-transformed estimate as a **constant provisional cap** for each pervious subarea. Mean sand gives 18.78–24.89 mm/h across supported cells. The lower and upper sand quantiles give 3.87–5.65 and 48.95–58.17 mm/h. These ranges capture the sand-input sensitivity. Soil structure, urban compaction and transfer of the published regression to Bellandur add uncertainty. Local conductivity and event infiltration remain unmeasured. [Cosby et al. (1984), Tables 3 and 5](https://denning.atmos.colostate.edu/readings/Land/Water_Resour._Res._1984_Cosby.pdf)

For current rainfall depth `R` in metres, timestep `dt` in seconds, pervious area fraction `f`, and supported sand mass percent `S`, the spatial accounting is

```text
K [mm/h] = 25.4 × 10^(−0.884 + 0.0153 × S)
infiltration [m over whole cell] = f × min(R, K × dt / 3,600,000)
surface input [m] = R − infiltration
coefficient loss [m] = 0
volume [m³] = cell-average depth [m] × 900 m²
```

All active fractions receive the same cell rainfall. The pervious cap applies before weighting by area, so a mixed cell cannot use spare soil capacity to infiltrate rain falling on its sealed or open-water part. In the existing budget schema, `runoff_input_m3` is pre-infiltration input and equals gross rainfall in spatial mode. `surface_water_input_m3` is the excess passed to routing. The closed-boundary runs start dry.

For pervious land without soil support, `zero-credit` retains its rain at the surface. The alternative `rainfall-limit` infiltrates all current rain on that subarea. These physical limits bound the effect of missing soil without assigning it a conductivity. Local initial moisture, wetting-front suction, soil storage, groundwater and ponded-water infiltration are unresolved. The model therefore uses a per-step rain limit and carries only surface storage between steps.

## Reproduction

Run from the repository root. Acquisition verifies a previously archived source and preparation publishes a new UUID directory. Omit `--surface-parameters` to reproduce the uniform fixture. For a spatial run, the CLI validates the parameter checksums, units, band order, mask, affine and source DEM before simulation.

```powershell
python -B scripts/data/acquire_surface_sources.py
$parameters = python -B scripts/data/prepare_surface_parameters.py
python -B scripts/data/run_surface_routing.py --surface-parameters $parameters
python -B scripts/data/run_surface_routing.py --surface-parameters $parameters --temporal-manifest data/rainfall/temporal/068d3d77a49c5602/manifest.json --event bellandur_2022-09-01
```

Use `--soil-scenario low_capacity`, `mean_texture` or `high_capacity` to select the sand band. Use `--missing-soil rainfall-limit` for the alternate bound. The configuration, raw files, fraction raster, runoff fractions, infiltration rates, soil support, preparation code and parameter manifest have individual SHA-256 records. Each simulation records its active scenario and missing-soil policy. [Configuration](../config/spatial_runoff.json)

## Regression evidence

| Measure | Synthetic 40 mm | Historical, zero credit | Historical, rainfall limit |
|---|---:|---:|---:|
| Five-minute steps | 12 | 228 | 228 |
| Rainfall and pre-infiltration input, m³ | 320,904.000 | 34,897.797 | 34,897.797 |
| Infiltration, m³ | 56,153.358 | 16,582.467 | 26,318.579 |
| Coefficient loss / boundary outflow, m³ | 0 / 0 | 0 / 0 | 0 / 0 |
| Surface input and final storage, m³ | 264,750.642 | 18,315.330 | 8,579.218 |
| Peak saved depth, m | 1.678244 | 0.572984 | 0.419533 |
| Domain peak time | 00:55 UTC, step 12 | Relative 64,500 s, step 215 | Relative 64,500 s, step 215 |

Task 3.3 produced peaks of 1.628103 and 0.253389 m and final storage of 238,003.800 and 13,376.911 m³ for the synthetic and historical cases. The spatial formulation removes the blanket 25% loss and concentrates infiltration on the supported pervious fraction. Synthetic storage rises by 26,746.842 m³ and historical storage by 4,938.419 m³ under zero credit. Both spatial primary runs peak at row 26, column 36, which has zero mapped pervious area. The D8 checksum matches each Task 3.3 baseline. The historical final 12 dry frames have a maximum consecutive study-area depth change of 0.011 mm.

Under zero credit, applying the low and high texture bands to the same rainfall gives synthetic infiltration of 12,042 and 113,816 m³ and historical infiltration of 16,020 and 16,582 m³. The historical mean and high bands admit the same total because the available rain is limiting. Unknown soil on mapped pervious land accounts for a further 9,736 m³ spread between the two historical missing-soil bounds.

The independent verifier reads the source rainfall bands in order, integrates the water budget at each step, checks all masks and finite depths, and reduces saved frames to the cellwise maxima. Across all three executions its largest gross-balance discrepancy was 7.43 × 10⁻¹⁰ m³ against a 10⁻⁶ m³ tolerance. [Synthetic manifest](../data/runs/d9dc683e-1ea4-4aec-b0da-b026f17a841f/manifest.json) · [Historical manifest](../data/runs/f4d220d7-dee2-4245-b568-734c45cbea9a/manifest.json) · [Historical sensitivity manifest](../data/runs/2b37b8cb-81f1-4800-984a-73c5097f5dcb/manifest.json)

```powershell
python -B scripts/data/verify_surface_parameters.py --synthetic-run data/runs/d9dc683e-1ea4-4aec-b0da-b026f17a841f --historical-run data/runs/f4d220d7-dee2-4245-b568-734c45cbea9a
```
