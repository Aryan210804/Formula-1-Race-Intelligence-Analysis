"""Streamlit dashboard for the validated Formula 1 analytical database."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from f1_intelligence.analytics import (
    apply_filters,
    classify_finish,
    constructor_performance,
    country_race_counts,
    driver_performance,
    load_tables,
    pit_stop_summary,
    race_results,
)

ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "data" / "processed" / "f1_intelligence.db"
ACCENT = "#C8102E"
st.set_page_config(page_title="Formula 1 Race Intelligence", layout="wide")


@st.cache_data(show_spinner="Loading validated race data...")
def get_data(database_path: str, modified_ns: int):
    del modified_ns
    tables, missing = load_tables(Path(database_path))
    return tables, missing, race_results(tables)


def chart(fig) -> None:
    dark_mode = st.session_state.get("dark_mode", False)
    background = "#171A20" if dark_mode else "#FFFFFF"
    foreground = "#F1F3F5" if dark_mode else "#20252B"
    grid = "#3A414B" if dark_mode else "#E4E7EB"
    fig.update_layout(
        paper_bgcolor=background,
        plot_bgcolor=background,
        font={"color": foreground, "family": "Arial, sans-serif", "size": 13},
        title_font={"color": foreground, "size": 17},
        margin={"l": 45, "r": 24, "t": 55, "b": 45},
        xaxis={
            "color": foreground,
            "title_font": {"color": foreground},
            "tickfont": {"color": foreground},
            "gridcolor": grid,
            "zerolinecolor": grid,
        },
        yaxis={
            "color": foreground,
            "title_font": {"color": foreground},
            "tickfont": {"color": foreground},
            "gridcolor": grid,
            "zerolinecolor": grid,
        },
        legend={"font": {"color": foreground}},
    )
    st.plotly_chart(fig, width="stretch")


def display_table(frame: pd.DataFrame, filename: str, label: str = "Download filtered CSV") -> None:
    st.dataframe(frame, width="stretch", hide_index=True, height=min(520, max(150, 38 * (len(frame) + 1))))
    st.download_button(
        label,
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
    )


def main() -> None:
    with st.sidebar:
        dark_mode = st.toggle("Dark mode", key="dark_mode", value=False)
    if dark_mode:
        theme = {
            "background": "#101318",
            "surface": "#171A20",
            "sidebar": "#171A20",
            "text": "#F1F3F5",
            "muted": "#B6BEC8",
            "border": "#363D47",
            "grid_bg": "#171A20",
            "grid_header": "#222833",
        }
    else:
        theme = {
            "background": "#F5F6F7",
            "surface": "#FFFFFF",
            "sidebar": "#FFFFFF",
            "text": "#20252B",
            "muted": "#58616D",
            "border": "#D9DEE5",
            "grid_bg": "#FFFFFF",
            "grid_header": "#F0F2F5",
        }
    st.markdown(
        f"""
        <style>
        :root {{
            color-scheme: {"dark" if dark_mode else "light"};
            --f1-background: {theme["background"]};
            --f1-surface: {theme["surface"]};
            --f1-sidebar: {theme["sidebar"]};
            --f1-text: {theme["text"]};
            --f1-muted: {theme["muted"]};
            --f1-border: {theme["border"]};
        }}
        html, body, [data-testid="stAppViewContainer"], .stApp {{
            background-color: var(--f1-background) !important;
            color: var(--f1-text) !important;
            font-size: 16px !important;
        }}
        [data-testid="stHeader"] {{
            background-color: var(--f1-background) !important;
        }}
        [data-testid="stAppDeployButton"] {{
            display: none !important;
        }}
        [data-testid="stSidebar"] {{
            background-color: var(--f1-sidebar) !important;
            border-right: 1px solid var(--f1-border);
            width: 285px !important;
            min-width: 285px !important;
            flex: 0 0 285px !important;
        }}
        [data-testid="stSidebar"] * {{
            color: var(--f1-text);
            font-size: 15px;
        }}
        .stApp h1, .stApp h2, .stApp h3, .stApp h4 {{
            color: var(--f1-text) !important;
            line-height: 1.3;
        }}
        .stApp h1 {{ font-size: 2rem !important; }}
        .stApp h2 {{ font-size: 1.55rem !important; }}
        .stApp p, .stApp label, .stApp [data-testid="stCaptionContainer"] {{
            color: var(--f1-muted) !important;
            font-size: 15px;
            line-height: 1.5;
        }}
        [data-testid="stMetric"] {{
            background-color: var(--f1-surface);
            border: 1px solid var(--f1-border);
            border-top: 3px solid {ACCENT};
            padding: 18px;
        }}
        [data-testid="stMetricLabel"], [data-testid="stMetricValue"] {{
            color: var(--f1-text) !important;
        }}
        [data-testid="stDataFrame"] {{
            --gdg-bg-cell: {theme["grid_bg"]};
            --gdg-bg-cell-medium: {theme["grid_header"]};
            --gdg-bg-header: {theme["grid_header"]};
            --gdg-text-dark: {theme["text"]};
            --gdg-text-medium: {theme["muted"]};
            --gdg-text-light: {theme["muted"]};
            --gdg-text-header: {theme["text"]};
            --gdg-border-color: {theme["border"]};
            --gdg-accent-color: {ACCENT};
            --gdg-font-size: 14px;
            border: 1px solid var(--f1-border);
            color: var(--f1-text);
        }}
        [data-testid="stDataFrame"] canvas {{
            color-scheme: {"dark" if dark_mode else "light"};
            filter: {"invert(1) hue-rotate(180deg)" if dark_mode else "none"};
        }}
        [data-baseweb="select"] > div, [data-baseweb="input"] > div,
        [data-baseweb="textarea"] > div, [data-testid="stDateInput"] input {{
            background-color: var(--f1-surface);
            color: var(--f1-text);
            border-color: var(--f1-border);
        }}
        [data-baseweb="popover"], [data-baseweb="menu"] {{
            background-color: var(--f1-surface);
            color: var(--f1-text);
        }}
        [data-testid="stDownloadButton"] button, [data-testid="stButton"] button {{
            color: var(--f1-text);
            background-color: var(--f1-surface);
            border-color: var(--f1-border);
        }}
        [data-testid="stDownloadButton"] button:hover,
        [data-testid="stButton"] button:hover {{
            border-color: {ACCENT};
            color: {ACCENT};
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("Formula 1 Race Intelligence")
    st.caption("Historical championship results and locally available strategy observations.")
    if not DATABASE.is_file():
        st.warning("The analytical database has not been built yet.")
        st.code(r".\.venv\Scripts\python.exe scripts\build_database.py")
        st.stop()
    try:
        tables, missing, results = get_data(str(DATABASE), DATABASE.stat().st_mtime_ns)
    except (OSError, ValueError, KeyError) as exc:
        st.error(f"Unable to load the analytical database: {exc}")
        st.stop()
    if results.empty:
        st.info("No race results are available in the database.")
        st.stop()

    years_available = sorted(int(year) for year in results["year"].dropna().unique())
    if not years_available:
        st.warning("The database has no year values to filter.")
        st.stop()
    with st.sidebar:
        st.header("Explore")
        page = st.radio(
            "Dashboard page",
            [
                "Executive Overview",
                "Driver Performance",
                "Constructor Championship",
                "Tyre and Circuit Strategy",
                "Global F1",
                "Reliability and DNF",
                "Pit Stops and Race Pace",
            ],
        )
        year_range = st.slider(
            "Season range",
            min_value=years_available[0],
            max_value=years_available[-1],
            value=(years_available[0], years_available[-1]),
        )
        driver_filter = st.multiselect("Driver", sorted(results["driver"].dropna().unique()))
        constructor_filter = st.multiselect(
            "Constructor", sorted(results["constructor"].dropna().unique())
        )
        country_filter = st.multiselect(
            "Host country", sorted(results["country"].dropna().unique())
        )
        circuit_filter = st.multiselect("Circuit", sorted(results["circuit"].dropna().unique()))
        status_filter = st.multiselect("Race status", sorted(results["status"].dropna().unique()))

    filtered = apply_filters(
        results,
        years=year_range,
        drivers=driver_filter,
        constructors=constructor_filter,
        countries=country_filter,
        statuses=status_filter,
        circuits=circuit_filter,
    )
    page_titles = {
        "Executive Overview": "Executive Overview",
        "Driver Performance": "Driver Performance",
        "Constructor Championship": "Constructor Championship",
        "Tyre and Circuit Strategy": "Tyre and Circuit Strategy",
        "Global F1": "Global F1",
        "Reliability and DNF": "Reliability and DNF",
        "Pit Stops and Race Pace": "Pit Stops and Race Pace",
    }
    st.header(page_titles[page])
    st.caption(f"Selected period: {year_range[0]}–{year_range[1]}. Each result row is one driver entry.")
    if filtered.empty and page not in {"Tyre and Circuit Strategy", "Constructor Championship"}:
        st.info("No race entries match the selected filters. Adjust the sidebar selections.")
        st.stop()

    if page == "Executive Overview":
        races_count = int(filtered["raceId"].nunique())
        drivers_count = int(filtered["driverId"].nunique())
        constructors_count = int(filtered["constructorId"].nunique())
        podiums = int(filtered["finish_position"].between(1, 3).sum())
        cards = st.columns(4)
        for column, label, value in zip(
            cards,
            ("Grand Prix", "Drivers", "Constructors", "Podium finishes"),
            (races_count, drivers_count, constructors_count, podiums),
        ):
            column.metric(label, f"{value:,}")
        st.caption("Podiums count result entries at positions 1–3; this can count several entries per race.")
        trends = (
            filtered.groupby("year", as_index=False)
            .agg(races=("raceId", "nunique"), points=("points", "sum"))
        )
        chart(px.line(trends, x="year", y="races", markers=True, title="Grand Prix coverage by season"))
        leaders = driver_performance(filtered).head(15)
        chart(px.bar(leaders, x="points", y="driver", orientation="h", title="Driver points in selected data"))
        leaders = leaders.sort_values("points")
        display_table(leaders, "driver_leaderboard.csv")
        st.subheader("Data coverage")
        coverage = pd.DataFrame(
            [{"Table": name, "Rows": len(frame)} for name, frame in tables.items()]
        )
        st.dataframe(coverage, width="stretch", hide_index=True)
        st.caption(
            "Tyre/weather laps come from a separate source and are not joined to historical results. "
            f"Unavailable optional tables: {', '.join(missing) if missing else 'none'}."
        )

    elif page == "Driver Performance":
        leaders = driver_performance(filtered)
        if leaders.empty:
            st.info("No driver data matches these filters.")
            return
        chart(px.bar(leaders.head(25), x="points", y="driver", orientation="h", title="Points by driver"))
        st.subheader("Cumulative points")
        chosen = driver_filter or leaders.head(5)["driver"].tolist()
        progression = filtered[filtered["driver"].isin(chosen)].sort_values(["date", "round"])
        progression = progression.assign(
            cumulative_points=progression.groupby("driver")["points"].cumsum()
        )
        chart(px.line(progression, x="date", y="cumulative_points", color="driver", title="Race-entry cumulative points"))
        chart(px.histogram(filtered, x="finish_position", nbins=20, title="Finishing-position distribution"))
        display_table(leaders, "driver_performance.csv")

    elif page == "Constructor Championship":
        standings = constructor_performance(tables)
        if standings.empty:
            st.info("Official constructor championship points are unavailable.")
            return
        standings = standings[standings["year"].between(*year_range)]
        if constructor_filter:
            standings = standings[standings["constructor"].isin(constructor_filter)]
        if standings.empty:
            st.info("No constructor standings match the selected filters.")
            return
        chart(px.line(standings, x="year", y="points", color="constructor", markers=True, title="Official constructor points by season"))
        season = st.selectbox("Season standings", sorted(standings["year"].unique(), reverse=True))
        current = standings[standings["year"] == season].sort_values("points", ascending=False)
        chart(px.bar(current, x="points", y="constructor", orientation="h", title=f"Constructor points — {season}"))
        display_table(current, f"constructor_standings_{season}.csv")
        st.caption(
            "Points are summed from constructor_results. Driver, host-country, circuit and status "
            "filters do not apply to official full-season constructor totals."
        )

    elif page == "Tyre and Circuit Strategy":
        tyre = tables.get("weather_tyre", pd.DataFrame())
        if tyre.empty:
            st.info("Tyre/weather analysis unavailable: the weather_tyre source table is missing.")
            return
        tyre = tyre[tyre["year"].between(*year_range)].copy()
        compounds = sorted(tyre["Compound"].dropna().unique())
        compound_filter = st.multiselect("Tyre compound", compounds)
        if compound_filter:
            tyre = tyre[tyre["Compound"].isin(compound_filter)]
        if tyre.empty:
            st.info("No tyre/weather observations match the selected filters.")
            return
        summary = (
            tyre.groupby(["year", "Compound"], dropna=False, as_index=False)
            .agg(laps=("lap", "size"), mean_lap_ms=("milliseconds", "mean"))
        )
        chart(px.bar(summary, x="Compound", y="laps", color="year", barmode="group", title="Observed laps by compound"))
        chart(px.scatter(summary, x="laps", y="mean_lap_ms", color="Compound", size="laps", title="Sample size and mean lap time"))
        st.caption(
            f"{len(tyre):,} observations shown. These records are lap-grain source observations; "
            "no result-level join is asserted and no causal effect is inferred."
        )
        display_table(summary, "tyre_compound_summary.csv")

    elif page == "Global F1":
        selected_races = tables["races"][tables["races"]["year"].between(*year_range)]
        country_counts = country_race_counts(
            {**tables, "races": selected_races}
        )
        if country_filter:
            country_counts = country_counts[country_counts["country"].isin(country_filter)]
        chart(px.bar(country_counts.head(25), x="races", y="country", orientation="h", title="Unique Grands Prix by host country"))
        nationalities = filtered[["driverId", "nationality"]].drop_duplicates()
        nationality_counts = nationalities.groupby("nationality", as_index=False).agg(drivers=("driverId", "nunique")).sort_values("drivers", ascending=False)
        chart(px.bar(nationality_counts.head(20), x="drivers", y="nationality", orientation="h", title="Driver nationalities in filtered entries"))
        podiums = filtered[filtered["finish_position"].between(1, 3)]
        podium_nationalities = podiums.groupby("nationality", as_index=False).agg(podium_finishes=("driverId", "size")).sort_values("podium_finishes", ascending=False)
        display_table(podium_nationalities, "podiums_by_nationality.csv")
        st.caption(
            "Nationality is the driver nationality field, not the Grand Prix host country. "
            "The season range applies to race and driver-entry measures."
        )

    elif page == "Reliability and DNF":
        reliability = filtered.assign(classified_finish=classify_finish(filtered["status"]))
        totals = reliability.groupby("year", as_index=False).agg(
            entries=("raceId", "size"),
            classified_finishes=("classified_finish", "sum"),
        )
        totals["non_finishes"] = totals["entries"] - totals["classified_finishes"]
        totals["completion_rate_pct"] = 100 * totals["classified_finishes"] / totals["entries"]
        chart(px.bar(totals, x="year", y=["classified_finishes", "non_finishes"], barmode="stack", title="Race-entry classifications"))
        chart(px.bar(filtered.groupby("status", as_index=False).agg(entries=("raceId", "size")).sort_values("entries", ascending=False).head(25), x="entries", y="status", orientation="h", title="Official status labels"))
        st.caption("Completion rate denominator is race entries. 'Finished' and '+N Lap(s)' count as classified finishes.")
        display_table(totals, "reliability_by_season.csv")

    else:
        pit = pit_stop_summary(tables)
        if pit.empty:
            st.info("Actual pit-stop duration analysis is unavailable: pit_stops is missing.")
            return
        pit = pit[pit["year"].between(*year_range)]
        if driver_filter:
            selected_ids = filtered["driverId"].unique()
            pit = pit[pit["driverId"].isin(selected_ids)]
        if constructor_filter:
            pit = pit[pit["constructor"].isin(constructor_filter)]
        if pit.empty:
            st.info("No pit stops match the selected seasons and drivers.")
            return
        by_year = pit.groupby("year", as_index=False).agg(
            stops=("stop", "size"),
            mean_duration_ms=("duration_ms", "mean"),
            median_duration_ms=("duration_ms", "median"),
        )
        chart(px.line(by_year, x="year", y="stops", markers=True, title="Recorded pit-stop events"))
        chart(px.box(pit, x="year", y="duration_ms", title="Recorded pit-stop durations (milliseconds)"))
        driver_stops = (
            pit.groupby("driver", as_index=False)
            .agg(stops=("stop", "size"), median_duration_ms=("duration_ms", "median"))
            .sort_values("stops", ascending=False)
            .head(15)
        )
        chart(
            px.bar(
                driver_stops,
                x="median_duration_ms",
                y="driver",
                orientation="h",
                title="Median stop duration by driver (top 15 by recorded stops)",
            )
        )
        team_stops = pit.dropna(subset=["constructor"]).groupby(
            "constructor", as_index=False
        ).agg(stops=("stop", "size"), median_duration_ms=("duration_ms", "median"))
        if not team_stops.empty:
            chart(
                px.bar(
                    team_stops.sort_values("stops", ascending=False).head(15),
                    x="median_duration_ms",
                    y="constructor",
                    orientation="h",
                    title="Median stop duration by team (unique race-entry links only)",
                )
            )
        ambiguous_stops = int(pit["constructor"].isna().sum())
        st.caption(
            "Pit-stop duration is the source milliseconds field. Driver and season filters apply. "
            f"Team attribution is unavailable for {ambiguous_stops:,} stops because the source "
            "race/driver key is ambiguous or unmatched; those events are excluded only from team comparisons."
        )
        display_table(by_year, "pit_stop_summary.csv")
        laps = tables.get("lap_times", pd.DataFrame())
        if not laps.empty:
            laps = laps.merge(tables["races"][["raceId", "year"]], on="raceId", validate="many_to_one")
            laps = laps[laps["year"].between(*year_range)]
            if not laps.empty:
                lap_year = laps.groupby("year", as_index=False).agg(mean_lap_ms=("milliseconds", "mean"))
                chart(px.line(lap_year, x="year", y="mean_lap_ms", markers=True, title="Mean recorded lap time by season"))


if __name__ == "__main__":
    main()
