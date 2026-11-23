# Temporal rainfall products

Run the following command from the repository root with the data-processing Python environment and both Task 2.3 mapped snapshots present.

```powershell
python -B scripts/data/process_temporal_rainfall.py
```

Open `data/rainfall/temporal/latest.json` and follow its relative manifest path. Verify the manifest digest against the pointer. The bundle manifest lists event manifests, input hashes (including the immutable spatial snapshots), output hashes, software versions and the processing version. The CLI publishes a complete bundle atomically. An identical build reuses its snapshot. The historical forecast catalogue uses the fixed archive reference time in `config/rainfall_events.json`.

## Choosing a source interval

The MOSDAC filenames provide timestamp labels interpreted as UTC. Their nominal cadence is 1,800 seconds. The local files do not establish a timestamp anchor, observation interval bounds, or rate averaging period. The Task 2.3 mapped rate retains its native mm/h interpretation. A separate mapped half-hour depth already incorporates the assumption that this rate represents the nominal half hour.

The allocator reads that derived depth once and uses the assumption `mosdac_uniform_intensity_nominal_30min_v1`. Each of six steps receives the derived depth divided by six, in mm. An independent check uses the mapped rate multiplied by 300/3,600 hours. A dry source pixel gives six valid zero depths. Uncovered areas and DEM voids retain nodata. The source and step volumes use the actual covered area in m² multiplied by depth in mm and divided by 1,000.

The primary window begins with the 31 August 2022 22:15 UTC label and ends with the 1 September 16:45 UTC label. The alternative starts with the 30 August 22:15 label and ends with the 31 August 16:45 label. These are inclusive source labels. Each complete event gets its own half-open relative clock from 0 to 68,400 seconds. Calendar bounds for its physical intervals are unknown. The 5 September high-intensity sequence ends next to a long gap and is excluded from the configured replays.

## Reading the files

| Path inside a snapshot | Contents |
|---|---|
| `mosdac_insat3dr/inventory.json` | Independent nominal label inventory, every missing label, surrounding observations and elapsed time, continuous nominal windows, and irregular separations. |
| `mosdac_insat3dr/conservation.json` | Native pixel rates, derived depths, equal-step depths and numerical residuals for the archive. Grid volumes and residuals use each frame's spatial coverage. |
| `mosdac_insat3dr/<event>/allocated_depth_mm.tif` | Float64 multiband GeoTIFF, one half-open relative interval per band. Each band stores allocated mm during 300 seconds. NaN is nodata. |
| `mosdac_insat3dr/<event>/steps.json` | One-based raster band, zero-based source interval index, relative start and end in seconds, original filename label, interpreted UTC label, mapped band, coverage reference and assumption identifier. |
| `mosdac_insat3dr/<event>/manifest.json` | Source rows and columns, original native files, references to mapped rate/depth and terrain, completeness, interval conventions, conservation results and checksums. |
| `<other-source>/native.json` | IMD daily accumulation, Electronic City daily statement, archived hourly Open-Meteo forecasts, or IMERG availability. Each entry preserves its own source clock. |

Paths beginning with `data/` are relative to the repository root. Paths between manifests and indices within a snapshot are relative to the enclosing file. To read a computational step, read its one-based band, follow the corresponding coverage reference, and use the event manifest's terrain mask. The coverage bands contain source-covered area, covered fraction and source validity. The source interval index joins the step to its native pixel measurements. The original half-hour field and rate remain accessible through the mapped raster paths and mapped band number.

## P9 time-series coverage

The `/api/rainfall/timeseries` endpoint selects observation labels inclusively. A successful response includes `coverage_status`. A dry observation returns its measured zero and `available`. A request spanning a known gap returns the available records, `partial`, and the missing labels. A request containing only records marked missing has status `missing_data`. Coverage also reports requests extending beyond the source label range.

An empty query wholly within a gap returns HTTP 404 with `detail.error = coverage_gap`. A request wholly outside the archive returns `outside_coverage` for an explicitly selected available source. A sub-cadence query between consecutive observations returns `no_observation_labels`. The gap's surrounding observation labels describe archive availability. They do not establish physical accumulation boundaries.
