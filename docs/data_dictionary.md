# Data dictionary and analytical schema

## Source and rebuild contract

`f1-transform` reads only JSON snapshots below `data/raw/fastf1/`. It never
cleans or rewrites those inputs. Normalized tables and quality findings are
recreated transactionally in SQLite from all currently available raw snapshots.
The default database is `data/processed/f1_intelligence.sqlite3`; override it
with `f1-transform --database PATH`.

FastF1 source columns remain available in each raw JSON record. The normalized
schema keeps source identifiers and selected source status/time text alongside
typed values. A SQL `NULL` represents unavailable source information; it is not
converted to zero. Distances and positions are one-based when present, and
elapsed times are stored in seconds.

## Relational tables

| Table | Grain (one row) | Primary key | Foreign keys |
|---|---|---|---|
| `circuits` | One normalized FastF1 country/location pair | `circuit_id` | — |
| `events` | One championship event in one season | `event_id` (`season:round`) | `circuit_id` → `circuits` |
| `drivers` | One source driver identifier | `driver_id` (`DriverId`; season-scoped number fallback only when necessary) | — |
| `constructors` | One FastF1 `TeamId` | `constructor_id` | — |
| `sessions` | One session code for one event | `session_id` (`event_id:code`) | `event_id` → `events` |
| `race_results` | One driver classification row per race session | (`event_id`, `session_id`, `driver_id`) | composite session/event, driver, optional constructor |
| `qualifying_results` | One driver classification row per qualifying session | (`event_id`, `session_id`, `driver_id`) | composite session/event, driver, optional constructor |
| `session_results` | One driver classification row for another explicitly ingested session | (`event_id`, `session_id`, `driver_id`) | composite session/event, driver, optional constructor |
| `laps` | One source lap row per session, driver, and lap number | (`session_id`, `driver_id`, `lap_number`) | composite session/event, driver |
| `pit_stops` | One source pit-in/out observation row per session, driver, and lap | (`session_id`, `driver_id`, `lap_number`) | composite session/event, driver |
| `weather` | One FastF1 weather observation by session sample order | (`session_id`, `sample_number`) | composite session/event |
| `telemetry` | One telemetry sample by session, driver, and source sample order | (`session_id`, `driver_id`, `sample_number`) | composite session/event, driver |
| `rejected_records` | One source record rejected by cleaning or relationship validation | deterministic SHA-256 `reject_id` | — |
| `quality_issues` | One unique validation finding | deterministic SHA-256 `issue_id` | — |

`circuit_id` is a deterministic normalized key derived from country and
location because the inspected FastF1 schedule does not contain a circuit ID.
Driver and constructor joins use `DriverId` and `TeamId` when present, not
names. If `DriverId` is absent, `DriverNumber` is namespaced by season; the
quality report records this fallback.

### Event and session dimensions

`events` fields: `event_id TEXT`, `season INTEGER`, `round_number INTEGER`,
`event_name TEXT`, normalized `event_name_key TEXT`,
`official_event_name TEXT`, `country TEXT`, `location TEXT`,
nullable `circuit_id TEXT`, `event_date TEXT`, and `event_format TEXT`.
`season`/`round_number` is unique. Event names are preserved from FastF1;
normalization is used only to construct the circuit key.

`sessions` fields: `session_id TEXT`, `event_id TEXT`, `session_code TEXT`,
`session_name TEXT`, and nullable `scheduled_start TEXT`. Standard FastF1
schedule names map to `FP1`, `FP2`, `FP3`, `Q`, `SQ`, `SS`, `S`, and `R`.
An ingested session not represented in the schedule is added from the source
dataset metadata.

### People dimensions

`drivers` stores `driver_id`, `driver_number`, `abbreviation`, first/last/full
name, and country code. `constructors` stores `constructor_id`, source team
name, and source color. Descriptive fields can be null and can change between
source snapshots; identifiers define joins.

### Result facts

Race, qualifying, and generic session result facts store event/session/driver
keys, optional constructor, position, source classified position, grid
position, points, original status string, conservative status group, elapsed
time seconds, and completed laps. Qualifying facts additionally keep each
original `Q1`/`Q2`/`Q3` value and its parsed seconds.

Position and grid position are nullable for source records without a
classification. No position, points, or classification is inferred. The
original `Status` remains in `status_source`; `status_group` only classifies
explicit source values such as `DNF`, `DNS`, `DSQ`, `Finished`, and
`Classified`. Other source strings are retained as `OTHER_SOURCE_STATUS`;
missing source status remains SQL `NULL`.

### Timing and observations

`laps` contains positive source lap numbers, source lap-time text, typed lap
and sector seconds, start time seconds, stint, tyre compound/life, and the
source personal-best flag. Missing lap/sector times remain null; malformed
non-empty lap times are rejected.

`pit_stops` is deliberately an **observation** table: FastF1 lap rows can
expose `PitInTime` and/or `PitOutTime`, but this is not an independent
pit-stop classification feed. Each row preserves those timestamps as available
on one source lap; no pit-stop duration or in/out pairing is fabricated.

`weather` stores one source weather sample and typed temperature, humidity,
pressure, wind, rainfall source value, and elapsed source time when available.
`telemetry` stores one source sample with speed, throttle, brake, gear, RPM,
DRS, and source time. Availability is session-specific; absent data means zero
rows, not synthetic observations.

## Type and constraint conventions

- Keys and source categorical identifiers are `TEXT`.
- Season, round, lap, position, gear, stint, and sample numbers are `INTEGER`
  with positive/non-negative `CHECK` constraints where applicable.
- Continuous scores, points, and parsed times are `REAL`; parsed elapsed times
  must be non-negative.
- Source booleans are retained as text where the source can vary; normalized
  telemetry brake/personal-best fields use nullable integer `0`/`1`.
- Foreign keys are enabled for every SQLite connection. Composite
  session/event foreign keys prevent a fact row from pairing a valid session
  with the wrong event.
- Fact-table keys are unique at their documented grain. Rebuild mode deletes
  and repopulates all normalized tables in dependency order in one transaction.
