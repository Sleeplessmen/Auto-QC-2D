from pathlib import Path

from auto_qc_2d.paths import PROJECT_ROOT, runtime_paths


def test_project_root_is_repository_root():
    assert (PROJECT_ROOT / "README.md").is_file()


def test_runtime_paths_honor_environment(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    review_dir = tmp_path / "review"
    artifact_dir = tmp_path / "artifacts"
    monkeypatch.setenv("QC_DATA_DIR", str(data_dir))
    monkeypatch.setenv("QC_REVIEW_OUTPUT_DIR", str(review_dir))
    monkeypatch.setenv("QC_ARTIFACT_DIR", str(artifact_dir))

    paths = runtime_paths()

    assert paths.data_dir == data_dir
    assert paths.review_output_dir == review_dir
    assert paths.upload_dir == data_dir / "uploads"
    assert paths.guideline_dir == data_dir / "guidelines"
    assert paths.artifact_dir == artifact_dir
    assert all(path.is_dir() for path in (data_dir, review_dir, artifact_dir))
