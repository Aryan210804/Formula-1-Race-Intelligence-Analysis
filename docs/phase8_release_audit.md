# Phase 8 — Senior QA Audit and Project Release

**Audit date:** 2026-10-16
**Result:** **Not release-ready.** The available FastF1-only ingestion and
transformation workflow passed the checks run below. The requested Kaggle
inputs are absent, and analytics and Tableau export components are not
implemented, so the requested complete end-to-end workflow cannot be validated
or declared complete.

This report distinguishes executed checks from unimplemented or unavailable
checks. No source data was downloaded, fabricated, changed, or attributed to
the absent Kaggle datasets.

## 1. Implemented components

- Python `src/` package and `pyproject.toml` dependency, CLI, and pytest
  configuration.
- FastF1 schedule/session ingestion, bounded retry support, raw JSON
  persistence, and the `f1-ingest` CLI.
- FastF1 raw JSON normalization, validation/reject reporting, and SQLite
  relational storage through `f1-transform`.
- Data dictionary, data-quality guidance, source inventory, and Tableau
  workbook build specification.
- Offline unit tests for settings, ingestion behavior (mocked external calls),
  transformation/storage behavior, and package smoke coverage.

**Not implemented:** analytical metric functions/queries, production Tableau
CSV exports, export manifest, a Tableau workbook, and a Tableau Story. The
`analytics` and `exports` packages currently contain only package
initializers; they do not provide those deliverables.

## 2. Verified dataset inventory and row counts

Only two raw F1 JSON source files were present:

| Source | File | Format and size | Source records | Columns |
|---|---|---:|---:|---:|
| FastF1 2024 schedule | `data/raw/fastf1/season=2024/schedule.json` | JSON, 25,704 bytes | 24 | 23 |
| FastF1 2024 Bahrain qualifying | `data/raw/fastf1/season=2024/round=01-bahrain-grand-prix/session=Q/qualifying_results.json` | JSON, 12,275 bytes | 20 | 22 |

The source counts were read from the actual JSON `records` arrays. The source
inventory contains further verified field, null/blank, duplicate, and key
details in [dataset_inventory.md](./dataset_inventory.md).

The requested manual Kaggle downloads were **not found**:

- `anthonytherrien/predicting-f1-pit-stops-vault`
- `navenkumar1998/formula-1-dataset-with-weather-and-tyre-features`
- `rohanrao/formula-1-world-championship-1950-2020`

The actual normalized SQLite row counts after the audited transform were:

| Table | Rows |
|---|---:|
| circuits | 24 |
| events | 24 |
| drivers | 20 |
| constructors | 10 |
| sessions | 120 |
| race_results | 0 |
| qualifying_results | 20 |
| session_results | 0 |
| laps | 0 |
| pit_stops | 0 |
| weather | 0 |
| telemetry | 0 |
| rejected_records | 0 |
| quality_issues | 0 |

The transformation CLI reported 218 normalized rows in total. Its JSON quality
report's source record counts and every database table row count matched the
actual raw JSON record counts and SQLite counts queried during the audit.
`PRAGMA foreign_key_check` returned no violations. The report contained zero
rejected records, zero error findings, and zero warning findings for these two
inputs only. This is not a full-history or Kaggle-data quality claim.

Before and after the documented transformation command, SHA-256 hashes of
both raw FastF1 input files were compared; neither changed.

## 3. Test results and failures

### Passing checks

In a newly created temporary virtual environment, the following documented
setup/pipeline equivalents completed:

```text
python -m venv <temporary-audit-venv>
<temporary-audit-venv>\Scripts\python.exe -m pip install -e ".[dev]"
<temporary-audit-venv>\Scripts\python.exe -m pytest
<temporary-audit-venv>\Scripts\f1-transform.exe
```

Actual test result:

```text
============================= 24 passed in 3.51s ==============================
```

Actual clean-environment transform result:

```text
Loaded 218 transformed rows into ...\data\processed\f1_intelligence.sqlite3
Rejected 0 records; quality errors=0, warnings=0
Quality report: ...\data\processed\quality\quality_report.json
Quality summary: ...\data\processed\quality\quality_summary.md
```

The global installed environment also ran `python -m pytest` successfully:

```text
============================= 24 passed in 1.28s ==============================
```

Additional executed checks:

- `python -m pip check` → `No broken requirements found.`
- `git diff --check` → exit code 0.
- SQLite row counts matched the quality report; foreign-key check → `[]`.
- Raw-file hash comparison → no changed files.
- Git ignore checks confirmed `.env`, `.venv`, `.cache`, raw FastF1 JSON,
  SQLite database, and generated export paths are ignored.

### Failed/blocked checks

- An initial `f1-transform` invocation from the pre-existing global shell
  failed because the Python `Scripts` directory was not on that shell's
  `PATH`. After editable installation in a fresh virtual environment, the
  command was available and the pipeline passed. In a Windows shell, activate
  the virtual environment as described in the README or invoke its
  `Scripts\f1-transform.exe` directly.
- The editor test-runner's implicit file selection returned “No tests found”;
  invoking the documented `python -m pytest` from the project root discovered
  and passed all 24 tests. No test case failed.
- No tests could validate analytical formulas, real-data join cardinality,
  exported totals, constructors, tyre compounds, race statuses, pit duration,
  or weather relationships: those analytics/exports are not implemented and
  the required data is absent.
- No workbook could be opened or validated because no Tableau executable was
  detected and no Tableau workbook or export files exist.
- No network-based ingestion was attempted during this audit. The real-data
  pipeline run started from the existing raw snapshots and ran
  `f1-transform`; it did not fetch new FastF1 data.

## 4. Join, metric, and missing-value audit

- Current SQLite constraints and foreign-key checks passed for the available
  normalized data.
- No analytic fact-to-fact joins were executed. Consequently, row
  multiplication prevention in Tableau/analytics has not been empirically
  validated; use the documented separate fact grains and relationships in
  [tableau_workbook_guide.md](./tableau_workbook_guide.md).
- Points, wins, podiums, DNF counts/rates, race completion rates, Red Bull
  Racing/Mercedes season comparisons, and race standings were **not**
  calculated or validated. There are zero race-result rows.
- Tyre, lap pace, pit duration, weather, and telemetry metrics were **not**
  calculated or validated. Their corresponding fact tables have zero rows.
  The current pit table is explicitly an observation table for pit-in/out
  timestamps; it does not by itself establish pit-stop duration.
- Nationality analysis was not possible because inspected FastF1 driver
  country codes are blank. Schedule-level events are not a substitute for
  historical race counts from the missing championship source.
- Missing values remain nullable in the storage design; the audit found no
  evidence of missing values being converted to zero in the available
  transformation run. This finding is scoped to those inputs and code paths.

## 5. Reproducible execution instructions

From the repository root in GitHub Codespaces:

```bash
python --version
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest
f1-transform
```

The install, test, and transform steps were exercised in a fresh temporary
Windows virtual environment using equivalent Windows executable paths and
passed. Python 3.12.10 was used; the project declares Python 3.10 or newer.
The raw-data transform does not require network access.

For Windows PowerShell, activate with:

```powershell
.\.venv\Scripts\Activate.ps1
```

Then use `python -m pytest` and `f1-transform`. If not activating, use
`.venv\Scripts\python.exe -m pytest` and
`.venv\Scripts\f1-transform.exe`.

This is only a reproducible setup and the currently implemented ingestion to
SQLite transformation path. It is **not** a reproducible complete analytics
and Tableau export pipeline yet.

## 6. Tableau import and Story instructions

No exports were generated: `data/exports/` contains only `.gitkeep`. The
Tableau instructions therefore remain a design/build guide rather than
verified import steps against actual project CSVs.

Use [tableau_workbook_guide.md](./tableau_workbook_guide.md) for proposed CSV
grains, safe logical relationships, dashboard definitions, Story sequence,
manual Desktop/Public build steps, and workbook QA. Once the analytics/export
phase produces manifest-listed CSVs, connect those files, confirm each
manifest schema and grain, relate facts using stable IDs, validate aggregates
against SQLite, then build the seven dashboards and Story. Do not display
unavailable metrics as zero or claim a workbook exists until it is actually
created and checked.

## 7. Git and release state

- The `.gitignore` checks passed for credentials (`.env`), virtual
  environments, local caches, raw downloads, generated SQLite files, and
  generated exports.
- `git status --short` is not clean: `README.md` is modified and the project
  directories/files are untracked in this checkout. No files were staged,
  committed, pushed, or deleted as part of this audit.
- No dataset source file was modified or moved.
- No Tableau workbook, CSV export, export manifest, or publication was
  created.

## 8. Remaining release requirements

1. Put the three original Kaggle datasets in `data/raw/kaggle/` without
   changing their contents, then inventory their actual files and schemas.
2. Implement source-specific ingestion/validation and normalization without
   guessing fields or key relationships.
3. Validate the relational model and join cardinalities against the real
   inputs, with tests for preservation and row multiplication.
4. Implement and test the documented analytics, including definitions,
   scoring-era caveats, source status handling, and constructor comparisons.
5. Generate Tableau CSV exports and a manifest from validated analytics;
   reconcile each exported total to database queries.
6. Run the complete test suite and the full raw-to-export workflow from a
   clean environment with the real inputs present.
7. Create/open the Tableau workbook and Story in an available Tableau
   environment; validate filters, denominators, relationships, and data
   refresh before describing the project as released.
8. Review the complete Git diff and decide which project files to stage and
   commit. No release commit or push was made.

**Release decision:** QA passed for the implemented FastF1 snapshot
transformation path only. The full Phase 8 release acceptance criteria remain
unmet; do not declare the project complete.
