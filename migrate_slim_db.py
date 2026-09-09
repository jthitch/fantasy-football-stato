"""One-off migration that shrinks espn_league.db so it can live in git.

The importers used to store the raw ESPN API payload for every box score and
every player-week. Those two columns accounted for ~88 MB of a 111 MB file,
which is over GitHub's 100 MiB per-file push limit. Nothing read
box_scores.box_score_json at all, and box_score_players.player_json was only
ever used to look up a player's natural position, so that value is backfilled
into a player_position column before the JSON is dropped.

Safe to re-run: each step is skipped if it has already been applied.
"""

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

from db import DEFAULT_DB_PATH, DEFAULT_POSITION_ID_MAP

DROPPED_COLUMNS = [
    ("box_scores", "box_score_json"),
    ("box_score_players", "player_json"),
]


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def position_from_json(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    player = data.get("playerPoolEntry", {}).get("player", {})
    position_id = player.get("defaultPositionId")
    if position_id is None:
        return None
    try:
        return DEFAULT_POSITION_ID_MAP.get(int(position_id))
    except (TypeError, ValueError):
        return None


def backfill_positions(conn: sqlite3.Connection) -> int:
    existing = columns(conn, "box_score_players")

    if "player_position" not in existing:
        conn.execute("ALTER TABLE box_score_players ADD COLUMN player_position TEXT")
        print("  added box_score_players.player_position")

    if "player_json" not in existing:
        print("  player_json already dropped, nothing to backfill")
        return 0

    rows = conn.execute(
        """
        SELECT id, player_json
        FROM box_score_players
        WHERE player_position IS NULL AND player_json IS NOT NULL
        """
    ).fetchall()

    updates = [(position_from_json(raw), row_id) for row_id, raw in rows]
    resolved = [u for u in updates if u[0] is not None]

    conn.executemany(
        "UPDATE box_score_players SET player_position = ? WHERE id = ?",
        resolved,
    )
    print(f"  backfilled {len(resolved)} of {len(rows)} player rows")
    return len(resolved)


def drop_columns(conn: sqlite3.Connection) -> None:
    for table, column in DROPPED_COLUMNS:
        if column in columns(conn, table):
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
            print(f"  dropped {table}.{column}")
        else:
            print(f"  {table}.{column} already dropped")


def size_mb(path: Path) -> float:
    return round(path.stat().st_size / 1048576, 2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Database to migrate.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip writing a .backup copy before migrating.",
    )
    args = parser.parse_args()

    db_path: Path = args.db
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    before = size_mb(db_path)
    print(f"Database: {db_path} ({before} MB)")

    if not args.no_backup:
        backup = db_path.with_suffix(db_path.suffix + ".backup")
        shutil.copy2(db_path, backup)
        print(f"Backup:   {backup}")

    conn = sqlite3.connect(db_path)
    try:
        print("Backfilling positions...")
        backfill_positions(conn)
        print("Dropping unused JSON columns...")
        drop_columns(conn)
        conn.commit()
    finally:
        conn.close()

    # VACUUM has to run outside a transaction to actually reclaim the pages.
    print("Vacuuming...")
    vacuum = sqlite3.connect(db_path, isolation_level=None)
    try:
        vacuum.execute("VACUUM")
    finally:
        vacuum.close()

    after = size_mb(db_path)
    saved = round(before - after, 2)
    print(f"Done: {before} MB -> {after} MB (saved {saved} MB)")


if __name__ == "__main__":
    main()
