# Architecture

Auto-QC-2D is organized as a monorepo:

- `apps/` contains deployable application entrypoints.
- `packages/` contains shared Python packages and stable runtime boundaries.
- `config/` contains versioned rules and guidelines.
- `tests/` contains automated tests and small fixtures.
- `artifacts/` contains generated output and runtime mounts; large data and
  models are intentionally outside the source tree.
- `archive/legacy/` contains retired implementations that are not deployed.

The current API implementation is still in `web_qc/` behind
`apps.api.main:app`. Future refactors should move modules behind package
interfaces without changing the public entrypoint.
