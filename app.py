import base64
import html
import importlib
from pathlib import Path

import plotly.graph_objects as go
import pandas as pd
import streamlit as st

import league_analytics

importlib.reload(league_analytics)

from db import DEFAULT_DB_PATH
from league_analytics import (
    best_draft_picks,
    best_kickers,
    biggest_upsets,
    biggest_wins,
    current_season_highlights,
    get_data_summary,
    head_to_head,
    highest_scoring_teams,
    highest_scoring_losses,
    list_team_owners,
    lowest_scoring_teams,
    lowest_scoring_wins,
    most_bench_points,
    narrowest_wins,
    player_usage,
    points_for_against_chart,
    group_team_points,
    group_owner_points,
    group_team_win_records,
    team_points_for_against,
    team_win_records,
    worst_lineup_decisions,
)

NO_TROPHY_VIDEO = Path(__file__).parent / "assets" / "gif" / "no_trophy.mp4"

WIN_COLUMNS = [
    "year",
    "week",
    "winner",
    "loser",
    "winner_score",
    "loser_score",
    "margin",
    "home_team",
    "away_team",
]


def format_column_title(column: str) -> str:
    return " ".join(part.capitalize() for part in column.split("_"))


def display_table(df: pd.DataFrame) -> None:
    display_df = df.copy()
    display_df.columns = [format_column_title(col) for col in display_df.columns]
    st.dataframe(display_df, width="stretch", hide_index=True)


STAT_SECTIONS = [
    "Points scored vs conceded",
    "Win percentage report",
    "Head-to-head records",
    "Highest scoring team ever",
    "Biggest upsets",
    "Biggest wins",
    "Narrowest wins",
    "Lowest scores",
    "Lowest scoring wins",
    "Highest scoring losses",
    "Best draft picks",
    "Worst lineup decisions",
    "Most points left on the bench",
    "All-time player usage",
    "Best kickers",
]

SECTION_DETAILS = {
    "Points scored vs conceded": (
        "Starter totals only (bench and IR excluded). "
        "Compare points scored and conceded by team and season."
    ),
    "Highest scoring team ever": (
        "Single-week starter totals (bench and IR excluded)."
    ),
    "Biggest upsets": (
        "Wins by the lower-projected starter lineup (bench and IR excluded)."
    ),
    "Biggest wins": (
        "Largest starter margin of victory (bench and IR excluded)."
    ),
    "Narrowest wins": (
        "Closest starter victories, excluding ties (bench and IR excluded)."
    ),
    "Lowest scores": (
        "Lowest single-week starter totals (bench and IR excluded)."
    ),
    "Lowest scoring wins": (
        "Victories with the fewest starter points (bench and IR excluded)."
    ),
    "Highest scoring losses": (
        "Losses with the most starter points (bench and IR excluded)."
    ),
    "Best draft picks": (
        "Most starter points from drafted players (bench and IR excluded)."
    ),
    "Worst lineup decisions": (
        "Bench player outscored a swappable starter: same position, "
        "or a benched RB/WR/TE vs a FLEX spot."
    ),
    "Most points left on the bench": "Total bench points in a single week.",
    "All-time player usage": "Non-bench appearances and total fantasy points.",
    "Best kickers": "Total fantasy points when started at kicker.",
    "Head-to-head records": (
        "Records by owner using starter scores (bench and IR excluded)."
    ),
    "Win percentage report": (
        "Win-loss record and win percentage by team using starter scores "
        "(bench and IR excluded). Ties are excluded."
    ),
}


def inject_global_styles() -> None:
    # Must run on every rerun: Streamlit drops elements the script no longer emits,
    # so guarding this behind session state would strip the CSS on the next rerun.
    #
    # Colours inherit from Streamlit's active theme rather than being hardcoded,
    # because prefers-color-scheme follows the OS and not the in-app theme toggle.
    st.markdown(
        """
        <style>
        .report-banner {
            border: 1px solid rgba(255, 75, 75, 0.28);
            border-left: 4px solid #ff4b4b;
            border-radius: 0.65rem;
            padding: 1rem 1.25rem 1.1rem;
            margin: 0 0 1.5rem 0;
            background: linear-gradient(
                135deg,
                rgba(255, 75, 75, 0.09) 0%,
                rgba(255, 75, 75, 0.03) 55%,
                rgba(151, 166, 195, 0.05) 100%
            );
            color: inherit;
        }
        .report-banner-meta {
            font-size: 0.78rem;
            font-weight: 600;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            margin-bottom: 0.35rem;
            color: inherit;
            opacity: 0.75;
        }
        .report-banner-title {
            font-size: 1.55rem;
            font-weight: 700;
            line-height: 1.25;
            margin: 0 0 0.45rem 0;
            color: inherit;
        }
        .report-banner-desc {
            font-size: 0.92rem;
            line-height: 1.45;
            margin: 0;
            color: inherit;
        }
        .ticker-wrap {
            display: flex;
            align-items: stretch;
            overflow: hidden;
            border: 1px solid rgba(255, 75, 75, 0.28);
            border-radius: 0.65rem;
            margin: 0 0 1.25rem 0;
            background: linear-gradient(
                90deg,
                rgba(255, 75, 75, 0.09) 0%,
                rgba(151, 166, 195, 0.04) 100%
            );
            color: inherit;
        }
        .ticker-label {
            flex: 0 0 auto;
            display: flex;
            align-items: center;
            padding: 0.5rem 0.9rem;
            background: #ff4b4b;
            color: #ffffff;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            white-space: nowrap;
        }
        .ticker-viewport {
            flex: 1 1 auto;
            overflow: hidden;
            padding: 0.5rem 0;
            -webkit-mask-image: linear-gradient(
                90deg, transparent 0, #000 1.5rem,
                #000 calc(100% - 1.5rem), transparent 100%
            );
            mask-image: linear-gradient(
                90deg, transparent 0, #000 1.5rem,
                #000 calc(100% - 1.5rem), transparent 100%
            );
        }
        .ticker-track {
            display: inline-flex;
            white-space: nowrap;
            will-change: transform;
            animation-name: ticker-scroll;
            animation-timing-function: linear;
            animation-iteration-count: infinite;
        }
        .ticker-wrap:hover .ticker-track {
            animation-play-state: paused;
        }
        .ticker-item {
            display: inline-flex;
            align-items: baseline;
            gap: 0.45rem;
            padding: 0 1.6rem;
            font-size: 0.9rem;
            color: inherit;
        }
        .ticker-rank {
            font-weight: 700;
            color: #ff4b4b;
        }
        .ticker-report {
            font-size: 0.72rem;
            font-weight: 600;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            opacity: 0.7;
        }
        .ticker-week {
            font-size: 0.78rem;
            opacity: 0.6;
        }
        @keyframes ticker-scroll {
            from { transform: translateX(0); }
            to { transform: translateX(-50%); }
        }
        @media (prefers-reduced-motion: reduce) {
            .ticker-track { animation: none; }
            .ticker-viewport { overflow-x: auto; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def _season_highlights(season: int, db_signature: float) -> list[dict]:
    # db_signature busts the cache whenever an import script rewrites the database.
    return current_season_highlights(season=season)


def render_season_ticker(seasons: list[int]) -> None:
    try:
        db_signature = DEFAULT_DB_PATH.stat().st_mtime
    except OSError:
        db_signature = 0.0

    # Falls back to the previous season so the ticker isn't blank in the preseason.
    season, highlights = None, []
    for candidate in seasons[:2]:
        highlights = _season_highlights(candidate, db_signature)
        if highlights:
            season = candidate
            break

    if not highlights:
        return

    items = "".join(
        f'<span class="ticker-item">'
        f'<span class="ticker-rank">#{item["rank"]}</span>'
        f'<span class="ticker-report">{html.escape(item["report"])}</span>'
        f'<span>{html.escape(item["text"])}</span>'
        f'<span class="ticker-week">Wk {item["week"]}</span>'
        f"</span>"
        for item in highlights
    )

    # The track holds two copies so the -50% keyframe loops seamlessly.
    # Rendered width is roughly 9px per character; 0.09 targets about 100px/second.
    characters = sum(len(item["text"]) + len(item["report"]) for item in highlights)
    duration = max(20, round(characters * 0.09))

    st.markdown(
        f"""
        <div class="ticker-wrap" title="Hover to pause">
            <div class="ticker-label">{season} all-time entries</div>
            <div class="ticker-viewport">
                <div class="ticker-track" style="animation-duration: {duration}s">
                    {items}{items}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_report_banner(
    section: str,
    year_filter: int | None,
    game_type_label: str,
) -> None:
    year_label = "All time" if year_filter is None else str(year_filter)
    details = SECTION_DETAILS.get(section, "")

    st.markdown(
        f"""
        <div class="report-banner">
            <div class="report-banner-meta">
                {html.escape(year_label)} · {html.escape(game_type_label)}
            </div>
            <div class="report-banner-title">{html.escape(section)}</div>
            <p class="report-banner-desc">{html.escape(details)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_header(title: str, details: str) -> None:
    return


def render_points_metric_chart(
    chart_df,
    x_col: str,
    x_label: str,
) -> None:
    fig = go.Figure()

    if x_col == "metric":
        for _, row in chart_df.iterrows():
            fig.add_trace(
                go.Bar(
                    name=row["metric"],
                    x=[row["metric"]],
                    y=[row["points"]],
                    hovertemplate=(
                        f"{row['metric']}<br>Points: %{{y:,.2f}}<extra></extra>"
                    ),
                )
            )
    else:
        if x_col == "label":
            x_order = (
                chart_df.groupby("label")["points"]
                .sum()
                .sort_values(ascending=False)
                .index.tolist()
            )
        else:
            x_order = sorted(chart_df[x_col].unique())

        for metric in ("Points scored", "Points conceded"):
            subset = chart_df[chart_df["metric"] == metric]
            fig.add_trace(
                go.Bar(
                    name=metric,
                    x=subset[x_col],
                    y=subset["points"],
                    hovertemplate=(
                        f"{x_label}: %{{x}}<br>{metric}: %{{y:,.2f}}<extra></extra>"
                    ),
                )
            )

        fig.update_layout(
            xaxis={
                "title": x_label,
                "categoryorder": "array",
                "categoryarray": x_order,
            }
        )

    fig.update_layout(
        barmode="group",
        height=420,
        yaxis_title="Points",
        legend_title_text="",
        margin={"l": 20, "r": 20, "t": 20, "b": 20},
    )
    if x_col == "metric":
        fig.update_layout(xaxis_title="")

    st.caption("Click **Points scored** or **Points conceded** in the legend to filter.")
    st.plotly_chart(fig, width="stretch")


@st.cache_data
def _no_trophy_video_data_uri() -> str:
    encoded = base64.b64encode(NO_TROPHY_VIDEO.read_bytes()).decode("ascii")
    return f"data:video/mp4;base64,{encoded}"


def render_scored_metric_with_hover_video(
    label: str,
    value: str,
    caption: str,
    video_data_uri: str,
) -> None:
    safe_label = html.escape(label)
    safe_value = html.escape(value)
    safe_caption = html.escape(caption)
    st.iframe(
        f"""
        <style>
            .scored-metric-wrap {{
                position: relative;
                font-family: "Source Sans Pro", sans-serif;
                cursor: pointer;
            }}
            .scored-metric-label {{
                color: rgb(115, 115, 115);
                font-size: 0.875rem;
                margin-bottom: 0.25rem;
            }}
            .scored-metric-value {{
                color: rgb(250, 250, 250);
                font-size: 2.25rem;
                font-weight: 600;
                line-height: 1.2;
            }}
            .scored-metric-caption {{
                color: rgb(115, 115, 115);
                font-size: 0.875rem;
                margin-top: 0.35rem;
            }}
            .scored-metric-backdrop,
            .scored-metric-modal {{
                display: none;
            }}
            .scored-metric-wrap:hover .scored-metric-backdrop,
            .scored-metric-wrap:hover .scored-metric-modal {{
                display: block;
            }}
            .scored-metric-backdrop {{
                position: fixed;
                inset: 0;
                background: rgba(0, 0, 0, 0.75);
                z-index: 999998;
            }}
            .scored-metric-modal {{
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                z-index: 999999;
                background: rgb(38, 39, 48);
                border-radius: 12px;
                padding: 16px;
                box-shadow: 0 16px 48px rgba(0, 0, 0, 0.45);
            }}
            .scored-metric-modal video {{
                display: block;
                max-width: min(420px, 80vw);
                max-height: 70vh;
                border-radius: 8px;
            }}
            @media (prefers-color-scheme: light) {{
                .scored-metric-value {{
                    color: rgb(38, 39, 48);
                }}
            }}
        </style>
        <div
            class="scored-metric-wrap"
            onmouseenter="this.querySelector('video').play()"
            onmouseleave="(() => {{ const video = this.querySelector('video'); video.pause(); video.currentTime = 0; }})()"
        >
            <div class="scored-metric-label">{safe_label}</div>
            <div class="scored-metric-value">{safe_value}</div>
            <div class="scored-metric-caption">{safe_caption}</div>
            <div class="scored-metric-backdrop"></div>
            <div class="scored-metric-modal">
                <video autoplay loop muted playsinline>
                    <source src="{video_data_uri}" type="video/mp4">
                </video>
            </div>
        </div>
        """,
        height=130,
    )


def render_points_section(
    year_filter: int | None,
    game_type_filter: str,
    owners: list[str],
    points_view: str,
    points_group_by: str,
    selected_owner: str | None,
) -> None:
    render_section_header(
        "Points scored vs conceded",
        SECTION_DETAILS["Points scored vs conceded"],
    )

    team_points = team_points_for_against(
        year=year_filter, game_type=game_type_filter
    )
    if team_points.empty:
        st.info("No points data available for this filter.")
        return

    if selected_owner is not None:
        team_points = team_points[team_points["team_owner"] == selected_owner]

    by_season, overall = points_for_against_chart(
        year=year_filter,
        team_owner=selected_owner,
        game_type=game_type_filter,
    )

    if team_points.empty:
        st.info("No points data available for this filter.")
        return

    metric_col1, metric_col2, metric_col3 = st.columns(3)

    if points_view == "All teams":
        if points_group_by == "Team owner":
            per_team_totals = group_owner_points(team_points, by_year=False)
        else:
            if year_filter is None:
                per_team_totals = group_team_points(team_points, by_year=False)
            else:
                per_team_totals = team_points

        year_label = "All time" if year_filter is None else str(year_filter)
        most_scored = per_team_totals.loc[per_team_totals["points_for"].idxmax()]
        most_conceded = per_team_totals.loc[per_team_totals["points_against"].idxmax()]
        best_diff = per_team_totals.loc[per_team_totals["point_diff"].idxmax()]

        def metric_caption(row) -> str:
            if points_group_by == "Team owner":
                return f"{row['team_owner']} · {year_label}"
            return f"{row['team_name']} · {row['team_owner']} · {year_label}"

        with metric_col1:
            render_scored_metric_with_hover_video(
                "Most points scored",
                f"{most_scored['points_for']:,.2f}",
                metric_caption(most_scored),
                _no_trophy_video_data_uri(),
            )
        with metric_col2:
            metric_col2.metric(
                "Most points conceded",
                f"{most_conceded['points_against']:,.2f}",
            )
            metric_col2.caption(metric_caption(most_conceded))
        with metric_col3:
            metric_col3.metric(
                "Best point differential",
                f"{best_diff['point_diff']:+,.2f}",
            )
            metric_col3.caption(metric_caption(best_diff))
    else:
        metric_col1.metric("Points scored", f"{overall.iloc[0]['points_for']:,.2f}")
        metric_col2.metric("Points conceded", f"{overall.iloc[0]['points_against']:,.2f}")
        metric_col3.metric("Point differential", f"{overall.iloc[0]['point_diff']:+,.2f}")

    if points_view == "All teams":
        if points_group_by == "Team owner":
            chart_data = group_owner_points(team_points, by_year=False).sort_values(
                "points_for", ascending=False
            )
            chart_data["label"] = chart_data["team_owner"]
            x_label = (
                "Owner (all-time)"
                if year_filter is None
                else f"Owner ({year_filter})"
            )
        elif year_filter is None:
            chart_data = group_team_points(team_points, by_year=False).sort_values(
                "points_for", ascending=False
            )
            chart_data["label"] = chart_data["team_name"]
            x_label = "Team (all-time)"
        else:
            chart_data = team_points.sort_values("points_for", ascending=False)
            chart_data["label"] = chart_data["team_name"]
            x_label = f"Team ({year_filter})"

        chart_df = chart_data.melt(
            id_vars="label",
            value_vars=["points_for", "points_against"],
            var_name="metric",
            value_name="points",
        )
        chart_df["metric"] = chart_df["metric"].map(
            {
                "points_for": "Points scored",
                "points_against": "Points conceded",
            }
        )
        render_points_metric_chart(chart_df, "label", x_label)
    elif year_filter is None and not by_season.empty:
        chart_df = by_season.melt(
            id_vars="year",
            value_vars=["points_for", "points_against"],
            var_name="metric",
            value_name="points",
        )
        chart_df["metric"] = chart_df["metric"].map(
            {
                "points_for": "Points scored",
                "points_against": "Points conceded",
            }
        )
        render_points_metric_chart(chart_df, "year", "Season")
    else:
        chart_df = overall.melt(
            value_vars=["points_for", "points_against"],
            var_name="metric",
            value_name="points",
        )
        chart_df["metric"] = chart_df["metric"].map(
            {
                "points_for": "Points scored",
                "points_against": "Points conceded",
            }
        )
        render_points_metric_chart(chart_df, "metric", "")

    if points_view == "All teams":
        if points_group_by == "Team owner":
            st.markdown("**By owner and season**")
            display_points = group_owner_points(team_points, by_year=True)[
                ["year", "team_owner", "points_for", "points_against", "point_diff"]
            ]
        else:
            st.markdown("**By team and season**")
            display_points = team_points[
                ["year", "team_name", "team_owner", "points_for", "points_against", "point_diff"]
            ]
    else:
        st.markdown("**By season**")
        if year_filter is None and not by_season.empty:
            display_points = by_season.copy()
            display_points["point_diff"] = (
                display_points["points_for"] - display_points["points_against"]
            )
        else:
            display_points = team_points[
                ["year", "team_name", "points_for", "points_against", "point_diff"]
            ]
    display_table(display_points)


def render_highest_scoring_teams(
    year_filter: int | None,
    game_type_filter: str,
) -> None:
    render_section_header(
        "Highest scoring team ever",
        SECTION_DETAILS["Highest scoring team ever"],
    )
    scores = highest_scoring_teams(year=year_filter, game_type=game_type_filter)
    if scores.empty:
        st.info("No box score data available for this filter.")
    else:
        display_table(scores)


def render_biggest_upsets(
    year_filter: int | None,
    game_type_filter: str,
) -> None:
    render_section_header("Biggest upsets", SECTION_DETAILS["Biggest upsets"])
    upsets = biggest_upsets(year=year_filter, game_type=game_type_filter)
    if upsets.empty:
        st.info("No upset data available for this filter.")
    else:
        display = upsets[
            [
                "year",
                "week",
                "winner",
                "home_team",
                "away_team",
                "home_score",
                "away_score",
                "home_projected",
                "away_projected",
                "upset_margin",
            ]
        ]
        display_table(display)


def render_biggest_wins(
    year_filter: int | None,
    game_type_filter: str,
) -> None:
    render_section_header("Biggest wins", SECTION_DETAILS["Biggest wins"])
    big_wins = biggest_wins(year=year_filter, game_type=game_type_filter)
    if big_wins.empty:
        st.info("No win data available for this filter.")
    else:
        display_table(big_wins[WIN_COLUMNS])


def render_narrowest_wins(
    year_filter: int | None,
    game_type_filter: str,
) -> None:
    render_section_header("Narrowest wins", SECTION_DETAILS["Narrowest wins"])
    close_wins = narrowest_wins(year=year_filter, game_type=game_type_filter)
    if close_wins.empty:
        st.info("No win data available for this filter.")
    else:
        display_table(close_wins[WIN_COLUMNS])


def render_lowest_scores(
    year_filter: int | None,
    game_type_filter: str,
) -> None:
    render_section_header("Lowest scores", SECTION_DETAILS["Lowest scores"])
    low_scores = lowest_scoring_teams(year=year_filter, game_type=game_type_filter)
    if low_scores.empty:
        st.info("No score data available for this filter.")
    else:
        display_table(low_scores)


def render_lowest_scoring_wins(
    year_filter: int | None,
    game_type_filter: str,
) -> None:
    render_section_header(
        "Lowest scoring wins",
        SECTION_DETAILS["Lowest scoring wins"],
    )
    low_wins = lowest_scoring_wins(year=year_filter, game_type=game_type_filter)
    if low_wins.empty:
        st.info("No win data available for this filter.")
    else:
        display_table(low_wins[WIN_COLUMNS])


def render_highest_scoring_losses(
    year_filter: int | None,
    game_type_filter: str,
) -> None:
    render_section_header(
        "Highest scoring losses",
        SECTION_DETAILS["Highest scoring losses"],
    )
    high_losses = highest_scoring_losses(year=year_filter, game_type=game_type_filter)
    if high_losses.empty:
        st.info("No loss data available for this filter.")
    else:
        display_table(high_losses[WIN_COLUMNS])


def render_best_draft_picks(
    year_filter: int | None,
    game_type_filter: str,
    summary: dict,
) -> None:
    render_section_header("Best draft picks", SECTION_DETAILS["Best draft picks"])
    if summary["draft_picks"] == 0:
        st.info("No draft data loaded yet. Run `python get_draft.py`.")
        return

    drafts = best_draft_picks(year=year_filter, game_type=game_type_filter)
    if drafts.empty:
        st.info("No draft pick data for this filter.")
    else:
        display_table(drafts)


def render_worst_lineup_decisions(
    year_filter: int | None,
    game_type_filter: str,
) -> None:
    render_section_header(
        "Worst lineup decisions",
        SECTION_DETAILS["Worst lineup decisions"],
    )
    decisions = worst_lineup_decisions(year=year_filter, game_type=game_type_filter)
    if decisions.empty:
        st.info("No lineup decision data for this filter.")
    else:
        display_table(decisions)


def render_most_bench_points(
    year_filter: int | None,
    game_type_filter: str,
) -> None:
    render_section_header(
        "Most points left on the bench",
        SECTION_DETAILS["Most points left on the bench"],
    )
    bench = most_bench_points(year=year_filter, game_type=game_type_filter)
    if bench.empty:
        st.info("No bench data for this filter.")
    else:
        display_table(bench)


def render_player_usage(
    year_filter: int | None,
    game_type_filter: str,
) -> None:
    render_section_header(
        "All-time player usage",
        SECTION_DETAILS["All-time player usage"],
    )
    usage = player_usage(year=year_filter, game_type=game_type_filter)
    if usage.empty:
        st.info("No player usage data for this filter.")
    else:
        display_table(usage)


def render_best_kickers(
    year_filter: int | None,
    game_type_filter: str,
) -> None:
    render_section_header("Best kickers", SECTION_DETAILS["Best kickers"])
    kickers = best_kickers(year=year_filter, game_type=game_type_filter)
    if kickers.empty:
        st.info("No kicker data for this filter.")
    else:
        display_table(kickers)


def render_head_to_head(
    year_filter: int | None,
    game_type_filter: str,
) -> None:
    render_section_header(
        "Head-to-head records",
        SECTION_DETAILS["Head-to-head records"],
    )
    h2h = head_to_head(year=year_filter, game_type=game_type_filter)
    if h2h.empty:
        st.info("No head-to-head data for this filter.")
    else:
        display_h2h = h2h[
            [
                "owner_a",
                "owner_b",
                "record",
                "games",
                "owner_a_wins",
                "owner_b_wins",
                "owner_a_points",
                "owner_b_points",
            ]
        ]
        display_table(display_h2h)


def render_win_percentage_report(
    year_filter: int | None,
    game_type_filter: str,
) -> None:
    render_section_header(
        "Win percentage report",
        SECTION_DETAILS["Win percentage report"],
    )

    records = team_win_records(year=year_filter, game_type=game_type_filter)
    if records.empty:
        st.info("No win-loss data for this filter.")
        return

    if year_filter is None:
        records = group_team_win_records(records, by_year=False)
    else:
        records = group_team_win_records(records, by_year=True)
        records = records[records["year"] == year_filter]

    if records.empty:
        st.info("No win-loss data for this filter.")
        return

    year_label = "All time" if year_filter is None else str(year_filter)
    cols_per_row = 3

    for row_start in range(0, len(records), cols_per_row):
        cols = st.columns(cols_per_row)
        for col_idx, col in enumerate(cols):
            row_idx = row_start + col_idx
            if row_idx >= len(records):
                break

            team = records.iloc[row_idx]
            fig = go.Figure(
                go.Pie(
                    labels=["Wins", "Losses"],
                    values=[team["wins"], team["losses"]],
                    hole=0.55,
                    marker={"colors": ["#2ecc71", "#e74c3c"]},
                    textinfo="value",
                    hovertemplate=(
                        "%{label}: %{value}<br>Win %: %{percent}<extra></extra>"
                    ),
                )
            )
            fig.update_layout(
                title={
                    "text": (
                        f"{team['team_name']}<br>"
                        f"<sup>{team['team_owner']} · {year_label}</sup>"
                    ),
                    "x": 0.5,
                    "xanchor": "center",
                },
                height=320,
                margin={"l": 10, "r": 10, "t": 70, "b": 10},
                showlegend=True,
                legend={"orientation": "h", "yanchor": "bottom", "y": -0.05},
                annotations=[
                    {
                        "text": f"{team['win_pct']:.1f}%",
                        "x": 0.5,
                        "y": 0.5,
                        "font": {"size": 22, "weight": "bold"},
                        "showarrow": False,
                    }
                ],
            )
            with col:
                st.plotly_chart(fig, width="stretch")


SECTION_RENDERERS = {
    "Points scored vs conceded": render_points_section,
    "Highest scoring team ever": render_highest_scoring_teams,
    "Biggest upsets": render_biggest_upsets,
    "Biggest wins": render_biggest_wins,
    "Narrowest wins": render_narrowest_wins,
    "Lowest scores": render_lowest_scores,
    "Lowest scoring wins": render_lowest_scoring_wins,
    "Highest scoring losses": render_highest_scoring_losses,
    "Best draft picks": render_best_draft_picks,
    "Worst lineup decisions": render_worst_lineup_decisions,
    "Most points left on the bench": render_most_bench_points,
    "All-time player usage": render_player_usage,
    "Best kickers": render_best_kickers,
    "Head-to-head records": render_head_to_head,
    "Win percentage report": render_win_percentage_report,
}


def render_selected_section(
    section: str,
    year_filter: int | None,
    game_type_filter: str,
    game_type_label: str,
    summary: dict,
    owners: list[str],
    points_view: str,
    points_group_by: str,
    selected_owner: str | None,
) -> None:
    render_report_banner(section, year_filter, game_type_label)

    renderer = SECTION_RENDERERS[section]
    if section == "Points scored vs conceded":
        renderer(
            year_filter,
            game_type_filter,
            owners,
            points_view,
            points_group_by,
            selected_owner,
        )
    elif section == "Best draft picks":
        renderer(year_filter, game_type_filter, summary)
    else:
        renderer(year_filter, game_type_filter)


st.set_page_config(
    page_title="Fantasy League History",
    page_icon="🏈",
    layout="wide",
)

inject_global_styles()

st.title("Fantasy League History")
st.caption("All-time stats from your ESPN league database")

summary = get_data_summary()
years = summary["years"]

selected_year = st.sidebar.selectbox(
    "Season filter",
    options=["All time"] + years,
    index=0,
)
year_filter = None if selected_year == "All time" else int(selected_year)

GAME_TYPE_OPTIONS = {
    "All games": "all",
    "Regular season": "regular",
    "Playoffs": "playoffs",
}
selected_game_type = st.sidebar.selectbox(
    "Games",
    options=list(GAME_TYPE_OPTIONS.keys()),
    index=0,
)
game_type_filter = GAME_TYPE_OPTIONS[selected_game_type]

st.sidebar.divider()
selected_section = st.sidebar.selectbox(
    "Report",
    options=STAT_SECTIONS,
    key="stats_menu",
)

points_view = "All teams"
points_group_by = "Team name"
selected_owner = None

if not years:
    st.warning(
        "No data found in the database. Run the import scripts first:\n\n"
        "`python get_team_details.py`\n\n"
        "`python get_matchups.py`\n\n"
        "`python get_box_scores.py`\n\n"
        "`python get_draft.py`"
    )
    st.stop()

owners = list_team_owners()

if selected_section == "Points scored vs conceded":
    points_view = st.sidebar.selectbox(
        "Chart view",
        options=["All teams", "Single team"],
        key="points_view",
    )
    if points_view == "All teams":
        points_group_by = st.sidebar.selectbox(
            "Group by",
            options=["Team name", "Team owner"],
            key="points_group_by",
        )
    if points_view == "Single team" and owners:
        selected_owner = st.sidebar.selectbox("Team owner", options=owners)

st.sidebar.divider()
st.sidebar.caption("Data loaded")
st.sidebar.write(f"Seasons: {', '.join(str(y) for y in years) or 'None'}")
st.sidebar.write(f"Matchups: {summary['matchups']}")
st.sidebar.write(f"Box scores: {summary['box_scores']}")
st.sidebar.write(f"Player rows: {summary['box_players']}")
st.sidebar.write(f"Draft picks: {summary['draft_picks']}")

render_season_ticker(years)

render_selected_section(
    selected_section,
    year_filter,
    game_type_filter,
    selected_game_type,
    summary,
    owners,
    points_view,
    points_group_by,
    selected_owner,
)
