# Development

Install the root project in editable mode after installing the ML dependencies
listed in `requirements.txt`:

```powershell
python -m pip install -e .
python -m pytest -q
```

Use the root as the working directory for legacy command-line tools. New code
should import from `auto_qc_2d` and should not depend on the current directory.
