from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Literal

import pandas as pd

from db import DEFAULT_DB_PATH

GameType = Literal["all", "regular", "playoffs"]

_EMOJI_PATTERN = re.compile(
    "["
    u"\U0001F600-\U0001F64F"
    u"\U0001F300-\U0001F5FF"
    u"\U0001F680-\U0001F6FF"
    u"\U0001F1E0-\U0001F1FF"
    u"\U00002702-\U000027B0"
    u"\U000024C2-\U0001F251"
    u"\U0001F900-\U0001F9FF"
    u"\U0001FA00-\U0001FAFF"
    u"\U00002600-\U000026FF"
    u"\u200d"
    u"\uFE0F"
    "]+",
    flags=re.UNICODE,
)

STARTER_SLOTS = {"QB", "RB", "WR", "TE", "FLEX", "K", "D/ST", "OP", "SUPER_FLEX", "RB/WR", "WR/TE", "DT", "DE", "LB", "DL", "CB", "S", "DB", "DP", "P", "HC", "TQB", "RB/WR/TE"}

FLEX_SLOTS = {"FLEX", "RB/WR", "WR/TE", "RB/WR/TE"}
FLEX_BENCH_POSITIONS = {"RB", "WR", "TE"}


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_team_name(name: str | None) -> str:
    if not name:
        return ""
    cleaned = _EMOJI_PATTERN.sub("", name)
    return " ".join(cleaned.split())


def group_team_points(df: pd.DataFrame, *, by_year: bool = True) -> pd.DataFrame:
    if df.empty:
        return df

    grouped = df.copy()
    grouped["team_name_key"] = grouped["team_name"].map(normalize_team_name)
    group_cols = ["team_owner", "team_name_key"]
    if by_year:
        group_cols = ["year", *group_cols]

    return (
        grouped.groupby(group_cols, as_index=False)
        .agg(
            points_for=("points_for", "sum"),
            points_against=("points_against", "sum"),
            team_name=("team_name", "last"),
        )
        .assign(
            team_name=lambda frame: frame["team_name_key"],
            point_diff=lambda frame: frame["points_for"] - frame["points_against"],
        )
        .drop(columns=["team_name_key"])
    )


def group_owner_points(df: pd.DataFrame, *, by_year: bool = True) -> pd.DataFrame:
    if df.empty:
        return df

    group_cols = ["team_owner"]
    if by_year:
        group_cols = ["year", *group_cols]

    return (
        df.groupby(group_cols, as_index=False)
        .agg(
            points_for=("points_for", "sum"),
            points_against=("points_against", "sum"),
        )
        .assign(point_diff=lambda frame: frame["points_for"] - frame["points_against"])
    )


def get_available_years(db_path: Path = DEFAULT_DB_PATH) -> list[int]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT year FROM matchups
            UNION
            SELECT DISTINCT year FROM box_scores
            ORDER BY year DESC
            """
        ).fetchall()
    return [row["year"] for row in rows]


def get_data_summary(db_path: Path = DEFAULT_DB_PATH) -> dict:
    with get_connection(db_path) as conn:
        return {
            "teams": conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0],
            "matchups": conn.execute("SELECT COUNT(*) FROM matchups").fetchone()[0],
            "box_scores": conn.execute("SELECT COUNT(*) FROM box_scores").fetchone()[0],
            "box_players": conn.execute(
                "SELECT COUNT(*) FROM box_score_players"
            ).fetchone()[0],
            "draft_picks": conn.execute(
                "SELECT COUNT(*) FROM draft_picks"
            ).fetchone()[0],
            "years": get_available_years(db_path),
        }


def _year_clause(year: int | None, column: str = "year") -> tuple[str, list]:
    if year is None:
        return "", []
    return f" AND {column} = ?", [year]


def _game_type_clause(
    game_type: GameType = "all", column: str = "is_playoff"
) -> tuple[str, list]:
    if game_type == "regular":
        return f" AND {column} = 0", []
    if game_type == "playoffs":
        return f" AND {column} = 1", []
    return "", []


def _is_swappable_lineup_decision(
    bench_position: str | None,
    starter_position: str | None,
    starter_slot: str,
) -> bool:
    if bench_position is None or starter_position is None:
        return False
    if bench_position == starter_position:
        return True
    if (
        starter_slot in FLEX_SLOTS
        and bench_position in FLEX_BENCH_POSITIONS
    ):
        return True
    return False


def _starter_team_totals_cte(game_type: GameType = "all") -> str:
    playoff_clause, _ = _game_type_clause(game_type, "bs.is_playoff")
    return f"""
    starter_team_totals AS (
        SELECT
            bp.year,
            bp.week,
            bp.team_id,
            ROUND(SUM(bp.points), 2) AS score,
            ROUND(SUM(COALESCE(bp.projected_points, 0)), 2) AS projected
        FROM box_score_players bp
        JOIN box_scores bs
          ON bs.year = bp.year
         AND bs.espn_matchup_id = bp.espn_matchup_id
        WHERE bp.slot_position NOT IN ('BE', 'IR')
          AND bp.points IS NOT NULL
          {playoff_clause}
        GROUP BY bp.year, bp.week, bp.team_id
    )
"""


_STARTER_MATCHUP_SCORES = """
            hs.score AS home_score,
            aws.score AS away_score,
            CASE
                WHEN hs.score > aws.score THEN ht.team_name
                WHEN aws.score > hs.score THEN at.team_name
            END AS winner,
            CASE
                WHEN hs.score > aws.score THEN at.team_name
                WHEN aws.score > hs.score THEN ht.team_name
            END AS loser,
            CASE
                WHEN hs.score > aws.score THEN hs.score
                WHEN aws.score > hs.score THEN aws.score
            END AS winner_score,
            CASE
                WHEN hs.score > aws.score THEN aws.score
                WHEN aws.score > hs.score THEN hs.score
            END AS loser_score,
            ROUND(ABS(hs.score - aws.score), 2) AS margin
"""

_STARTER_MATCHUP_JOINS = """
        JOIN starter_team_totals hs
          ON hs.year = m.year
         AND hs.week = m.week
         AND hs.team_id = m.home_team_id
        JOIN starter_team_totals aws
          ON aws.year = m.year
         AND aws.week = m.week
         AND aws.team_id = m.away_team_id
"""

_STARTER_MATCHUP_WHERE = """
        WHERE m.away_team_id != 0
          AND hs.score IS NOT NULL
          AND aws.score IS NOT NULL
          AND hs.score != aws.score
"""


def highest_scoring_teams(
    year: int | None = None,
    limit: int = 10,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    clause, params = _year_clause(year, "sts.year")
    query = f"""
        WITH {_starter_team_totals_cte(game_type)}
        SELECT sts.year, sts.week, t.team_name, t.team_owner, sts.score
        FROM starter_team_totals sts
        JOIN teams t
          ON t.year = sts.year AND t.team_id = sts.team_id
        WHERE 1 = 1 {clause}
        ORDER BY sts.score DESC
        LIMIT ?
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params + [limit]).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def lowest_scoring_teams(
    year: int | None = None,
    limit: int = 10,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    clause, params = _year_clause(year, "sts.year")
    query = f"""
        WITH {_starter_team_totals_cte(game_type)}
        SELECT sts.year, sts.week, t.team_name, t.team_owner, sts.score
        FROM starter_team_totals sts
        JOIN teams t
          ON t.year = sts.year AND t.team_id = sts.team_id
        WHERE 1 = 1 {clause}
        ORDER BY sts.score ASC
        LIMIT ?
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params + [limit]).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def biggest_upsets(
    year: int | None = None,
    limit: int = 10,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    year_clause, params = _year_clause(year, "m.year")
    playoff_clause, _ = _game_type_clause(game_type, "m.is_playoff")
    query = f"""
        WITH {_starter_team_totals_cte(game_type)}
        SELECT
            m.year,
            m.week,
            ht.team_name AS home_team,
            at.team_name AS away_team,
            hs.score AS home_score,
            aws.score AS away_score,
            hs.projected AS home_projected,
            aws.projected AS away_projected,
            CASE
                WHEN hs.score > aws.score THEN ht.team_name
                WHEN aws.score > hs.score THEN at.team_name
                ELSE 'Tie'
            END AS winner,
            CASE
                WHEN hs.score > aws.score THEN hs.projected - aws.projected
                WHEN aws.score > hs.score THEN aws.projected - hs.projected
                ELSE 0
            END AS projection_gap
        FROM matchups m
        {_STARTER_MATCHUP_JOINS}
        JOIN teams ht
          ON ht.year = m.year AND ht.team_id = m.home_team_id
        JOIN teams at
          ON at.year = m.year AND at.team_id = m.away_team_id
        WHERE m.away_team_id != 0
          AND hs.score IS NOT NULL
          AND aws.score IS NOT NULL
          AND hs.score != aws.score
          AND (
            (hs.score > aws.score AND hs.projected < aws.projected)
            OR (aws.score > hs.score AND aws.projected < hs.projected)
          )
          {year_clause}{playoff_clause}
        ORDER BY projection_gap ASC
        LIMIT ?
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params + [limit]).fetchall()

    df = pd.DataFrame([dict(row) for row in rows])
    if not df.empty:
        df["upset_margin"] = df["projection_gap"].abs()
    return df


def _matchup_win_margins(
    year: int | None = None,
    limit: int = 10,
    *,
    ascending: bool = False,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    year_clause, params = _year_clause(year, "m.year")
    playoff_clause, _ = _game_type_clause(game_type, "m.is_playoff")
    order = "ASC" if ascending else "DESC"
    query = f"""
        WITH {_starter_team_totals_cte(game_type)}
        SELECT
            m.year,
            m.week,
            ht.team_name AS home_team,
            at.team_name AS away_team,
            {_STARTER_MATCHUP_SCORES}
        FROM matchups m
        {_STARTER_MATCHUP_JOINS}
        JOIN teams ht
          ON ht.year = m.year AND ht.team_id = m.home_team_id
        JOIN teams at
          ON at.year = m.year AND at.team_id = m.away_team_id
        {_STARTER_MATCHUP_WHERE}
          {year_clause}{playoff_clause}
        ORDER BY margin {order}
        LIMIT ?
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params + [limit]).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def biggest_wins(
    year: int | None = None,
    limit: int = 10,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    return _matchup_win_margins(
        year, limit, ascending=False, game_type=game_type, db_path=db_path
    )


def narrowest_wins(
    year: int | None = None,
    limit: int = 10,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    return _matchup_win_margins(
        year, limit, ascending=True, game_type=game_type, db_path=db_path
    )


def lowest_scoring_wins(
    year: int | None = None,
    limit: int = 10,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    year_clause, params = _year_clause(year, "m.year")
    playoff_clause, _ = _game_type_clause(game_type, "m.is_playoff")
    query = f"""
        WITH {_starter_team_totals_cte(game_type)}
        SELECT
            m.year,
            m.week,
            ht.team_name AS home_team,
            at.team_name AS away_team,
            {_STARTER_MATCHUP_SCORES}
        FROM matchups m
        {_STARTER_MATCHUP_JOINS}
        JOIN teams ht
          ON ht.year = m.year AND ht.team_id = m.home_team_id
        JOIN teams at
          ON at.year = m.year AND at.team_id = m.away_team_id
        {_STARTER_MATCHUP_WHERE}
          {year_clause}{playoff_clause}
        ORDER BY winner_score ASC
        LIMIT ?
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params + [limit]).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def highest_scoring_losses(
    year: int | None = None,
    limit: int = 10,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    year_clause, params = _year_clause(year, "m.year")
    playoff_clause, _ = _game_type_clause(game_type, "m.is_playoff")
    query = f"""
        WITH {_starter_team_totals_cte(game_type)}
        SELECT
            m.year,
            m.week,
            ht.team_name AS home_team,
            at.team_name AS away_team,
            {_STARTER_MATCHUP_SCORES}
        FROM matchups m
        {_STARTER_MATCHUP_JOINS}
        JOIN teams ht
          ON ht.year = m.year AND ht.team_id = m.home_team_id
        JOIN teams at
          ON at.year = m.year AND at.team_id = m.away_team_id
        {_STARTER_MATCHUP_WHERE}
          {year_clause}{playoff_clause}
        ORDER BY loser_score DESC
        LIMIT ?
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params + [limit]).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def best_draft_picks(
    year: int | None = None,
    limit: int = 10,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    year_clause, params = _year_clause(year, "d.year")
    playoff_clause, _ = _game_type_clause(game_type, "bs.is_playoff")
    if game_type == "all":
        points_join = """
        LEFT JOIN box_score_players bp
          ON bp.year = d.year
         AND bp.team_id = d.team_id
         AND bp.player_id = d.player_id
         AND bp.slot_position NOT IN ('BE', 'IR')
        """
    else:
        points_join = f"""
        LEFT JOIN box_score_players bp
          ON bp.year = d.year
         AND bp.team_id = d.team_id
         AND bp.player_id = d.player_id
         AND bp.slot_position NOT IN ('BE', 'IR')
        JOIN box_scores bs
          ON bs.year = bp.year
         AND bs.espn_matchup_id = bp.espn_matchup_id
         {playoff_clause.strip()}
        """
    query = f"""
        SELECT
            d.year,
            d.round_num,
            d.round_pick,
            d.player_name,
            t.team_name,
            t.team_owner,
            COALESCE(SUM(bp.points), 0) AS season_points
        FROM draft_picks d
        JOIN teams t
          ON t.year = d.year AND t.team_id = d.team_id
        {points_join}
        WHERE d.player_id != 0 {year_clause}
        GROUP BY d.id
        ORDER BY season_points DESC
        LIMIT ?
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params + [limit]).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def _load_lineup_rows(
    year: int | None,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    year_clause, params = _year_clause(year, "bp.year")
    playoff_clause, _ = _game_type_clause(game_type, "bs.is_playoff")
    query = f"""
        SELECT
            bp.year,
            bp.week,
            bp.team_id,
            t.team_name,
            t.team_owner,
            bp.player_id,
            bp.player_name,
            bp.slot_position,
            bp.points,
            bp.player_position
        FROM box_score_players bp
        JOIN box_scores bs
          ON bs.year = bp.year
         AND bs.espn_matchup_id = bp.espn_matchup_id
        JOIN teams t
          ON t.year = bp.year AND t.team_id = bp.team_id
        WHERE bp.points IS NOT NULL {year_clause}{playoff_clause}
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    return pd.DataFrame([dict(row) for row in rows])


def worst_lineup_decisions(
    year: int | None = None,
    limit: int = 10,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    df = _load_lineup_rows(year, game_type, db_path)
    if df.empty:
        return df

    decisions = []
    grouped = df.groupby(["year", "week", "team_id", "team_name", "team_owner"])
    for (season, week, _team_id, team_name, team_owner), group in grouped:
        starters = group[group["slot_position"].isin(STARTER_SLOTS)]
        bench = group[group["slot_position"] == "BE"]
        if starters.empty or bench.empty:
            continue

        for _, bench_row in bench.iterrows():
            for _, starter_row in starters.iterrows():
                if not _is_swappable_lineup_decision(
                    bench_row["player_position"],
                    starter_row["player_position"],
                    starter_row["slot_position"],
                ):
                    continue
                diff = bench_row["points"] - starter_row["points"]
                if diff <= 0:
                    continue
                decisions.append(
                    {
                        "year": season,
                        "week": week,
                        "team_name": team_name,
                        "team_owner": team_owner,
                        "started_player": starter_row["player_name"],
                        "started_points": starter_row["points"],
                        "benched_player": bench_row["player_name"],
                        "benched_points": bench_row["points"],
                        "points_left": round(diff, 2),
                    }
                )

    if not decisions:
        return pd.DataFrame()

    result = pd.DataFrame(decisions).sort_values(
        "points_left", ascending=False
    ).head(limit)
    return result.reset_index(drop=True)


def most_bench_points(
    year: int | None = None,
    limit: int = 10,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    year_clause, params = _year_clause(year, "bp.year")
    playoff_clause, _ = _game_type_clause(game_type, "bs.is_playoff")
    query = f"""
        SELECT
            bp.year,
            bp.week,
            t.team_name,
            t.team_owner,
            ROUND(SUM(bp.points), 2) AS bench_points,
            COUNT(*) AS bench_players
        FROM box_score_players bp
        JOIN box_scores bs
          ON bs.year = bp.year
         AND bs.espn_matchup_id = bp.espn_matchup_id
        JOIN teams t
          ON t.year = bp.year AND t.team_id = bp.team_id
        WHERE bp.slot_position = 'BE' {year_clause}{playoff_clause}
        GROUP BY bp.year, bp.week, bp.team_id
        ORDER BY bench_points DESC
        LIMIT ?
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params + [limit]).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def player_usage(
    year: int | None = None,
    limit: int = 25,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    year_clause, params = _year_clause(year, "bp.year")
    playoff_clause, _ = _game_type_clause(game_type, "bs.is_playoff")
    placeholders = ", ".join(f"'{slot}'" for slot in STARTER_SLOTS)
    query = f"""
        SELECT
            bp.player_name,
            bp.player_id,
            COUNT(*) AS starts,
            ROUND(SUM(bp.points), 2) AS total_points,
            ROUND(AVG(bp.points), 2) AS avg_points,
            MIN(bp.year) AS first_year,
            MAX(bp.year) AS last_year
        FROM box_score_players bp
        JOIN box_scores bs
          ON bs.year = bp.year
         AND bs.espn_matchup_id = bp.espn_matchup_id
        WHERE bp.slot_position IN ({placeholders}) {year_clause}{playoff_clause}
        GROUP BY bp.player_id, bp.player_name
        ORDER BY starts DESC, total_points DESC
        LIMIT ?
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params + [limit]).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def best_kickers(
    year: int | None = None,
    limit: int = 10,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    year_clause, params = _year_clause(year, "bp.year")
    playoff_clause, _ = _game_type_clause(game_type, "bs.is_playoff")
    query = f"""
        SELECT
            bp.player_name,
            bp.player_id,
            COUNT(*) AS starts,
            ROUND(SUM(bp.points), 2) AS total_points,
            ROUND(AVG(bp.points), 2) AS avg_points,
            MIN(bp.year) AS first_year,
            MAX(bp.year) AS last_year
        FROM box_score_players bp
        JOIN box_scores bs
          ON bs.year = bp.year
         AND bs.espn_matchup_id = bp.espn_matchup_id
        WHERE bp.slot_position = 'K' {year_clause}{playoff_clause}
        GROUP BY bp.player_id, bp.player_name
        ORDER BY total_points DESC, starts DESC
        LIMIT ?
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params + [limit]).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def head_to_head(
    year: int | None = None,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    year_clause, params = _year_clause(year, "m.year")
    playoff_clause, _ = _game_type_clause(game_type, "m.is_playoff")
    query = f"""
        WITH {_starter_team_totals_cte(game_type)}
        SELECT
            m.year,
            m.week,
            ht.team_owner AS home_owner,
            at.team_owner AS away_owner,
            ht.team_name AS home_team,
            at.team_name AS away_team,
            hs.score AS home_score,
            aws.score AS away_score,
            CASE
                WHEN hs.score > aws.score THEN 'HOME'
                WHEN aws.score > hs.score THEN 'AWAY'
            END AS winner
        FROM matchups m
        {_STARTER_MATCHUP_JOINS}
        JOIN teams ht
          ON ht.year = m.year AND ht.team_id = m.home_team_id
        JOIN teams at
          ON at.year = m.year AND at.team_id = m.away_team_id
        {_STARTER_MATCHUP_WHERE}
          {year_clause}{playoff_clause}
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        return pd.DataFrame()

    records: dict[tuple[str, str], dict] = {}
    for row in rows:
        home_owner = row["home_owner"] or row["home_team"]
        away_owner = row["away_owner"] or row["away_team"]
        pair = tuple(sorted([home_owner, away_owner]))
        if pair not in records:
            records[pair] = {
                "owner_a": pair[0],
                "owner_b": pair[1],
                "owner_a_wins": 0,
                "owner_b_wins": 0,
                "games": 0,
                "owner_a_points": 0.0,
                "owner_b_points": 0.0,
            }

        rec = records[pair]
        rec["games"] += 1

        if row["winner"] == "HOME":
            winner = home_owner
            home_pts, away_pts = row["home_score"], row["away_score"]
        else:
            winner = away_owner
            home_pts, away_pts = row["home_score"], row["away_score"]

        if home_owner == pair[0]:
            rec["owner_a_points"] += home_pts or 0
            rec["owner_b_points"] += away_pts or 0
        else:
            rec["owner_a_points"] += away_pts or 0
            rec["owner_b_points"] += home_pts or 0

        if winner == pair[0]:
            rec["owner_a_wins"] += 1
        else:
            rec["owner_b_wins"] += 1

    df = pd.DataFrame(records.values())
    df["record"] = df.apply(
        lambda r: f"{int(r['owner_a_wins'])}-{int(r['owner_b_wins'])}", axis=1
    )
    df = df.sort_values(["games", "owner_a_wins"], ascending=[False, False])
    return df.reset_index(drop=True)


def team_win_records(
    year: int | None = None,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    year_clause, params = _year_clause(year, "m.year")
    playoff_clause, _ = _game_type_clause(game_type, "m.is_playoff")
    query = f"""
        WITH {_starter_team_totals_cte(game_type)}
        SELECT
            m.year,
            ht.team_name AS home_team,
            ht.team_owner AS home_owner,
            at.team_name AS away_team,
            at.team_owner AS away_owner,
            CASE
                WHEN hs.score > aws.score THEN 'HOME'
                WHEN aws.score > hs.score THEN 'AWAY'
            END AS winner
        FROM matchups m
        {_STARTER_MATCHUP_JOINS}
        JOIN teams ht
          ON ht.year = m.year AND ht.team_id = m.home_team_id
        JOIN teams at
          ON at.year = m.year AND at.team_id = m.away_team_id
        {_STARTER_MATCHUP_WHERE}
          {year_clause}{playoff_clause}
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        return pd.DataFrame()

    team_rows: list[dict] = []
    for row in rows:
        if row["winner"] == "HOME":
            team_rows.append(
                {
                    "year": row["year"],
                    "team_name": row["home_team"],
                    "team_owner": row["home_owner"] or row["home_team"],
                    "wins": 1,
                    "losses": 0,
                }
            )
            team_rows.append(
                {
                    "year": row["year"],
                    "team_name": row["away_team"],
                    "team_owner": row["away_owner"] or row["away_team"],
                    "wins": 0,
                    "losses": 1,
                }
            )
        else:
            team_rows.append(
                {
                    "year": row["year"],
                    "team_name": row["away_team"],
                    "team_owner": row["away_owner"] or row["away_team"],
                    "wins": 1,
                    "losses": 0,
                }
            )
            team_rows.append(
                {
                    "year": row["year"],
                    "team_name": row["home_team"],
                    "team_owner": row["home_owner"] or row["home_team"],
                    "wins": 0,
                    "losses": 1,
                }
            )

    return pd.DataFrame(team_rows)


def group_team_win_records(df: pd.DataFrame, *, by_year: bool = True) -> pd.DataFrame:
    if df.empty:
        return df

    grouped = df.copy()
    grouped["team_name_key"] = grouped["team_name"].map(normalize_team_name)
    group_cols = ["team_owner", "team_name_key"]
    if by_year:
        group_cols = ["year", *group_cols]

    return (
        grouped.groupby(group_cols, as_index=False)
        .agg(
            wins=("wins", "sum"),
            losses=("losses", "sum"),
            team_name=("team_name", "last"),
        )
        .assign(
            team_name=lambda frame: frame["team_name_key"],
            games=lambda frame: frame["wins"] + frame["losses"],
            win_pct=lambda frame: frame["wins"] / frame["games"] * 100,
        )
        .drop(columns=["team_name_key"])
        .sort_values("win_pct", ascending=False)
    )


def team_points_for_against(
    year: int | None = None,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    year_clause, params = _year_clause(year, "tg.year")
    playoff_clause, _ = _game_type_clause(game_type, "m.is_playoff")
    query = f"""
        WITH {_starter_team_totals_cte(game_type)},
        team_games AS (
            SELECT
                m.year,
                m.home_team_id AS team_id,
                hs.score AS points_for,
                aws.score AS points_against
            FROM matchups m
            {_STARTER_MATCHUP_JOINS}
            WHERE m.away_team_id != 0
              AND hs.score IS NOT NULL
              AND aws.score IS NOT NULL
              {playoff_clause}
            UNION ALL
            SELECT
                m.year,
                m.away_team_id AS team_id,
                aws.score AS points_for,
                hs.score AS points_against
            FROM matchups m
            {_STARTER_MATCHUP_JOINS}
            WHERE m.away_team_id != 0
              AND hs.score IS NOT NULL
              AND aws.score IS NOT NULL
              {playoff_clause}
        )
        SELECT
            tg.year,
            t.team_name,
            t.team_owner,
            ROUND(SUM(tg.points_for), 2) AS points_for,
            ROUND(SUM(tg.points_against), 2) AS points_against,
            ROUND(SUM(tg.points_for) - SUM(tg.points_against), 2) AS point_diff
        FROM team_games tg
        JOIN teams t
          ON t.year = tg.year AND t.team_id = tg.team_id
        WHERE tg.points_for IS NOT NULL {year_clause}
        GROUP BY tg.year, tg.team_id
        ORDER BY tg.year DESC, points_for DESC
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return group_team_points(pd.DataFrame([dict(row) for row in rows]), by_year=True)


def points_for_against_chart(
    year: int | None = None,
    team_owner: str | None = None,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = team_points_for_against(year=year, game_type=game_type, db_path=db_path)
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    if team_owner is not None:
        df = df[df["team_owner"] == team_owner]

    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    by_season = (
        df.groupby("year", as_index=False)[["points_for", "points_against"]]
        .sum()
        .sort_values("year")
    )

    overall = pd.DataFrame(
        [
            {
                "points_for": round(df["points_for"].sum(), 2),
                "points_against": round(df["points_against"].sum(), 2),
                "point_diff": round(df["points_for"].sum() - df["points_against"].sum(), 2),
            }
        ]
    )

    return by_season, overall


def list_team_owners(db_path: Path = DEFAULT_DB_PATH) -> list[str]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT team_owner
            FROM teams
            WHERE team_owner IS NOT NULL
            ORDER BY team_owner
            """
        ).fetchall()
    return [row["team_owner"] for row in rows]


def _highlight_text(report: str, row: pd.Series) -> str:
    name = normalize_team_name

    if report == "Highest scoring team ever":
        return f"{name(row['team_name'])} scored {row['score']:,.2f}"
    if report == "Lowest scores":
        return f"{name(row['team_name'])} managed only {row['score']:,.2f}"
    if report == "Biggest upsets":
        beaten = (
            row["away_team"] if row["winner"] == row["home_team"] else row["home_team"]
        )
        return (
            f"{name(row['winner'])} upset {name(beaten)} from "
            f"{row['upset_margin']:,.2f} down on projection"
        )
    if report == "Biggest wins":
        return (
            f"{name(row['winner'])} beat {name(row['loser'])} "
            f"by {row['margin']:,.2f}"
        )
    if report == "Narrowest wins":
        return (
            f"{name(row['winner'])} edged {name(row['loser'])} "
            f"by {row['margin']:,.2f}"
        )
    if report == "Lowest scoring wins":
        return f"{name(row['winner'])} won with only {row['winner_score']:,.2f}"
    if report == "Highest scoring losses":
        return f"{name(row['loser'])} lost despite scoring {row['loser_score']:,.2f}"
    return ""


def current_season_highlights(
    season: int | None = None,
    limit: int = 10,
    game_type: GameType = "all",
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """Entries from `season` that appear in the all-time top `limit` of each report."""
    if season is None:
        years = get_available_years(db_path)
        if not years:
            return []
        season = max(years)

    reports = {
        "Highest scoring team ever": highest_scoring_teams,
        "Biggest upsets": biggest_upsets,
        "Biggest wins": biggest_wins,
        "Narrowest wins": narrowest_wins,
        "Lowest scores": lowest_scoring_teams,
        "Lowest scoring wins": lowest_scoring_wins,
        "Highest scoring losses": highest_scoring_losses,
    }

    highlights: list[dict] = []

    for report, fetch in reports.items():
        all_time = fetch(
            year=None, limit=limit, game_type=game_type, db_path=db_path
        )
        if all_time.empty or "year" not in all_time.columns:
            continue

        for position, (_, row) in enumerate(all_time.iterrows(), start=1):
            if row["year"] != season:
                continue
            highlights.append(
                {
                    "report": report,
                    "rank": position,
                    "week": int(row["week"]),
                    "text": _highlight_text(report, row),
                }
            )

    highlights.sort(key=lambda item: (item["rank"], item["report"]))
    return highlights
