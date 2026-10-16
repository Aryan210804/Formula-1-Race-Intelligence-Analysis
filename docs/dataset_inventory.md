# Dataset discovery and inventory

**Inspection date:** 2026-10-16
**Workspace:** `C:\Users\leanvo\OneDrive\Desktop\Formula-1-Race-Intelligence-Analysis`
**Scope:** Read-only file and schema inspection. No source data was moved,
renamed, downloaded, or modified.

## Executive finding

The three manually downloaded Kaggle datasets were **not found** in the current
workspace or the user download locations searched. The only raw F1 inputs found
inside the project are two FastF1 JSON snapshots: the 2024 season schedule and
2024 Bahrain qualifying results. These are not the named Kaggle datasets and
must not be treated as substitutes for them.

The workspace search checked all files in the repository (excluding Git
internals and generated caches for source inventory), and searched for
`.csv`, `.zip`, `.json`, Excel, Parquet, SQLite/database and archive files in
the repository. The following common local locations were also searched:

- `C:\Users\leanvo\Downloads`
- `C:\Users\leanvo\Documents`
- `C:\Users\leanvo\Desktop`
- `C:\Users\leanvo\OneDrive`
- `C:\Users\leanvo\.cache`
- `C:\Users\leanvo\.kaggle`

No Kaggle-specific folders were found at
`C:\Users\leanvo\.kaggle`,
`C:\Users\leanvo\.cache\kaggle`,
`C:\Users\leanvo\Downloads\kaggle`, or
`C:\Users\leanvo\OneDrive\Kaggle`. Other CSV/spreadsheet files exist in
OneDrive, but do not identify themselves as any of the requested F1 datasets;
their contents were not inspected or attributed to F1.

## Repository and environment

- Git branch: `main`, tracking `origin/main`.
- Git status at inspection: `README.md` modified; the bootstrap, ingestion,
  transformation, tests, configuration, and documentation files are
  untracked. The worktree is **not clean**. These pre-existing changes were
  not altered for this inventory.
- Root directories: `.cache/`, `.git/`, `.github/`, `.pytest_cache/`,
  `config/`, `data/`, `docs/`, `scripts/`, `src/`, and `tests/`.
- Python available by absolute path: **3.12.10**. The `python` command on
  `PATH` resolves to the Windows Store app-execution alias; use the installed
  interpreter or a configured virtual environment.
- Installed project-relevant packages: FastF1 3.8.3, Pandas 2.3.3, NumPy
  2.5.4, PyYAML 6.0.3, pytest 9.1.1. The dependency manifest also declares
  `setuptools>=68` as a build-system requirement.
- The current project manifest declares FastF1, Pandas and PyYAML at runtime,
  pytest for development, and `f1-ingest`/`f1-transform` command entry points.
- Source files currently include FastF1 ingestion, transformations, SQLite
  storage and QA test modules. Their existence does not imply that the
  requested Kaggle sources are present or that those sources were validated.

## Found raw source files

Counts and column dtypes below were inferred by reading the JSON `records`
arrays with Pandas. `Null` counts mean JSON null/Pandas missing values; `Blank`
counts mean empty or whitespace-only strings. Full-row duplicates were
checked within each file.

### FastF1 2024 schedule

- **Actual path:** `data/raw/fastf1/season=2024/schedule.json`
- **Absolute path:** `C:\Users\leanvo\OneDrive\Desktop\Formula-1-Race-Intelligence-Analysis\data\raw\fastf1\season=2024\schedule.json`
- **Provenance:** FastF1, per JSON metadata (`source=fastf1`,
  `dataset=schedule`, `season=2024`); not a Kaggle file.
- **Format/size:** JSON object containing metadata and a records array;
  25,704 bytes.
- **Shape:** 24 rows × 23 columns.
- **Full-row duplicates:** 0.
- **Null/blank:** no Pandas nulls and no empty-string cells in the inspected
  records.
- **Candidate single-column uniqueness in this one-season snapshot:**
  `RoundNumber`, `Location`, `OfficialEventName`, `EventDate`, `EventName`,
  and the session date fields. The season-scoped natural key candidate is
  `(season, RoundNumber)`; uniqueness of event names or locations in this one
  schedule is not evidence that they are globally safe keys.
- **Types and per-column missing counts** (all missing counts 0):
  - `RoundNumber` int64; `Country` object; `Location` object;
    `OfficialEventName` object; `EventDate` object; `EventName` object;
    `EventFormat` object.
  - `Session1` object; `Session1Date` object; `Session1DateUtc` object;
    `Session2` object; `Session2Date` object; `Session2DateUtc` object;
    `Session3` object; `Session3Date` object; `Session3DateUtc` object;
    `Session4` object; `Session4Date` object; `Session4DateUtc` object;
    `Session5` object; `Session5Date` object; `Session5DateUtc` object.
  - `F1ApiSupport` bool.
- **Potential relationships:** `season + RoundNumber` can be compared with
  session snapshot metadata `event_id=season:round`; session names and dates
  can map to a session dimension after verifying mappings.
- **Quality cautions:** timestamps are strings and some are UTC-marked strings
  while other fields such as `EventDate` are date-only/naive strings. Parse
  formats explicitly and preserve source values. `Country` has 21 distinct
  values across 24 events, so country is not an event key.

### FastF1 2024 Bahrain qualifying results

- **Actual path:** `data/raw/fastf1/season=2024/round=01-bahrain-grand-prix/session=Q/qualifying_results.json`
- **Absolute path:** `C:\Users\leanvo\OneDrive\Desktop\Formula-1-Race-Intelligence-Analysis\data\raw\fastf1\season=2024\round=01-bahrain-grand-prix\session=Q\qualifying_results.json`
- **Provenance:** FastF1, per JSON metadata (`source=fastf1`,
  `dataset=qualifying_results`, `season=2024`, `event_id=2024:1`,
  `event_name=Bahrain Grand Prix`, `session=Q`); not a Kaggle file.
- **Format/size:** JSON object containing metadata and a records array;
  12,275 bytes.
- **Shape:** 20 rows × 22 columns.
- **Full-row duplicates:** 0.
- **Null counts:** `GridPosition=20`, `Q2=5`, `Q3=10`, `Time=20`,
  `Points=20`, `Laps=20`; all other columns 0.
- **Blank-string counts:** `BroadcastName=20`, `TeamColor=20`,
  `HeadshotUrl=20`, `CountryCode=20`, `ClassifiedPosition=20`, and
  `Status=20`; all other columns 0. Blanks are distinct from nulls and both
  are distinct from numeric zero.
- **Types and per-column null counts:**
  - `DriverNumber` object (0); `BroadcastName` object (0);
    `Abbreviation` object (0); `DriverId` object (0); `TeamName` object (0);
    `TeamColor` object (0); `TeamId` object (0); `FirstName` object (0);
    `LastName` object (0); `FullName` object (0); `HeadshotUrl` object (0);
    `CountryCode` object (0).
  - `Position` float64 (0); `ClassifiedPosition` object (0);
    `GridPosition` object (20); `Q1` object (0); `Q2` object (5);
    `Q3` object (10); `Time` object (20); `Status` object (0);
    `Points` object (20); `Laps` object (20).
- **Candidate single-column uniqueness in this event:** `DriverNumber`,
  `Abbreviation`, `DriverId`, `FirstName`, `LastName`, `FullName`,
  `Position`, and `Q1`. Only `DriverId` (or `DriverNumber` where `DriverId`
  is unavailable) is a suitable identity candidate. Result grain should be
  keyed by event/session/driver, not names, `Position`, or lap-time segment.
- **Potential relationships:** metadata `event_id=2024:1` and `event_round=1`
  map to the schedule's 2024 round 1. `DriverId` is a driver join key and
  `TeamId` is a constructor join key. Both relationships require validation
  across more than this one snapshot before generalizing.
- **Quality cautions:** optional qualifying segments are null for drivers who
  did not reach later segments; null `Q2`/`Q3` must not be interpreted as zero.
  All `GridPosition`, `Time`, `Points`, and `Laps` values are null in this
  snapshot, while `ClassifiedPosition` and `Status` are blank strings.
  `Q1` is a FastF1 duration string and needs validated parsing. `CountryCode`
  and headshot URL are blank throughout and cannot support nationality or
  media analysis from this file.

## Other F1-related workspace artifacts (not raw Kaggle inputs)

- `data/processed/f1_intelligence.sqlite3` — SQLite, 192,512 bytes; generated
  local analytical artifact. A read-only schema/count inspection found
  `events=24`, `drivers=20`, `constructors=10`, `sessions=120`,
  `qualifying_results=20`; `race_results`, `session_results`, `laps`,
  `pit_stops`, `weather`, `telemetry`, rejected-record, and quality-issue
  tables each have 0 rows. This database is not an original Kaggle download.
- `data/processed/fastf1/season=2024/schedule.json` — processed FastF1
  schedule snapshot, 30,888 bytes.
- `data/processed/fastf1/season=2024/round=01-bahrain-grand-prix/session=Q/qualifying_results.json`
  — processed FastF1 qualifying snapshot, 17,659 bytes.
- `data/processed/fastf1/season=2024/round=01-bahrain-grand-prix/session=Q/manifest.json`
  — ingestion manifest, 234 bytes.
- `data/processed/quality/quality_report.json` — generated QA report,
  1,194 bytes; describes only the files included in its run.
- `data/processed/quality/quality_summary.md` — generated QA summary,
  412 bytes.
- `.cache/fastf1/fastf1_http_cache.sqlite` — FastF1 cache, 53,248 bytes;
  not an analytical source dataset.
- No CSV, ZIP, XLS, XLSX, XLSM, Parquet, or archive dataset was found inside
  the repository.

## Requested Kaggle source mapping

| Requested source | File found? | Verified schema/format |
|---|---:|---|
| `anthonytherrien/predicting-f1-pit-stops-vault` | No | Not available to inspect |
| `navenkumar1998/formula-1-dataset-with-weather-and-tyre-features` | No | Not available to inspect |
| `rohanrao/formula-1-world-championship-1950-2020` | No | Not available to inspect |

No mapping of filenames or columns to these sources is assumed. Therefore,
there are no verified cross-source candidate keys, join relationships, or
source-specific data-quality findings for those Kaggle downloads yet.

## Proposed data folder layout

This is a proposal only; source files have not been copied or reorganized.
Place each downloaded source in its own provenance-preserving folder, retaining
the exact downloaded filenames:

```text
data/
  raw/
    kaggle/
      anthonytherrien_predicting-f1-pit-stops-vault/
        <original downloaded files>
      navenkumar1998_formula-1-dataset-with-weather-and-tyre-features/
        <original downloaded files>
      rohanrao_formula-1-world-championship-1950-2020/
        <original downloaded files>
    fastf1/
      season=2024/
        schedule.json
        round=01-bahrain-grand-prix/
          session=Q/
            qualifying_results.json
  interim/
    kaggle/
      <source-slug>/
        <derived, source-specific validated extracts>
  processed/
    normalized/
      <documented canonical tables>
    reports/
      dataset_inventory.json
      data_quality.json
  exports/
    tableau/
      <validated analytical CSV outputs>
```

Raw data should remain immutable. Any extraction, normalized copy, join, or
Tableau output belongs in a separate derived-data directory and should include
source provenance and row-count/exclusion reports.

## Blocker and next step

The requested three Kaggle datasets are outside the searchable workspace/home
locations or otherwise unavailable to this environment. To continue Phase 1,
place their original downloaded files in the corresponding folders under
`data/raw/kaggle/` above, or provide the exact directory path if they are
already stored elsewhere. After that, inventory actual file names, headers,
row counts, inferred types, missingness, duplicate keys, and potential joins
before proposing transformations. No analytics or dashboards were started.
