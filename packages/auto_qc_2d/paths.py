"""Centralized filesystem boundaries used by local and container deployments."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RuntimePaths:
    """Persistent and generated data locations for one application instance."""

    data_dir: Path
    review_output_dir: Path
    upload_dir: Path
    guideline_dir: Path
    artifact_dir: Path

    def ensure(self) -> "RuntimePaths":
        for path in (
            self.data_dir,
            self.review_output_dir,
            self.upload_dir,
            self.guideline_dir,
            self.artifact_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return self


def runtime_paths() -> RuntimePaths:
    """Resolve runtime directories without depending on the current directory."""

    data_dir = Path(os.getenv("QC_DATA_DIR", PROJECT_ROOT / "web_qc" / "data")).expanduser()
    review_output_dir = Path(
        os.getenv("QC_REVIEW_OUTPUT_DIR", PROJECT_ROOT / "artifacts" / "review")
    ).expanduser()
    artifact_dir = Path(os.getenv("QC_ARTIFACT_DIR", PROJECT_ROOT / "artifacts")).expanduser()
    return RuntimePaths(
        data_dir=data_dir,
        review_output_dir=review_output_dir,
        upload_dir=data_dir / "uploads",
        guideline_dir=data_dir / "guidelines",
        artifact_dir=artifact_dir,
    ).ensure()
