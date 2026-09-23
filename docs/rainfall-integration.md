# P9 rainfall integration

The canonical study area remains `config/study_area.json` (Bellandur,
Bengaluru, EPSG:4326). Provider policy and quantitative priority are in
`config/rainfall_sources.json`; the configured historical analysis window is
in `config/rainfall_events.json`.

## Source status

- IMD DWR/QPE is reserved and unavailable because authorized historical access
  was not verified. The DWR adapter raises an explicit unavailable error.
- MOSDAC INSAT-3DR `3RIMG_L2B_IMC` is available for the historical window:
  341 valid GeoTIFFs covering 2022-08-30 through 2022-09-07. The normalized
  product is a 30-minute Bellandur pixel-footprint subset at approximately
  4 km native resolution. It is satellite-derived QPE, not DWR.
- IMD AWS/ARG and IMD DSP are configured as point/file adapters. Station data
  retains station metadata and is not expanded to a grid.
- Existing IMD/NCMRWF merged daily rainfall remains the P1 baseline at its
  native daily grid resolution.
- NASA GPM IMERG is configured as a satellite fallback; Earthdata access is
  required for downloads and no file is fabricated.
- Open-Meteo is available through the existing public client as numerical
  weather-model precipitation, not radar or DWR.
- RainViewer is available through the existing client as recent/past radar
  observation metadata and imagery references. It is not quantitative
  rainfall, and it is not a future 0–3 hour nowcast provider.

## Normalized contract and fallback

`backend/app/rainfall/contracts.py` validates UTC timestamps, finite
coordinates, non-negative millimetres, duplicate keys, units, and optional
study-area bounds. The internal record preserves `source`, `product`, quality
flags, observed/forecast/fallback state, and station IDs where applicable.

`backend/app/rainfall/resolver.py` selects one configured quantitative source
according to the registry priority and returns `source_used`,
`fallback_reason`, and availability metadata. It does not blend sources and
does not make live requests from status endpoints. Historical resolution now
selects MOSDAC when its normalized product is present; current/forecast
resolution excludes MOSDAC and uses appropriate configured sources.

## API and operation

Existing `/api/rainfall/sources` remains a catalog endpoint. Additive endpoints
are:

- `GET /api/rainfall/status`
- `GET /api/rainfall/metadata?source_id=...`
- `GET /api/rainfall/timeseries?source_id=...` for stored normalized CSV
- `GET /api/rainfall/current` for current availability, without a fabricated
  value
- `GET /api/nowcast/status`

The existing live fetch script remains `scripts/fetch_rainfall_sources.py` for
Open-Meteo and RainViewer. `scripts/ingest_rainfall.py` validates a local
normalized CSV and can emit a provenance-preserving JSON representation. The
real MOSDAC set is ingested with `scripts/data/ingest_mosdac_rainfall.py`; its
CSV contains the legacy P3-compatible columns plus source-product, resolution,
units, quality, and observed/forecast/fallback fields.

RainViewer attribution (`Weather data by RainViewer`, linked to
`https://www.rainviewer.com/`) is required in any user-facing visualization.

## Limitations

IMD DWR, AWS/ARG, DSP, and IMERG remain unavailable in this workspace. The
MOSDAC CSV is compatible with the existing P3 normalized-CSV input interface;
the validated P5 path remains explicitly synthetic-fixture-only and is not
silently replaced. This P9 layer does not rewrite P1–P8 model logic or
outputs, does not create DWR data, and does not infer rainfall from radar tile
colors.
