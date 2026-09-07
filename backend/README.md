# FloodOps backend

This is the initial FastAPI foundation for FloodOps. Run it from this
directory with:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API currently returns clearly labelled sample payloads. It does not run
rainfall nowcasting, GIS processing, hydraulic modelling, SWMM, flood-risk
calculation, or real routing.

## Development-only mock authentication

Mock authentication is isolated in `app/auth.py` and is not suitable for
production. The `POST /storms/run` demonstration endpoint accepts the
`X-Mock-Role` header with `admin` or `operator`; `viewer` is rejected. There
are no real users, passwords, tokens, sessions, or external identity providers.
