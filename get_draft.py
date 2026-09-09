import os
from pathlib import Path

from dotenv import load_dotenv
from espn_api.football import League

from db import DEFAULT_DB_PATH, save_draft_picks
from get_matchups import years_for_full_history
from get_team_details import HISTORY_YEARS, LEAGUE_ID, YEAR

load_dotenv()


def load_draft_picks(
    league_id: int,
    *,
    year: int | None = None,
    end_year: int = YEAR,
    history_years: int = HISTORY_YEARS,
    espn_s2: str | None = None,
    swid: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict]:
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
            data = league.espn_request.get_league_draft()
            picks = data.get("draftDetail", {}).get("picks", [])
            if not picks:
                results.append(
                    {
                        "year": season_year,
                        "pick_count": 0,
                        "error": "No draft data found",
                    }
                )
                continue

            pick_count = save_draft_picks(
                league_id, season_year, picks, league.player_map, db_path=db_path
            )
            results.append(
                {"year": season_year, "pick_count": pick_count, "error": None}
            )
        except Exception as exc:
            results.append(
                {"year": season_year, "pick_count": 0, "error": str(exc)}
            )

    return results


def main() -> list[dict]:
    results = load_draft_picks(
        LEAGUE_ID,
        espn_s2=os.getenv("ESPN_S2"),
        swid=os.getenv("SWID"),
    )

    saved = [r for r in results if r["error"] is None]
    failed = [r for r in results if r["error"] is not None]
    total = sum(r["pick_count"] for r in saved)

    print(f"Database: {DEFAULT_DB_PATH}")
    print(f"Saved {total} draft picks across {len(saved)} seasons")
    for result in saved:
        print(f"  {result['year']}: {result['pick_count']} picks")
    if failed:
        print(f"Skipped {len(failed)} seasons:")
        for result in failed:
            print(f"  {result['year']}: {result['error']}")

    return results


if __name__ == "__main__":
    main()
