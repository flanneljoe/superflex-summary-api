import asyncio
from sqlalchemy.orm import Session
import sleeper
import trends
import queries
from models import LeagueSummary
from summarizer import request_narrative


async def build_and_store_weekly_stats(db: Session, league_id: str, week: int) -> list[dict]:
    """Fetches Sleeper data, computes all derived stats/trends, and writes TeamHistory + Matchups.
    Does not call the LLM or write LeagueSummary; can run on any past week."""
    league_settings = await sleeper.get_league_settings(league_id)
    season = league_settings["season"]

    players, matchups, rosters, users = await asyncio.gather(
        sleeper.get_players(),
        sleeper.get_matchups(league_id, week),
        sleeper.get_rosters(league_id),
        sleeper.get_users(league_id),
    )
    projections = await sleeper.get_or_fetch_projections(db, season, week)
    roster_lookup = sleeper.build_roster_lookup(rosters, users)

    weekly_matchups = sleeper.build_week_matchups(
        matchups, players, roster_lookup,
        roster_positions=league_settings["roster_positions"],
        projections=projections,
        scoring_settings=league_settings["scoring_settings"],
    )

    _attach_trends_and_facts(db, league_id, week, weekly_matchups, players)

    for m in weekly_matchups:
        team_a, team_b = m["team_a"], m["team_b"]

        queries.store_matchup(db, league_id, week, team_a["user_id"], team_b["user_id"],
                                team_a["points"], team_b["points"])

        queries.store_team_history(db, league_id, team_a["user_id"], week, team_a, team_a["_weekly_facts"])
        queries.store_team_history(db, league_id, team_b["user_id"], week, team_b, team_b["_weekly_facts"])

    db.commit()
    return weekly_matchups


async def ensure_history_through_week(db: Session, league_id: str, upto_week: int):
    """Backfills any missing weeks' stats so trend queries have full context, without generating summaries for them."""
    highest = queries.get_highest_recorded_week(db, league_id)
    start = (highest or 0) + 1

    for week in range(start, upto_week):
        await build_and_store_weekly_stats(db, league_id, week)


async def build_and_store_weekly_summary(db: Session, league_id: str, week: int) -> str:
    """Full pipeline for the requested week: backfill anything missing, compute this week's stats,
    generate the narrative, and store LeagueSummary."""
    await ensure_history_through_week(db, league_id, week)

    weekly_matchups = await build_and_store_weekly_stats(db, league_id, week)
    summary_text = request_narrative(week, weekly_matchups)

    db.merge(LeagueSummary(league_id=league_id, week_generated=week, summary=summary_text))
    db.commit()

    return summary_text


def _attach_trends_and_facts(db, league_id, week, weekly_matchups, players):
    all_scores = [m[side]["points"] for m in weekly_matchups for side in ("team_a", "team_b")]

    for m in weekly_matchups:
        team_a, team_b = m["team_a"], m["team_b"]

        team_a["_weekly_facts"] = trends.compute_weekly_facts(team_a, team_b, all_scores)
        team_b["_weekly_facts"] = trends.compute_weekly_facts(team_b, team_a, all_scores)

        team_a["trend_notes"] = trends.compute_trend_notes(db, league_id, team_a["user_id"], week, team_b["user_id"], players)
        team_b["trend_notes"] = trends.compute_trend_notes(db, league_id, team_b["user_id"], week, team_a["user_id"], players)