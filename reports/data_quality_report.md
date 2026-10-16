# Data quality and coverage

This report is generated from the repository's local Kaggle files. Refresh the inventory with:

```powershell
.\.venv\Scripts\python.exe scripts\inspect_datasets.py
```

The checked-in inventory records the following source shapes:

- Historical championship source: 14 tables, including 1,125 races and 26,759 result entries; the actual local `races.csv` spans 1950–2024.
- Historical lap times: 589,081 lap rows.
- Historical pit stops: 11,371 measured stop events, covering 2011–2024.
- Weather/tyre source: 69,230 lap observations with 29 fields, covering 2021–2023.
- Pit-stop prediction source: two copies of a 188,165-row, two-column target file (`id`, `PitNextLap`); this does not contain measured pit-stop duration.

Counts above describe source files, not distinct Grands Prix or driver totals. The database builder checks actual required columns, unique primary keys and supported foreign-key references every time it builds. It refuses to replace the current database if these validations fail. Inspect the generated `reports/dataset_inventory.json` and successful build output for fresh exact counts.

Known limitations: weather/tyre observations and historical result tables have separate grains and have not been joined; pit-stop duration analyses use the measured historical `pit_stops.csv`, not the prediction target file. A pit-stop event is assigned to a constructor only when its source race/driver result key is unique; ambiguous assignments remain missing.
