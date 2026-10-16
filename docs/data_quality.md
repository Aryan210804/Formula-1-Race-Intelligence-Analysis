# Data quality and transformation rules

## Running the checks

Install the project, then run:

```bash
python -m pip install -e ".[dev]"
python -m pytest
f1-transform
```

`f1-transform --strict` returns status `1` when error-severity findings exist.
Input/read/storage failures return status `2`. Reports are written to
`data/processed/quality/quality_report.json` and
`data/processed/quality/quality_summary.md`; use `--report-dir` to change the
location. The SQLite database also contains `quality_issues` and
`rejected_records` tables. Each rejected row retains its source record,
filename, record index, target table, and reason codes.

The command rebuilds all analytical tables from raw snapshots by default.
`--incremental` uses key-based upserts instead. Raw JSON is never edited.
Repeated rebuilds are deterministic in table contents and do not create
duplicate facts.

## Checks and remediation

| Rule | Finding | Action |
|---|---|---|
| Raw JSON structure and required source columns | Transformation error or `missing_required_columns` | Correct/re-ingest the affected source snapshot; no source file is modified |
| Metadata row count versus JSON record count | `source_row_count_mismatch` warning | Investigate a truncated or stale snapshot |
| Event round/name, season, and `event_id` against the season schedule | `inconsistent_event_*` or `broken_event_relationship` error | Re-ingest the schedule or session for the matching event |
| Missing driver identifiers | `missing_driver_identifier` error and rejected fact; if only `DriverId` is missing, a season-scoped `DriverNumber` fallback is warned | Obtain a source identifier; do not join on driver names |
| Missing `TeamId` | Constructor stays nullable | Leave unmatched; no constructor is guessed from a team name |
| Duplicate event, result, lap, or observation natural key | `duplicate_*_key` error; later conflicting fact is rejected | Inspect source duplication and preserve source evidence |
| Non-positive/non-integral positions, lap numbers, grid positions, or completed laps | `invalid_*` error; invalid fact is rejected | Correct source data or retain as a documented reject |
| Negative or malformed non-empty result/lap/qualifying/pit times | `invalid_*_time` error and rejected fact | Check source value and FastF1 availability |
| Missing optional result positions/timing/points | Nullable fact values, not zero | No remediation unless the field is required for a downstream use |
| Broken fact-to-event/session/driver/constructor relationship | `broken_event_relationship` or `missing_*_dimension` error; fact rejected | Ingest the corresponding schedule/identity source before loading facts |
| High null rate for driver/constructor names or event name | `unexpected_null_rate` warning when more than 50% of people names or any event name is null | Verify source completeness; keys remain the authoritative identity |
| At least 20 prior/current source records and a change greater than 50% | `suspicious_row_count_change` warning | Check whether the source snapshot is partial or intentionally updated |
| Event round zero/testing row in a schedule | Informational `non_championship_schedule_row` | Excluded from championship event dimension |
| Missing optional dataset (e.g., no telemetry file) | Zero table rows; no synthetic fallback | Use a supported session/scope if the data is needed |

Warnings are non-fatal by default. Error findings do not silently remove
evidence: records that can be associated with a source row are captured in
`rejected_records`, and all issues are present in both report formats. A
`--strict` run exposes those errors through its exit code for automation.

## Status semantics

Status is never derived solely from position, points, laps, or the absence of a
time. The original source text is preserved. Only explicit known source
statuses are grouped as `DNF`, `DNS`, `DSQ`, or `CLASSIFIED`; other non-empty
values remain `OTHER_SOURCE_STATUS`, and blank status stays null. This prevents
missing timing or unavailable result data from being mislabeled as a DNF.

## Coverage and caveats

The current local raw snapshot set contains a 2024 FastF1 schedule and 2024
Bahrain qualifying results only. No historical-wide cleanliness or coverage
claim is made. FastF1's session support, circuit locations, optional columns,
and timing availability vary by year/session. For pit data, the inspected
ingestion source exposes lap `PitInTime`/`PitOutTime` observations rather than
a guaranteed independent stop table. A full run's report counts are the
authoritative record of exactly which source files were checked and which
records were accepted or rejected.
