# Public rainfall-source integration

This document covers the additive rainfall ingestion infrastructure for the
locked Bellandur study area. It does not change P1–P5 model behavior and does
not start P6.

## Sources

### Open-Meteo

Open-Meteo provides numerical weather-model precipitation forecasts through a
public JSON API. FloodOps requests one deterministic point at the centroid of
the canonical `config/study_area.json` bbox. The returned model-grid
coordinate, hourly timestamps, units, and forecast metadata are preserved. The
adapter normalizes hourly precipitation into the existing provider-neutral
schema:

```text
timestamp, latitude, longitude, rainfall_mm, source
```

This is forecast/model data, not observed radar, DWR, or street-level rainfall.
The request does not create a finer grid than Open-Meteo's returned model cell.

### RainViewer

RainViewer provides a public radar observation timeline and web-map tile
references. FloodOps stores the raw timeline and creates recent past-frame
references centered on Bellandur. It does not download tiles by default and
does not convert rendered radar imagery into `rainfall_mm` or mm/h values.

The public future radar nowcast service was discontinued on 2026-01-01, so the
adapter ignores future-nowcast frames and records `future_nowcast_available:
false`. An empty or unavailable past-frame list is represented explicitly and
does not become fabricated rainfall.

User-facing radar visualization must display: **Weather data by RainViewer**
with a link to <https://www.rainviewer.com/>.

## Authentication and configuration

Neither source requires a login or API key for this integration. Settings are
loaded through the existing backend `pydantic-settings` convention. Copy
`backend/.env.example` to `backend/.env` only when local overrides are needed;
do not overwrite an existing `.env`.

```text
OPEN_METEO_ENABLED=true
OPEN_METEO_BASE_URL=https://api.open-meteo.com
RAINVIEWER_ENABLED=true
RAINVIEWER_BASE_URL=https://api.rainviewer.com/public/weather-maps.json
RAINFALL_HTTP_TIMEOUT_SECONDS=20
RAINFALL_HTTP_RETRIES=2
```

The Bellandur bbox is loaded only from `config/study_area.json`; it is not
duplicated in the adapters or CLI.

## Running the fetchers

From the repository root:

```powershell
python scripts/fetch_rainfall_sources.py --source open-meteo --forecast-days 3
python scripts/fetch_rainfall_sources.py --source rainviewer
python scripts/fetch_rainfall_sources.py --source all --forecast-days 3
```

The clients use timeouts, retries for transient network/5xx/429 failures,
clear validation errors, and no secret headers. Tests use mocked HTTP
responses and never require live services.

## Storage and provenance

- Open-Meteo raw JSON: `data/rainfall/raw/open_meteo/`
- RainViewer raw JSON: `data/rainfall/raw/rainviewer/`
- Open-Meteo normalized CSV: `data/rainfall/processed/`
- Source metadata and RainViewer frame index: `data/rainfall/metadata/`
- Source registry: `data/rainfall/metadata/source_catalog.json`

Each fetch records retrieval time, endpoint, request parameters, study-area
bbox, CRS, source type, units, response/grid metadata, and raw/processed file
paths. RainViewer metadata records frame time, path, Bellandur tile reference,
coverage reference, attribution, and the fact that no quantitative rainfall
value was generated.

The existing IMD/NCMRWF and synthetic rainfall pipelines remain unchanged.
Open-Meteo can be used as a provider-neutral forecast rainfall input after its
metadata is reviewed. RainViewer remains a radar observation/visualization
layer unless a separately validated quantitative conversion is introduced.

## References

- [Open-Meteo Forecast API](https://open-meteo.com/en/docs)
- [RainViewer Weather Maps API](https://www.rainviewer.com/api/weather-maps-api.html)
- [RainViewer API transition summary](https://www.rainviewer.com/api/transition-faq.html)
- [RainViewer attribution/API terms](https://www.rainviewer.com/api.html)
