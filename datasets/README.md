# Datasets

Production images, model weights, caches, and large evaluation sets do not
belong in the application image or normal source checkout. Store them in
versioned artifact/object storage and keep only manifests or small fixtures in
this repository.

The checked-in evaluation fixtures are under `tests/fixtures/evaluation/`.
