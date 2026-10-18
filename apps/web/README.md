# Web frontend

The current frontend is a dependency-free static application. Its source
assets live in `static/` and are served by the API during the migration. This
boundary is intentionally independent from the backend Python modules so a
future build step or separate static host can be introduced without moving
user-facing assets again.

For Vercel, set the project root to `apps/web`, output directory to `static`,
and replace `api.example.com` in `vercel.json` with the real backend hostname.
The rewrite keeps browser requests same-origin while forwarding `/api/*` to
FastAPI, so session cookies do not need to be exposed to JavaScript.
