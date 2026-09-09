import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from espn_api.football import League

from db import DEFAULT_DB_PATH, get_connection, init_db, save_matchups
from get_team_details import HISTORY_YEARS, LEAGUE_ID, YEAR, years_for_history

load_dotenv()


def fetch_schedule(league: League) -> list[dict]:
    data = league.espn_request.league_get(params={"view": "mMatchupScore"})
    return data["schedule"]


def filter_matchups(schedule: list[dict], week: int) -> list[dict]:
    return [matchup for matchup in schedule if matchup["matchupPeriodId"] == week]


def years_for_full_history(
    end_year: int = YEAR,
    history_years: int = HISTORY_YEARS,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[int]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT year FROM teams ORDER BY year"
        ).fetchall()

    if rows:
        return [row["year"] for row in rows]

    return years_for_history(end_year, history_years)


def load_matchups(
    league_id: int,
    *,
    year: int | None = None,
    week: int | None = None,
    end_year: int = YEAR,
    history_years: int = HISTORY_YEARS,
    espn_s2: str | None = None,
    swid: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict]:
    if week is not None and year is None:
        raise ValueError("week requires year")

    if year is not None:
        years = [year]
    else:
        years = years_for_full_history(end_year, history_years, db_path)

    results = []

    for season_year in years:
        try:
            league = League(
                league_id=league_id,
                year=season_year,
                espn_s2=espn_s2,
                swid=swid,
            )
            schedule = fetch_schedule(league)

            if week is not None:
                matchups = filter_matchups(schedule, week)
            else:
                matchups = [
                    matchup
                    for matchup in schedule
                    if matchup["matchupPeriodId"] <= league.currentMatchupPeriod
                ]

            matchup_count = save_matchups(
                league_id, season_year, matchups, db_path=db_path
            )
            results.append(
                {
                    "year": season_year,
                    "week": week,
                    "matchup_count": matchup_count,
                    "error": None,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "year": season_year,
                    "week": week,
                    "matchup_count": 0,
                    "error": str(exc),
                }
            )

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch ESPN fantasy football matchups into SQLite."
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Season year to fetch. If omitted, loads full history.",
    )
    parser.add_argument(
        "--week",
        type=int,
        help="Matchup week to fetch. Requires --year.",
    )
    return parser.parse_args()


def main() -> list[dict]:
    args = parse_args()

    if args.week is not None and args.year is None:
        raise SystemExit("--week requires --year")

    results = load_matchups(
        LEAGUE_ID,
        year=args.year,
        week=args.week,
        espn_s2=os.getenv("ESPN_S2"),
        swid=os.getenv("SWID"),
    )

    saved = [result for result in results if result["error"] is None]
    failed = [result for result in results if result["error"] is not None]
    total_matchups = sum(result["matchup_count"] for result in saved)

    print(f"Database: {DEFAULT_DB_PATH}")
    print(f"Saved {total_matchups} matchup rows across {len(saved)} requests")

    for result in saved:
        if result["week"] is not None:
            print(
                f"  {result['year']} week {result['week']}: "
                f"{result['matchup_count']} matchups"
            )
        else:
            print(f"  {result['year']}: {result['matchup_count']} matchups")

    if failed:
        print(f"Skipped {len(failed)} requests:")
        for result in failed:
            if result["week"] is not None:
                print(
                    f"  {result['year']} week {result['week']}: {result['error']}"
                )
            else:
                print(f"  {result['year']}: {result['error']}")

    return results


if __name__ == "__main__":
    # Fetch errors are collected rather than raised, so surface them as a
    # non-zero exit code or scheduled runs would report success after failing.
    if any(result["error"] for result in main()):
        raise SystemExit(1)
