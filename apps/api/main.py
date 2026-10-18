"""Run the Web QC FastAPI application from the repository root.

The legacy ``web_qc/server.py`` module is kept as the implementation boundary
for now; this entrypoint gives deployment tooling a stable import path.
"""

from web_qc.server import app

__all__ = ["app"]
