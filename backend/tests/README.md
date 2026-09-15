# Backend unit tests

The directory layout mirrors `app/`:

- `tests/api/...` tests API models, route helpers, and route behavior with mocked managers.
- `tests/core/...` tests configuration, archive handling, NVFlare helpers, FHIR utilities, and database-manager behavior with fake connections/cursors.

Install the development dependencies and run the deterministic suite from the backend root:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

When your shell is already inside `backend/tests`, use:

```bash
python -m pip install -r ../requirements-dev.txt
python -m pytest
```

The normal unit suite intentionally avoids live AWS, EC2, MySQL, Docker, and NVFlare-server calls. Existing simulator/integration tests under `app/core/job_runner/nvflare_jobs/tests` remain separate and are not included by `pytest.ini`.
