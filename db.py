import json
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parent / "espn_league.db"

# ESPN's defaultPositionId values. Note these are NOT the same numbers as the
# lineup slot ids in espn_api's POSITION_MAP (where 0 is QB and 4 is WR) - using
# that map here mislabels every position except RB and D/ST. Ids outside this
# map resolve to None rather than guessing.
DEFAULT_POSITION_ID_MAP = {
    1: "QB",
    2: "RB",
    3: "WR",
    4: "TE",
    5: "K",
    16: "D/ST",
}


def position_from_entry(entry: dict | None) -> str | None:
    """Resolve a roster entry's natural position, independent of the slot played."""
    if not entry:
        return None

    player = entry.get("playerPoolEntry", {}).get("player", {})
    position_id = player.get("defaultPositionId")
    if position_id is None:
        return None

    try:
        return DEFAULT_POSITION_ID_MAP.get(int(position_id))
    except (TypeError, ValueError):
        return None


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                league_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                team_name TEXT NOT NULL,
                team_owner TEXT,
                owners_json TEXT NOT NULL,
                UNIQUE (league_id, year, team_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS matchups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                league_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                week INTEGER NOT NULL,
                espn_matchup_id INTEGER NOT NULL,
                home_team_id INTEGER NOT NULL,
                away_team_id INTEGER NOT NULL,
                home_score REAL,
                away_score REAL,
                winner TEXT,
                is_playoff INTEGER NOT NULL,
                playoff_tier_type TEXT,
                matchup_json TEXT NOT NULL,
                UNIQUE (league_id, year, espn_matchup_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS box_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                league_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                week INTEGER NOT NULL,
                espn_matchup_id INTEGER NOT NULL,
                home_team_id INTEGER NOT NULL,
                away_team_id INTEGER NOT NULL,
                home_score REAL,
                away_score REAL,
                home_projected REAL,
                away_projected REAL,
                is_playoff INTEGER NOT NULL,
                playoff_tier_type TEXT,
                UNIQUE (league_id, year, espn_matchup_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS box_score_players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                league_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                week INTEGER NOT NULL,
                espn_matchup_id INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                player_id INTEGER NOT NULL,
                player_name TEXT,
                slot_position TEXT,
                points REAL,
                projected_points REAL,
                player_position TEXT,
                UNIQUE (league_id, year, espn_matchup_id, team_id, player_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS draft_picks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                league_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                player_id INTEGER NOT NULL,
                player_name TEXT,
                round_num INTEGER NOT NULL,
                round_pick INTEGER NOT NULL,
                bid_amount INTEGER,
                keeper_status INTEGER,
                pick_json TEXT NOT NULL,
                UNIQUE (league_id, year, round_num, round_pick)
            )
            """
        )
        conn.commit()


def format_team_owner(owners: list) -> str | None:
    if not owners:
        return None

    names = []
    for owner in owners:
        first = owner.get("firstName", "")
        last = owner.get("lastName", "")
        name = f"{first} {last}".strip()
        if not name:
            name = owner.get("displayName", "")
        if name:
            names.append(name)

    return ", ".join(names) if names else None


def save_teams(league, db_path: Path = DEFAULT_DB_PATH) -> int:
    init_db(db_path)

    rows = []
    for team in league.teams:
        rows.append(
            (
                league.league_id,
                league.year,
                team.team_id,
                team.team_name,
                format_team_owner(team.owners),
                json.dumps(team.owners),
            )
        )

    with get_connection(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO teams (
                league_id, year, team_id, team_name, team_owner, owners_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (league_id, year, team_id) DO UPDATE SET
                team_name = excluded.team_name,
                team_owner = excluded.team_owner,
                owners_json = excluded.owners_json
            """,
            rows,
        )
        conn.commit()

    return len(rows)


def save_matchups(
    league_id: int,
    year: int,
    matchups: list[dict],
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    init_db(db_path)

    rows = []
    for matchup in matchups:
        home = matchup.get("home", {})
        away = matchup.get("away", {})
        rows.append(
            (
                league_id,
                year,
                matchup["matchupPeriodId"],
                matchup["id"],
                home.get("teamId", 0),
                away.get("teamId", 0),
                home.get("totalPoints"),
                away.get("totalPoints"),
                matchup.get("winner"),
                1 if matchup.get("playoffTierType", "NONE") != "NONE" else 0,
                matchup.get("playoffTierType", "NONE"),
                json.dumps(matchup),
            )
        )

    if not rows:
        return 0

    with get_connection(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO matchups (
                league_id,
                year,
                week,
                espn_matchup_id,
                home_team_id,
                away_team_id,
                home_score,
                away_score,
                winner,
                is_playoff,
                playoff_tier_type,
                matchup_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (league_id, year, espn_matchup_id) DO UPDATE SET
                week = excluded.week,
                home_team_id = excluded.home_team_id,
                away_team_id = excluded.away_team_id,
                home_score = excluded.home_score,
                away_score = excluded.away_score,
                winner = excluded.winner,
                is_playoff = excluded.is_playoff,
                playoff_tier_type = excluded.playoff_tier_type,
                matchup_json = excluded.matchup_json
            """,
            rows,
        )
        conn.commit()

    return len(rows)


def _find_player_entry(entries: list[dict], player_id: int) -> dict | None:
    for entry in entries:
        if entry.get("playerId") == player_id:
            return entry
    return None


def save_box_scores(
    league_id: int,
    year: int,
    week: int,
    box_scores: list,
    raw_schedule: list[dict],
    db_path: Path = DEFAULT_DB_PATH,
) -> tuple[int, int]:
    init_db(db_path)

    raw_by_teams = {}
    for matchup in raw_schedule:
        home_id = matchup.get("home", {}).get("teamId", 0)
        away_id = matchup.get("away", {}).get("teamId", 0)
        raw_by_teams[(home_id, away_id)] = matchup

    box_rows = []
    player_rows = []

    for box in box_scores:
        home_id = box.home_team if isinstance(box.home_team, int) else box.home_team.team_id
        away_id = box.away_team if isinstance(box.away_team, int) else (
            box.away_team.team_id if box.away_team is not None else 0
        )
        raw = raw_by_teams.get((home_id, away_id))
        if raw is None:
            continue

        espn_matchup_id = raw["id"]
        box_rows.append(
            (
                league_id,
                year,
                week,
                espn_matchup_id,
                home_id,
                away_id,
                box.home_score,
                box.away_score,
                box.home_projected,
                box.away_projected,
                1 if box.is_playoff else 0,
                raw.get("playoffTierType", "NONE"),
            )
        )

        for team_id, lineup in ((home_id, box.home_lineup), (away_id, box.away_lineup)):
            if not lineup:
                continue

            side = "home" if team_id == home_id else "away"
            entries = raw.get(side, {}).get(
                "rosterForCurrentScoringPeriod", {}
            ).get("entries", [])

            for player in lineup:
                entry = _find_player_entry(entries, player.playerId)
                player_rows.append(
                    (
                        league_id,
                        year,
                        week,
                        espn_matchup_id,
                        team_id,
                        player.playerId,
                        player.name,
                        player.slot_position,
                        player.points,
                        player.projected_points,
                        position_from_entry(entry),
                    )
                )

    if not box_rows:
        return 0, 0

    with get_connection(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO box_scores (
                league_id,
                year,
                week,
                espn_matchup_id,
                home_team_id,
                away_team_id,
                home_score,
                away_score,
                home_projected,
                away_projected,
                is_playoff,
                playoff_tier_type
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (league_id, year, espn_matchup_id) DO UPDATE SET
                week = excluded.week,
                home_team_id = excluded.home_team_id,
                away_team_id = excluded.away_team_id,
                home_score = excluded.home_score,
                away_score = excluded.away_score,
                home_projected = excluded.home_projected,
                away_projected = excluded.away_projected,
                is_playoff = excluded.is_playoff,
                playoff_tier_type = excluded.playoff_tier_type
            """,
            box_rows,
        )
        conn.executemany(
            """
            INSERT INTO box_score_players (
                league_id,
                year,
                week,
                espn_matchup_id,
                team_id,
                player_id,
                player_name,
                slot_position,
                points,
                projected_points,
                player_position
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (league_id, year, espn_matchup_id, team_id, player_id) DO UPDATE SET
                week = excluded.week,
                player_name = excluded.player_name,
                slot_position = excluded.slot_position,
                points = excluded.points,
                projected_points = excluded.projected_points,
                player_position = excluded.player_position
            """,
            player_rows,
        )
        conn.commit()

    return len(box_rows), len(player_rows)


def save_draft_picks(
    league_id: int,
    year: int,
    picks: list[dict],
    player_map: dict,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    init_db(db_path)

    rows = []
    for pick in picks:
        player_id = pick.get("playerId", 0)
        player_name = player_map.get(player_id, "")
        rows.append(
            (
                league_id,
                year,
                pick.get("teamId", 0),
                player_id,
                player_name,
                pick.get("roundId", 0),
                pick.get("roundPickNumber", 0),
                pick.get("bidAmount"),
                1 if pick.get("keeper") else 0,
                json.dumps(pick),
            )
        )

    if not rows:
        return 0

    with get_connection(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO draft_picks (
                league_id, year, team_id, player_id, player_name,
                round_num, round_pick, bid_amount, keeper_status, pick_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (league_id, year, round_num, round_pick) DO UPDATE SET
                team_id = excluded.team_id,
                player_id = excluded.player_id,
                player_name = excluded.player_name,
                bid_amount = excluded.bid_amount,
                keeper_status = excluded.keeper_status,
                pick_json = excluded.pick_json
            """,
            rows,
        )
        conn.commit()

    return len(rows)
