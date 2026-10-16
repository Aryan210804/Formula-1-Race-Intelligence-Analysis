# Formula 1 Race Intelligence

A modular Python project for Formula 1 source ingestion, validation,
transformation, SQLite storage, and Tableau-compatible analytics.

## Verified data availability

The project includes local snapshots for the 2024 season schedule and Bahrain
qualifying, all three configured Kaggle sources, and a reproducible historical
SQLite build. The historical championship source covers 1950–2020; the separate
weather/tyre source is analyzed at lap grain and is not assumed to join directly
to historical race results. The files currently present cover 1950–2024 for race
records, 2011–2024 for historical pit stops, and 2021–2023 for weather/tyre
observations. See [the source inventory](reports/dataset_inventory.txt)
and [metric definitions](docs/metric_definitions.md).

## Kaggle dataset downloads

The KaggleHub downloader requests these exact datasets and stages the
downloaded cache contents into the project without deleting or modifying
KaggleHub's cache:

| Kaggle identifier | Project destination |
|---|---|
| `anthonytherrien/predicting-f1-pit-stops-vault` | `data/raw/pit_stops/` |
| `navenkumar1998/formula-1-dataset-with-weather-and-tyre-features` | `data/raw/weather_tyre/` |
| `rohanrao/formula-1-world-championship-1950-2020` | `data/raw/historical_f1/` |

Install in Windows PowerShell from the repository root:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If KaggleHub reports that authentication is needed, create an API token from
[Kaggle API settings](https://www.kaggle.com/settings/api). Do not put it in
source code, a committed file, or a command containing the literal secret.
One supported PowerShell approach is a process-scoped environment variable
entered using a hidden secure prompt and consumed in the same shell:

```powershell
$secureToken = Read-Host "Kaggle API token" -AsSecureString
$tokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try {
    $env:KAGGLE_API_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPointer)
    .\.venv\Scripts\python.exe scripts\download_datasets.py
}
finally {
    Remove-Item Env:\KAGGLE_API_TOKEN -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPointer)
    Remove-Variable secureToken, tokenPointer -ErrorAction SilentlyContinue
}
```

When credentials are already configured, the main command is:

```powershell
.\.venv\Scripts\python.exe scripts\download_datasets.py
```

The script attempts public datasets if it detects no credentials; restricted
or private data can fail. Each dataset is handled independently, and any
failed required dataset yields a nonzero exit status. The script uses the
actual path returned from KaggleHub, copies files recursively while preserving
relative names, checks file size and SHA-256, skips identical files, and
refuses to overwrite a differing destination file. The generated report is
`reports/dataset_inventory.txt`. It inventories CSV, TSV, JSON, Parquet,
Excel, and supported tabular ZIP members without extracting ZIP archives.

Raw downloads in `data/raw/pit_stops/`, `data/raw/weather_tyre/`, and
`data/raw/historical_f1/` are excluded by `.gitignore` because file sizes,
licensing, and repository limits are not verified. This prevents large
downloaded data from being accidentally committed; the datasets can be
reproduced by rerunning the downloader. Inventory reports and source code are
not excluded.

## Project structure

```text
config/settings.yaml               Non-secret paths and runtime settings
data/raw/fastf1/                   FastF1 JSON snapshots (Git-ignored)
data/raw/pit_stops/                Kaggle pit-stop source (Git-ignored)
data/raw/weather_tyre/             Kaggle weather/tyre source (Git-ignored)
data/raw/historical_f1/             Kaggle historical source (Git-ignored)
data/interim/                      Temporary/source-specific derived data
data/processed/                    Rebuildable normalized tables and SQLite DB
data/exports/                      Tableau-compatible exports
reports/dataset_inventory.txt      Generated dataset inventory
scripts/download_datasets.py       KaggleHub download, staging, and inventory
src/f1_intelligence/data/          FastF1 source access and ingestion CLIs
src/f1_intelligence/transformations/
                                   Normalization and quality checks
src/f1_intelligence/storage/       SQLite store interface and implementation
tests/                             Offline unit and integration tests
```

## Dependencies and Codespaces setup

Python 3.10 or newer and pip are required. SQLite is included with Python.
`pyproject.toml` defines the package and its dependencies. `requirements.txt`
is the convenient setup command and installs this project, KaggleHub, Pandas,
pytest, Parquet support, Excel readers, Streamlit, and Plotly. Kaggle
credentials are configured outside the repository; `.env` and credential files
are Git-ignored.

In GitHub Codespaces, run:

```bash
python --version
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest
```

## Implemented pipeline commands

```bash
python scripts/download_datasets.py
f1-ingest list-seasons
f1-ingest list-events --season 2024
f1-ingest ingest-event --season 2024 --event 1 --session Q --dry-run
f1-transform
```

`f1-ingest` retrieves supported FastF1 data and persists raw JSON with
provenance. `f1-transform` rebuilds SQLite tables from available FastF1 JSON
and writes JSON/Markdown data-quality reports. The historical Kaggle pipeline
and dashboard use a separate database, `data/processed/f1_intelligence.db`.

## Local dashboard and historical analytics (Windows PowerShell)

Run these from the repository root:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts\download_datasets.py
python scripts\inspect_datasets.py
python scripts\build_database.py
python scripts\export_tableau_data.py
python -m pytest
python -m streamlit run app.py
```

The downloader uses KaggleHub and may need Kaggle authentication for restricted
sources; follow the secure token instructions above. If local source files are
already staged, the inspect/build/export/dashboard steps run offline. The
database build checks source columns, unique keys and foreign-key values, then
atomically replaces its output only after validation. It does not delete or
rewrite raw sources. The dashboard listens on Streamlit's local URL (normally
`http://localhost:8501`).

Tableau extracts are written under `data/exports/tableau/`, with one
`.data_dictionary.md` per CSV. See
[the Tableau implementation guide](docs/tableau_implementation_guide.md).
The CSVs are extracts, not a generated Tableau workbook.

Troubleshooting:

- **Kaggle authentication error:** configure an API token outside the repo
  using KaggleHub's documented environment or user config, then rerun download.
- **Missing source file or schema:** rerun `scripts\inspect_datasets.py` and
  verify the relevant files under `data\raw\`; the database builder reports the
  exact missing path or columns.
- **Database locked/rebuild issue:** stop another process using the database
  and rerun `scripts\build_database.py`. The existing database is not replaced
  when validation fails.
- **Dashboard says database missing:** build it first with
  `python scripts\build_database.py`.
- **Tests fail at collection in `tests\test_settings.py`:** verify that file
  does not contain stray editor text; this project has encountered local
  uncommitted corruption in that test file before.

## Data and Git policy

Downloaded raw datasets, FastF1 caches, SQLite files, generated quality
outputs, exports, model artifacts, credentials, and virtual environments are
ignored where appropriate. The Kaggle destination directories are ignored
because large raw data and licensing should be handled locally. Configuration
uses relative paths; original raw files and KaggleHub's cache are preserved.
