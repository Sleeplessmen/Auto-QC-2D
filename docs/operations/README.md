# Operations

Production runtime data must be mounted outside the image:

- `QC_DATA_DIR`: SQLite database, encrypted CVAT tokens, uploads, and
  guidelines.
- `QC_REVIEW_OUTPUT_DIR`: review result files.
- `QC_ARTIFACT_DIR`: generated reports and benchmark output.

Back up `QC_DATA_DIR` and `QC_REVIEW_OUTPUT_DIR` together. The
`data/secret.key` file is required to decrypt stored CVAT tokens and to keep
existing sessions valid.
