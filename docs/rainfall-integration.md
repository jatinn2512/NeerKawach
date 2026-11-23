# P9 rainfall integration

The source registry is `config/rainfall_sources.json`. P9 reads local files. The read-only paths below use the canonical Bellandur boundary from `config/study_area.json`.

## Native rainfall records

`backend/app/rainfall/contracts.py` retains the P9 fields `timestamp`, `rainfall_mm`, coordinates, source, product and observation/forecast flags. Use `measurement_type`, `original_value`, and `original_unit` for scientific interpretation. Derived depth has a separate value, unit and derivation. Unknown temporal fields are JSON null. An invalid or nodata measurement has a null amount and a quality flag. A measured zero retains its numeric value.

Pixel centres are longitude/latitude pairs. Footprints and raster bounds are west, south, east, north in the source CRS. The six transform coefficients use GDAL order. Station coordinates are points. Top-level MOSDAC latitude/longitude continue to represent the clipped subset centroid for existing clients. Native geometry is under `geometry`.

| Dataset | Measurement and location | Clock and completeness |
|---|---|---|
| MOSDAC INSAT-3DR IMC | Satellite rate in mm/h on native approximately 4 km pixels. The separate derived depth uses rate × 0.5 h. | UTC interpretation of a filename label. Nominal cadence 1,800 seconds. The rate averaging period and interval boundaries are unknown. The tracked CSV and frame manifest identify 682 pixel records, 341 timestamps and 91 absent labels. |
| IMD/NCMRWF merged daily | Native daily total in mm. The binary reader takes dimensions, spacing, variable, and nodata from the GrADS control file and byte order from acquisition metadata. The processed CSV alone carries rounded values. | Product date is assigned. The existing UTC midnight label is retained for compatibility. Actual accumulation boundaries are unknown. |
| IMD Electronic City ARG | Daily station total in mm at station 303127776, outside Bellandur. Explicit historical requests make this statement available for regional comparisons. | Provider calendar dates are preserved. UTC time, day cutoff and datum are unknown. Missing labels are unlisted dates between the first and last entries. |
| Open-Meteo | Hourly forecast precipitation in mm at the returned model coordinate. The footprint is unknown. | Valid time, retrieval time, and model issue time are separate. If no sidecar exists, the capture filename supplies retrieval time at second precision. The local archive has three equivalent captures of 72 hours. |
| IMERG | The local archive contains no NASA observation file. | Explicit time-series requests return HTTP 503. The IMD merged product has a separate source ID. |
| RainViewer and DWR | RainViewer supplies past-frame imagery references. DWR remains reserved. | Neither supplies quantitative records here. RainViewer imagery displays require attribution to Weather data by RainViewer. |

## Reading local records

`GET /api/rainfall/sources` returns the descriptive catalog. `GET /api/rainfall/metadata` returns the registry. `GET /api/rainfall/status` and `GET /api/rainfall/current` report source availability. An archived forecast can be readable while `current_usable` is false. Expired or absent forecasts give a null current selection when there is no other eligible source. The existing explicit DWR status fallback remains visible in its response.

`GET /api/rainfall/timeseries?source_id=arg_aws` returns regional statement records with null `timestamp_utc`. Use ISO calendar dates for both query bounds on this series. UTC-labelled series accept timezone-qualified bounds. `missing_labels` uses the same clock as its records.

`GET /api/rainfall/timeseries?source_id=open_meteo_precipitation_forecast` reads archived forecasts. The `captures` list preserves retrievals, file names, series fingerprints and duplicate references. Records sharing a valid time and model coordinate use the most recently retrieved version. Querying `mode=current` or `mode=forecast` requires a capture already retrieved with valid forecast times remaining. An expired archive returns HTTP 503 for these modes. The current endpoint and the archive readers perform no network requests. `GET /api/nowcast/status` remains the separate quantitative nowcast capability endpoint.

Run the existing inspection CLI from the repository root. It writes JSON to standard output by default. The optional `--output` takes a new file path.

```powershell
python scripts/ingest_rainfall.py --source mosdac_insat3dr
python scripts/ingest_rainfall.py --source imd_ncmrwf_gpm_merged_daily
python scripts/ingest_rainfall.py --source arg_aws
python scripts/ingest_rainfall.py --source open_meteo_precipitation_forecast
```

Run backend regression tests with `python -m pytest` from `backend/`. Run `python -m pytest scripts/data/test_rainfall_archive.py` from the repository root for native-file verification with the existing raster dependencies. Missing local deliveries skip independently. Task 2.2 ends at native rainfall records. The saved P3 run still uses its synthetic fixture.
