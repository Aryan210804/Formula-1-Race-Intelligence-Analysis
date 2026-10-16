# Architecture

The repository keeps the existing FastF1 ingestion/transformation pipeline separate from the Kaggle historical-data analytics path.

1. `scripts/download_datasets.py` stages the three configured KaggleHub datasets without deleting cache files or overwriting differing local data.
2. `scripts/inspect_datasets.py` inventories supported files under `data/raw/` and writes JSON and text inspection reports.
3. `scripts/build_database.py` validates expected columns, primary-key uniqueness and source foreign-key values, then builds a temporary SQLite database. It replaces `data/processed/f1_intelligence.db` only after the transaction and SQLite foreign-key check succeed.
4. `f1_intelligence.analytics` reads SQLite tables and applies one-to-many-safe dimension joins plus reusable metrics.
5. `app.py` loads the database once per file modification time and renders interactive Streamlit/Plotly pages.
6. `scripts/export_tableau_data.py` writes independent grain-specific CSVs with a data dictionary for each extract.

Raw datasets are retained. The database build is reproducible and independent of the separate FastF1 `f1-transform` command. Historical result facts are joined to dimensions with many-to-one validation; weather/tyre observations stay at source lap grain and are not joined to historical race results. Stop-to-constructor comparisons use only unique `(raceId, driverId)` result mappings; ambiguous constructor assignments are reported as unavailable.
