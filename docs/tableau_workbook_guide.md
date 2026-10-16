# Formula 1 Race Intelligence — Tableau workbook build guide

## Delivery status and evidence boundary

**This document is a build specification, not a Tableau workbook.** No Tableau
Desktop/Public executable or installation was detected in the checked Windows
environment. `data/exports/` contains only `.gitkeep`; no verified CSV export,
manifest, packaged workbook, or published workbook exists.

The source inventory in [dataset_inventory.md](./dataset_inventory.md) found
only:

- A FastF1 2024 season schedule (24 events).
- Bahrain 2024 qualifying results (20 drivers).

The three requested Kaggle datasets were not found. The existing SQLite
database was built from those FastF1 snapshots, not from the requested full
historical, weather/tyre, and pit-stop data. In that inspected data the
qualifying-results table has 20 rows; race results, laps, pit stops, weather,
and telemetry have zero rows; driver country codes are blank; qualifying
`Points`, `Time`, `Laps`, and `GridPosition` are null throughout. Therefore
championship totals, wins, podiums, reliability, tyre strategy, nationality
comparisons, pit duration, lap pace, and weather relationships cannot currently
be calculated from verified project data.

Do not create zero-valued KPI cards for unavailable measures. Hide a sheet or
mark it “Not available in current source coverage” until a validated export
contains its documented inputs. A blank/unknown value is not zero.

## Workbook identity and design system

- **Workbook title:** Formula 1 Race Intelligence
- **Subtitle:** Evidence-led championship, driver, team, strategy, and
  reliability analysis
- **Audience:** Motorsport analysts, team/commercial stakeholders, and
  informed F1 viewers
- **Canvas:** 1280 × 800 px dashboard target; device layouts should be checked
  separately.
- **Background:** `#F5F6F7`
- **Cards/surfaces:** `#FFFFFF`
- **Primary text:** `#20252B`
- **Secondary text:** `#68717D`
- **Accent:** `#C8102E`, reserved for selected/highlighted/primary series.
- Use restrained gridlines, one consistent sans-serif family, sentence-case
  titles, concise subtitles, and direct labels. Do not use gradients, neon
  colors, decorative race imagery, or red as the only encoding for categories.
- Use colorblind-safe sequential/diverging palettes for multi-category
  analysis; keep constructor/driver colors stable within the workbook.
- Include a visible data-coverage caption on every dashboard:
  selected seasons, events, available sessions, source refresh timestamp, and
  missing source families.
- Keep tooltips explicit about row grain, denominator, season selection, and
  null treatment.

## Data source contract before workbook construction

Build CSV outputs from the validated database first. No CSV filenames are
verified today, so names in this table are **proposed export contracts**, not
claims that files exist.

| Proposed logical export | Required grain | Required source tables/fields |
|---|---|---|
| `dim_event.csv` | One event per season | `events`: `event_id`, `season`, `round_number`, `event_name`, `country`, `location`, `circuit_id`, `event_date`; `circuits` attributes only if validated |
| `dim_session.csv` | One session per event | `sessions`: `session_id`, `event_id`, `session_code`, `session_name`, `scheduled_start` |
| `dim_driver.csv` | One source driver identifier | `drivers`: `driver_id`, `abbreviation`, `full_name`, `country_code`; nationality analysis requires populated, validated country code |
| `dim_constructor.csv` | One source constructor identifier | `constructors`: `constructor_id`, `constructor_name`, `team_color` |
| `fact_race_result.csv` | One driver per race session | `race_results`: event/session/driver/constructor IDs, position, points, source status/group, elapsed time, laps completed |
| `fact_qualifying_result.csv` | One driver per qualifying session | `qualifying_results`: same identity keys, position, Q1/Q2/Q3 source and seconds |
| `fact_lap.csv` | One driver lap per session | `laps`: session/driver/lap keys, lap time and sectors in seconds, stint, compound |
| `fact_pit_observation.csv` | One source pit-in/out observation per driver lap | `pit_stops`: session/driver/lap keys and source pit-in/out seconds. These are not guaranteed stop-duration records. |
| `fact_weather.csv` | One weather sample per session | `weather`: session/sample keys, observation time, temperatures, humidity, rainfall source, wind |
| `fact_telemetry.csv` | One telemetry sample per driver/session | `telemetry`: session/driver/sample keys and supported channel fields |

Preserve source IDs and use relationship keys, not names. Do not flatten
race-result facts together with lap, weather, telemetry, or pit-observation
facts: these are different grains, and their row multiplication inflates points,
entries, and podiums. In Tableau, use **relationships** between logical tables
at their declared grain; avoid physical joins unless a worksheet-specific
aggregate table has been proven one-to-one/many-to-one.

### Proposed logical relationships

```text
dim_event (1) ── (many) dim_session
dim_event (1) ── (many) fact_race_result
dim_event (1) ── (many) fact_qualifying_result
dim_event (1) ── (many) fact_lap
dim_event (1) ── (many) fact_pit_observation
dim_event (1) ── (many) fact_weather

dim_session (1) ── (many) each session-grain fact
dim_driver (1)  ── (many) race, qualifying, lap, pit, telemetry facts
dim_constructor (1) ── (many) result facts
dim_circuit (1) ── (many) dim_event, only if a validated circuit key exists
```

Use `event_id`, `session_id`, `driver_id`, and `constructor_id`. Before
publishing, verify key uniqueness on dimension sides and foreign-key coverage
on every fact export. The current schema's `circuit_id` is derived from
country/location because the schedule did not provide a source circuit ID;
do not represent this as an official circuit identifier.

## Metric and filter conventions

Create these calculations only on the matching fact table or a validated
aggregate export. Prefix calculations with their grain, for example
`Race | Podium Flag` or `Lap | Valid Lap Flag`.

- **Race entry count:** `COUNTD([event_id] + "|" + [session_id] + "|" + [driver_id])`
  on `fact_race_result.csv`. The denominator is source result rows at the
  driver-race grain, not laps or pit observations.
- **Points:** `SUM([points])` only from race results. Null points remain
  unavailable; never `ZN()` them without a documented, validated rule.
- **Wins:** count race-result rows with source position 1. Do not count
  qualifying position as a race win.
- **Podium:** count race-result rows with position in 1, 2, 3. A driver or
  constructor podium count uses the same race-row flag at the appropriate
  grouping level.
- **Average finishing position:** average non-null race `position` over
  classified/source-positioned driver-race rows; state the denominator. Do not
  map blank classifications or retirements to a finishing position.
- **Completion rate (source-position proxy):** classified race entries divided
  by race entries only if the source has a validated classified indicator.
  If using `position IS NOT NULL`, title it “Entries with position recorded”;
  do not call it physical race completion without validating status semantics.
- **Explicit DNF rate:** entries with an explicit source status mapped to DNF,
  divided by all race-result entries in the current filter context. Keep DNS,
  DSQ, other statuses, and missing status separate. The actual status mapping
  must be documented for each source before aggregation.
- **Cumulative points:** running sum of race points ordered by
  `event_date`, then `season`, `round_number` (and a stable event key as a
  tie-breaker). Partition by `season` and driver for season totals/trends.
  Across scoring-system eras, label raw cumulative points as source-awarded
  points; do not compare them as if points schedules were constant.
- **Tyre usage:** laps or stint count by original compound, depending on
  supplied grain. Show null/unknown compound as its own “Not recorded” category,
  not as zero usage. Map source compound strings using a documented mapping
  while retaining the original value.
- **Pit duration:** only calculate if the source provides compatible
  in/out/duration records at a documented stop grain. The current
  `pit_stops` table stores lap-level pit-in/out observations and does **not**
  support pit-stop duration calculation on its own.
- **Time units:** result/lap/sector/weather time is seconds where the export
  documents `_s`; display lap/qualifying times as `mm:ss.000` only through a
  tested formatting calculation, retaining numeric seconds for comparisons.
- **Race count by host country:** `COUNTD([event_id])` using `dim_event`, with
  an explicit season filter. This counts scheduled championship events in the
  selected data, not unique physical circuits or all historical races.
- **Season filters:** Season, event, session, driver, constructor, circuit.
  Apply filters only to sheets whose data supports them. Use `event_id` for
  event filtering and `circuit_id` only when validated. A nationality filter
  must not imply nationality coverage when its source field is null.

Avoid dashboard-global “Apply to all using related data sources” unless
relationships and denominator behavior have been tested. Prefer explicit
filter scoping and visible numerator/denominator definitions.

## Dashboard specifications

### 1. Executive Overview

- **Question:** What championship picture is supported by the selected,
  validated seasons?
- **Data/grain:** Race result fact, one driver per race session, related to
  event and constructor dimensions. This source family has zero rows today.
- **KPI definitions:** Season points (`SUM(points)`), races (`COUNTD(event_id)`),
  wins (race position 1), podiums (race position ≤ 3). Each must be tagged to
  the season filter and source coverage. If unavailable, replace the KPI row
  with a neutral coverage notice; do not show 0.
- **Charts:** Season points trend; race winners by round; constructor points
  by round; event calendar strip. Do not present current qualifying position
  as championship standing.
- **Filters:** Season, constructor, driver. The season filter applies to all
  KPI/chart sheets; driver and constructor filters should be mutually
  documented if both are applied.
- **Navigation/tooltips:** Click a season mark to open Driver Intelligence or
  Constructor Championship filtered to that season. Tooltip shows source row
  grain, points, race round/date, and coverage.
- **Layout:** Title/coverage header, four KPI cards, two balanced charts, small
  event strip; no map on this summary page.
- **Current release gate:** Block championship KPIs and charts until race
  results are populated and validated. In the inspected data, only schedule
  event count is supportable for the 2024 schedule, and that is not a
  historical championship KPI.

### 2. Driver Intelligence

- **Question:** How did a selected driver's championship performance evolve
  within a season?
- **Data/grain:** Race result fact at driver-race grain; driver dimension for
  identity/nationality.
- **KPI definitions:** Season points, race wins, podium count, average
  finishing position with classified-position denominator, and explicit-status
  completion/retirement measures as defined above.
- **Charts:** Running cumulative points by race date/round; finishing-position
  dot plot by round; season points vs. podiums; nationality comparison only
  where country code is populated and source semantics confirmed.
- **Calculated fields:** `Race | Win Flag`, `Race | Podium Flag`,
  `Driver | Cumulative Points` with season/driver partition and event-date
  ordering.
- **Filters:** Season required; driver; constructor; circuit/event. Default to
  one season and one driver to avoid mixing scoring eras.
- **Navigation/tooltips:** Driver mark opens qualifying/lap detail only if
  related exports exist. Tooltip includes classified-row denominator and
  missing status/timing notes.
- **Layout:** Driver selector and identity band, cumulative trend left,
  finishing plot right, compact season summary below.
- **Current release gate:** Block points, wins, podiums, finishing performance,
  and nationality comparisons. The available file is qualifying-only and
  country codes are blank.

### 3. Constructor Championship

- **Question:** Which constructor led a selected championship season and how
  did its race-by-race points develop?
- **Data/grain:** Race results at driver-race grain related to constructor;
  optionally pre-aggregate verified points to one constructor/event before
  charting.
- **KPI definitions:** Constructor points are the sum of member-driver race
  points once per result row; wins and podiums use result row counts (a team
  can have two podiums in one race). Add a separate “races with a constructor
  podium” metric only as `COUNTD(event_id)` of constructor-event aggregates.
- **Charts:** Season-by-season constructor points bars; selected-season
  constructor cumulative points by round; points/wins/podium small multiples.
- **Filters:** Season, constructor, event/circuit. Red Bull Racing vs.
  Mercedes comparison is limited to overlapping seasons with rows for both
  constructor IDs; compare within a season, never cumulative career totals.
- **Tooltip:** Constructor source ID/name, season, race, points, driver result
  rows contributing to event aggregate.
- **Layout:** Side-by-side season comparison plus one selected-season detail
  trend; legends ordered consistently.
- **Current release gate:** Block. The present qualifying snapshot has team
  identifiers but no championship points; do not infer constructor standings
  from qualifying results.

### 4. Tyre and Race Strategy

- **Question:** Which tyre compounds and stints were recorded, and how do
  observed usage/outcomes differ by event?
- **Data/grain:** Lap fact at driver-lap grain (or a validated stint table);
  race result fact at driver-race grain. Aggregate each fact separately
  before relating outcomes. Never join raw lap rows to results and sum race
  points.
- **KPI definitions:** Lap usage = count of source laps with a non-null
  normalized compound; compound share = compound lap count / all laps with a
  recorded compound. Publish missing-compound laps separately. Outcome is
  race finish/points at race grain, not repeated per lap.
- **Charts:** Compound distribution by circuit; stint sequence by driver and
  race; compound lap count by season/circuit; outcome comparison only with
  explicitly described grouping and adequate coverage.
- **Categories:** Preserve raw compound. Map Soft/Medium/Hard/Intermediate
  only with explicit source dictionary; all unmatched source values remain
  “Other source value” and null remains “Not recorded.”
- **Filters:** Season, circuit, driver, constructor, event; session restricted
  to race where race strategy is being interpreted.
- **Tooltip:** Compound source string and normalized label, lap denominator,
  stint/lap grain, number of races represented.
- **Current release gate:** Block. Current database has zero lap rows and no
  tyre data.

### 5. Reliability and DNF

- **Question:** What source-recorded race statuses and position availability
  occurred by season?
- **Data/grain:** Race result fact, one driver-race row. No lap/pit/weather
  joins in numerator or denominator calculations.
- **KPI definitions:** Race entries = count of result rows at event/driver;
  explicit DNF entries = rows whose documented source status maps to DNF;
  DNF rate = explicit DNF entries / all selected race-result entries.
  DNS, DSQ, other source status, and missing status each remain distinct.
  “Entries with a position recorded” is separate from “completed” unless the
  source status definition justifies completion.
- **Charts:** Season entry/status stacked bars; DNF-rate line with numerator
  and denominator in tooltip; source status detail table.
- **Classification:** Never infer mechanical failure from DNF alone. Mechanical,
  collision, disqualification, and other causes require a source field with
  validated mapping.
- **Filters:** Season, constructor, driver, country/circuit. Display
  denominator changes as filters are applied.
- **Current release gate:** Block. No race-result rows exist in the verified
  database.

### 6. Global F1

- **Question:** How are the validated event schedule and driver nationalities
  distributed geographically?
- **Data/grain:** Event dimension, one scheduled event; driver dimension, one
  source driver. Separate map/country sheets to avoid multiplying drivers by
  event rows.
- **KPI definitions:** Host event count = distinct event IDs by host country
  and selected season. Driver nationality distribution = distinct driver IDs
  by validated nationality field; it is not a race-entry count.
- **Charts:** Host-country event count bars; circuit/event calendar table;
  nationality distribution only with populated, documented nationality data.
  Map is optional and requires geocodable host country/location, not a
  fabricated circuit coordinate.
- **Filters:** Season, country, circuit. Nationality filter only when supported.
- **Tooltip:** Events and seasons represented; clarify schedule count vs.
  historical race count.
- **Current release gate:** A 2024 schedule-only event count is possible from
  the documented event table, but no CSV is available. Nationality analysis is
  blocked because the inspected driver country codes are blank. Label event
  counts as schedule coverage, not all-time F1 history.

### 7. Pit Stops and Pace

- **Question:** What source-backed stop, qualifying, lap-pace, and weather
  observations are available for a selected session?
- **Data/grain:** Pit observation one driver/lap; lap fact one driver/lap;
  qualifying fact one driver/session; weather fact one session sample.
  Build separate sheets from each logical fact; do not cross-join raw grains.
- **KPI definitions:** Pit-stop duration only from a source-defined stop row
  with compatible entry/exit or duration fields. The current schema stores
  lap pit-in/out timestamps and does not define a duration. Lap pace uses
  valid non-null `lap_time_s`; report valid-lap count and exclusions. Qualifying
  best segment is the minimum non-null segment time per driver/session only
  when the source values are parsed and verified.
- **Charts:** Qualifying segment comparison; lap-time trend by lap number;
  pit-duration distribution if valid duration data is later supplied;
  weather time series and lap-time comparison only if clocks/session keys are
  compatible. A weather association is descriptive, not causal.
- **Filters:** Season, event/circuit, session, driver, constructor, compound.
  Make session selection mandatory for timing comparisons.
- **Tooltip:** Original time field, normalized unit, source observation/lap
  grain, included/excluded row counts, weather sample timestamp.
- **Current release gate:** Only qualifying result rows are present. There are
  no lap, pit, weather, or telemetry rows; show a source-coverage notice and
  do not show a pit duration or pace correlation.

## Connected Tableau Story

Create a Story titled **“Reading the race: championship, strategy, and
reliability”** with these points, only after the corresponding dashboards
pass their data gates:

1. **The championship frame** — Executive Overview, selected season and
   coverage statement.
2. **Driver trajectory** — Driver Intelligence; one-season cumulative points
   and race positions.
3. **Team contest** — Constructor Championship; compare constructors only in
   shared seasons.
4. **Strategy under the tyres** — Tyre and Race Strategy; explain lap/stint
   denominator and unrecorded compound share.
5. **Reliability context** — Reliability and DNF; show source status and
   denominator, separating unknown statuses.
6. **The global calendar** — Global F1; distinguish event schedule counts
   from unique circuits and historical race totals.
7. **Pace and conditions** — Pit Stops and Pace; finish with supported
   observations and explicitly avoid causal conclusions.

Use one short takeaway sentence per story point, linked to a visible field or
calculation, and a “coverage/limitations” caption. Do not write findings in
advance of data validation. With current sources, only a schedule/qualifying
coverage story point could be populated, and no CSV export exists yet.

## Tableau Desktop/Public build steps (manual; no workbook created)

1. In a prepared Tableau environment, first generate the documented CSV
   exports from a validated database and retain their manifest. Verify each
   file's row count, columns, null handling, and grain against SQLite.
2. Open Tableau Desktop or Tableau Public and create a new workbook. Use
   **Connect → Text file** for each CSV export. Do not connect to guessed
   filenames; select only manifest-listed files.
3. In the Data Source page, set explicit data types from the manifest:
   IDs as strings, seasons/rounds/positions/counts as whole numbers, points
   and elapsed seconds as numeric, dates as Date/Date & Time, and source
   categories as strings.
4. Build the logical model with relationships on exact IDs. Keep each fact
   table separate. Set the relationship cardinality only after checking
   exported key uniqueness; otherwise leave it unspecified. Do not use
   Tableau's automatic physical join suggestions without validating
   row-count preservation.
5. Create a small data-validation worksheet for each fact: row count,
   distinct business key count, null key count, and aggregate points/counts.
   Compare totals against the export manifest and SQLite before constructing
   KPI sheets.
6. Create calculations from the definitions above; name calculations with
   their grain. Test filter interaction against expected numerator and
   denominator values. Do not use `ZN`/`IFNULL(...,0)` for unavailable data.
7. Build the dashboards in this document's order. Use fixed dashboard sizing,
   tiled containers, 16–24 px internal spacing, consistent typography and
   restrained color. Hide gated sheets rather than displaying unsupported
   metrics.
8. Add navigation buttons or dashboard actions from summary marks to detail
   dashboards. Pass stable season/event/driver/constructor IDs, not display
   names.
9. Create the Story last. Set a consistent story point size, concise titles,
   one explanatory annotation per point, and repeat source coverage in the
   story caption.
10. Save locally as a `.twb` or packaged `.twbx` only after workbook QA. Publish
    to Tableau Public only if explicitly desired and data licensing permits.

## Workbook QA checklist

- [ ] Every data source is listed in the export manifest; no unverified CSV is
      connected.
- [ ] Each dimension key is unique; each fact key is unique at documented
      grain; foreign-key coverage is checked.
- [ ] Relationship filters do not multiply points, wins, podiums, or race
      entries when lap/weather/pit tables are added.
- [ ] Points totals and row counts match SQLite/export manifest for every
      season and filter selection.
- [ ] Cumulative points sort by event date, round, and stable event ID; running
      total restarts at intended season/driver partition.
- [ ] Constructor comparisons use the same selected season and source
      constructor identifiers.
- [ ] Podium counts use race result rows and position 1–3; qualifying rows are
      never included.
- [ ] DNF/DNS/DSQ/unknown categories preserve source distinctions; rate
      denominator is visible in titles/tooltips.
- [ ] Null compound/status/nationality/weather/time is visibly distinct from
      zero or “none.”
- [ ] Pit duration appears only if a source-defined stop duration or verified
      in/out pairing exists.
- [ ] All date filters use a documented timezone/date field; no timestamp
      string is silently interpreted as a local time.
- [ ] Tooltips state units and grain; axis titles show points, seconds,
      entries, or percentages.
- [ ] No chart implies that a correlation demonstrates causation.
- [ ] Dashboard filters are scoped intentionally; season/event selections
      remain consistent when navigating.
- [ ] Story points show source coverage, limitations, and traceable
      calculations.
- [ ] Workbook opens in the target Tableau Desktop/Public version and all
      data connections refresh successfully.
- [ ] No screenshot, published link, workbook file, or finding is claimed
      unless actually created and checked.

## Current completion state

- Verified CSV exports: **none**.
- Tableau workbook/story file: **not created**.
- Tableau Desktop/Public tooling: **not detected** in the inspected environment.
- Manual Tableau build: **not yet actionable against project exports** because
  exports and the three Kaggle sources are unavailable.
- Verified build specification: this document, based on the checked inventory
  and documented SQLite table grains/fields only.
