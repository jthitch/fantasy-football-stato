import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from espn_api.football import League
from espn_api.football.box_score import BoxScore

from db import DEFAULT_DB_PATH, save_box_scores
from get_matchups import years_for_full_history
from get_team_details import HISTORY_YEARS, LEAGUE_ID, YEAR

load_dotenv()

MIN_BOX_SCORE_YEAR = 2019


def resolve_periods(league: League, week: int) -> tuple[int, int]:
    matchup_period = league.currentMatchupPeriod
    scoring_period = league.current_week
    if week <= league.current_week:
        scoring_period = week
        for matchup_id in league.settings.matchup_periods:
            if week in league.settings.matchup_periods[matchup_id]:
                matchup_period = matchup_id
                break
    return scoring_period, matchup_period


def fetch_week_box_scores(
    league: League,
    week: int,
    player_team_cache: dict | None = None,
) -> tuple[list[BoxScore], list[dict], int]:
    if league.year < MIN_BOX_SCORE_YEAR:
        raise Exception(f"Cant use box score before {MIN_BOX_SCORE_YEAR}")

    scoring_period, matchup_period = resolve_periods(league, week)
    params = {
        "view": ["mMatchupScore", "mScoreboard"],
        "scoringPeriodId": scoring_period,
    }
    filters = {"schedule": {"filterMatchupPeriodIds": {"value": [matchup_period]}}}
    headers = {"x-fantasy-filter": json.dumps(filters)}
    data = league.espn_request.league_get(params=params, headers=headers)
    schedule = data["schedule"]
    pro_schedule = league._get_pro_schedule(scoring_period)
    positional_rankings = league._get_positional_ratings(scoring_period)
    box_scores = [
        BoxScore(
            matchup,
            pro_schedule,
            positional_rankings,
            scoring_period,
            league.year,
            player_team_cache,
        )
        for matchup in schedule
    ]
    return box_scores, schedule, matchup_period


def weeks_to_load(league: League, week: int | None) -> list[int]:
    if week is not None:
        return [week]
    return list(range(1, league.currentMatchupPeriod + 1))


def load_box_scores(
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
        years = [
            season_year
            for season_year in years_for_full_history(
                end_year, history_years, db_path
            )
            if season_year >= MIN_BOX_SCORE_YEAR
        ]

    results = []

    for season_year in years:
        try:
            league = League(
                league_id=league_id,
                year=season_year,
                espn_s2=espn_s2,
                swid=swid,
            )
            player_team_cache: dict = {}
            weeks = weeks_to_load(league, week)
            box_count = 0
            player_count = 0

            for load_week in weeks:
                box_scores, schedule, matchup_period = fetch_week_box_scores(
                    league, load_week, player_team_cache
                )
                saved_boxes, saved_players = save_box_scores(
                    league_id,
                    season_year,
                    matchup_period,
                    box_scores,
                    schedule,
                    db_path=db_path,
                )
                box_count += saved_boxes
                player_count += saved_players

            results.append(
                {
                    "year": season_year,
                    "week": week,
                    "box_score_count": box_count,
                    "player_count": player_count,
                    "error": None,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "year": season_year,
                    "week": week,
                    "box_score_count": 0,
                    "player_count": 0,
                    "error": str(exc),
                }
            )

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch ESPN fantasy football box scores into SQLite."
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

    results = load_box_scores(
        LEAGUE_ID,
        year=args.year,
        week=args.week,
        espn_s2=os.getenv("ESPN_S2"),
        swid=os.getenv("SWID"),
    )

    saved = [result for result in results if result["error"] is None]
    failed = [result for result in results if result["error"] is not None]
    total_boxes = sum(result["box_score_count"] for result in saved)
    total_players = sum(result["player_count"] for result in saved)

    print(f"Database: {DEFAULT_DB_PATH}")
    print(
        f"Saved {total_boxes} box scores and {total_players} player rows "
        f"across {len(saved)} requests"
    )

    for result in saved:
        if result["week"] is not None:
            print(
                f"  {result['year']} week {result['week']}: "
                f"{result['box_score_count']} box scores, "
                f"{result['player_count']} players"
            )
        else:
            print(
                f"  {result['year']}: {result['box_score_count']} box scores, "
                f"{result['player_count']} players"
            )

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
