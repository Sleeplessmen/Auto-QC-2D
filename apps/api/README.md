# API application

`apps.api.main:app` is the stable production import path for the FastAPI
application. The current Web QC implementation remains under `web_qc/` while the service
boundaries are migrated incrementally. Static frontend assets are under
`apps/web/static/`.

Run locally from the repository root:

```powershell
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```
