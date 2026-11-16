# For developers

## Layout

```
src/ceh_biomonitoring/
  cli.py              the cehbio command
  settings.py         settings layers: defaults < machine profile < plug-in < settings.yml < command line
  runner.py           runs one chunk, combines chunks, writes provenance
  chunks.py           splits file lists into chunk manifests
  slurm.py            writes and submits Slurm array jobs
  devices.py          recorder profiles and file-name timestamps
  objectstore.py      optional S3 access
  upload.py           cehbio upload (the UKCEH upload service)
  pipelines/          one module per pipeline (base.py explains the interface)
  profiles/           machine settings (local, JASMIN)
  device_profiles/    recorder profiles
docs/                 user guides
tests/                no models or keys needed
```

## Adding a pipeline

1. Write one class in `src/ceh_biomonitoring/pipelines/`, subclassing `Pipeline` from `base.py`. It says which files it wants (`extensions`, `media`), its default settings, and how to process a folder of them (`process`), returning a `ChunkResult`.
2. Check its packages with `require(...)` inside methods, not at the top of the module, so `cehbio` stays fast and works without it installed.
3. Register it in `pipelines/__init__.py`, and add an install extra with its packages in `pyproject.toml`.
4. Add a guide in `docs/` and a row in the README.

The engine does everything else: finding files, chunks, Slurm, resuming, combining, the file-status list, QA and provenance.

## Plug-ins

Other packages can add parts without changing this one, through entry points:

| Entry point | Adds |
|---|---|
| `ceh_biomonitoring.pipelines` | pipelines |
| `ceh_biomonitoring.devices` | recorder profiles (a package folder of `.yml` files) |
| `ceh_biomonitoring.profiles` | machine settings, e.g. a cluster's paths and Slurm account |
| `ceh_biomonitoring.commands` | extra `cehbio` commands |
| `ceh_biomonitoring.data` | data tables, e.g. a list of project buckets |

## Tests

```bash
pip install -e ".[dev]"
pytest
```

They need no key and no models.

## Line endings

`.gitattributes` keeps every text file in LF, so shell scripts work on JASMIN even when edited on Windows.
