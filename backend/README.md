# FloodOps backend

This is the initial FastAPI foundation for FloodOps. Run it from this
directory with:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

P9 endpoints under `/api` are read-only integration endpoints: they serve
existing validated P6--P8 outputs when those products are available and return
`503 product_unavailable` when they are not. They never run rainfall,
hydraulic, inundation, or routing calculations. Interactive documentation is
available at `/docs`.

Key P9 endpoints are `/health`, `/api/status`, `/api/study-area`,
`/api/flood/*`, `/api/roads/impact`, `POST /api/routes`, `/api/runs`, and
`/api/rainfall/sources`. `POST /api/routes` delegates to the locked P8
routing implementation and accepts only exact timestamps present in its
validated P7 inputs.

## Development-only mock authentication

Mock authentication is isolated in `app/auth.py` and is not suitable for
production. The `POST /storms/run` demonstration endpoint accepts the
`X-Mock-Role` header with `admin` or `operator`; `viewer` is rejected. There
are no real users, passwords, tokens, sessions, or external identity providers.
