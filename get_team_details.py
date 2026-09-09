import os
from pathlib import Path

from dotenv import load_dotenv
from espn_api.football import League

from db import DEFAULT_DB_PATH, save_teams

load_dotenv()

LEAGUE_ID = 6164510
YEAR = 2026
HISTORY_YEARS = 1


def years_for_history(end_year: int, count: int = 10) -> list[int]:
    return list(range(end_year - count + 1, end_year + 1))


def load_teams_history(
    league_id: int,
    end_year: int,
    *,
    espn_s2: str | None = None,
    swid: str | None = None,
    years: int = 10,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict]:
    results = []

    for year in years_for_history(end_year, years):
        try:
            league = League(
                league_id=league_id,
                year=year,
                espn_s2=espn_s2,
                swid=swid,
            )
            team_count = save_teams(league, db_path=db_path)
            results.append(
                {
                    "year": year,
                    "team_count": team_count,
                    "error": None,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "year": year,
                    "team_count": 0,
                    "error": str(exc),
                }
            )

    return results


def main():
    results = load_teams_history(
        LEAGUE_ID,
        YEAR,
        espn_s2=os.getenv("ESPN_S2"),
        swid=os.getenv("SWID"),
        years=HISTORY_YEARS,
    )

    saved = [r for r in results if r["error"] is None]
    failed = [r for r in results if r["error"] is not None]
    total_teams = sum(r["team_count"] for r in saved)

    print(f"Database: {DEFAULT_DB_PATH}")
    print(f"Saved {total_teams} team rows across {len(saved)} seasons")

    for result in saved:
        print(f"  {result['year']}: {result['team_count']} teams")

    if failed:
        print(f"Skipped {len(failed)} seasons:")
        for result in failed:
            print(f"  {result['year']}: {result['error']}")

    return results


if __name__ == "__main__":
    # Fetch errors are collected rather than raised, so surface them as a
    # non-zero exit code or scheduled runs would report success after failing.
    if any(result["error"] for result in main()):
        raise SystemExit(1)
