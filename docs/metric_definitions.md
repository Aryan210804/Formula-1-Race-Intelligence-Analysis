# Metric definitions and coverage

| Metric | Definition | Grain / limitation |
|---|---|---|
| Driver points | Sum of `results.points` | Race entries grouped by driver or driver-season; not a standings snapshot |
| Wins | Race entries with `positionOrder = 1` | A win is one driver entry at the top of a Grand Prix classification |
| Podiums | Race entries with `positionOrder` in 1-3 | Counts driver finishes, not unique Grand Prix events |
| Average finish | Mean numeric `positionOrder` | Includes classified and unclassified result-order values; interpret alongside status |
| Constructor season points | Sum of `constructor_results.points` by constructor and race year | Official constructor points source; not sum of driver result points |
| Classified finish | Status `Finished` or `+N Lap(s)` | Defined operational classification, not an independent FIA classification rule |
| Completion rate | Classified finishes divided by race result entries | Entry-level denominator; non-finish labels are not claimed to be mechanical failures |
| Host-country Grand Prix count | Distinct race IDs per circuit country | One event is one race row; multiple circuits in a country are grouped |
| Pit-stop duration | `pit_stops.milliseconds` | Source units are milliseconds; historical pit-stop records only |
| Tyre/weather observations | Lap-grain observations from the separate weather/tyre Parquet file | No direct join to historical results is asserted; trends are observational |
| Mean lap time | Mean source milliseconds by observed compound/year or season | Conditions, circuit mix, and regulations are not controlled; not causal |

The local race file covers 1950–2024, historical pit stops cover 2011–2024, and the separate weather/tyre dataset covers 2021–2023. Weather/tyre observations are displayed independently. The pit-stop prediction CSVs contain only `id` and `PitNextLap`; they do not contain a measured stop duration and are not used for duration analysis. The historical `pit_stops.csv` does contain measured duration data. Team attribution for stop events is made only when the `(raceId, driverId)` result key maps to exactly one constructor; ambiguous cases remain unassigned and are excluded from team comparisons only.
