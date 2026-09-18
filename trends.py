from sqlalchemy import text
from sqlalchemy.orm import Session
from models import TeamHistory
from config import is_notable_delta

# ### Logic for updating TeamHistory and trend information ###


def compute_weekly_facts(team: dict, opponent: dict, all_scores_this_week: list[float]) -> dict:
    signed_margin = round(team["points"] - opponent["points"], 2)

    # All-play: how this team's score ranks against every other team's score that week,
    # not just their actual opponent.
    other_scores = [s for s in all_scores_this_week if s != team["points"]]  # see note below on ties
    all_play_wins = sum(1 for s in other_scores if team["points"] > s)
    all_play_losses = sum(1 for s in other_scores if team["points"] < s)

    # Would a better bench swap have flipped a loss into a win?
    bench_beat_starter = None
    bench = team.get("bench_standout")
    if bench:
        hypothetical_points = team["points"] - bench["outscored_starter_pts"] + bench["points"]
        if team["points"] < opponent["points"]:  # only meaningful framing is "would've won instead of lost"
            bench_beat_starter = 1 if hypothetical_points > opponent["points"] else 0
        else:
            bench_beat_starter = 0  # already won — not a "what if" story

    return {
        "margin": signed_margin,
        "all_play_wins": all_play_wins,
        "all_play_losses": all_play_losses,
        "bench_beat_starter": bench_beat_starter,
    }


def compute_trend_notes(db: Session, league_id: str, user_id: str, current_week: int,
                          opponent_user_id: str, players: dict) -> list[str]:
    recent = (
        db.query(TeamHistory)
        .filter(TeamHistory.league_id == league_id, TeamHistory.user_id == user_id,
                 TeamHistory.matchup_week < current_week)
        .order_by(TeamHistory.matchup_week.desc())
        .limit(3)
        .all()
    )
    notes = []

    # Close games / blowouts — last 2+ weeks in the same direction
    if len(recent) >= 2:
        margins = [r.margin for r in recent[:2]]
        if all(abs(m) <= 10 for m in margins):
            notes.append("has been involved in a string of close games")
        elif all(m >= 25 for m in margins):
            notes.append("has been blowing out opponents lately")
        elif all(m <= -25 for m in margins):
            notes.append("has been on the losing end of blowouts lately")

    # Repeat over/under performer (same player flagged in consecutive weeks)
    if len(recent) >= 1:
        last = recent[0]
        this_week_over_id = ...  # current week's over_performer id, passed in or looked up
        if (last.over_performer_id and this_week_over_id and last.over_performer_id == this_week_over_id
                and is_notable_delta(last.over_performer_delta, None)):
            name = players.get(this_week_over_id, {}).get("full_name", this_week_over_id)
            notes.append(f"{name} has now outperformed projection in back-to-back weeks")

    # Repeat team over/under performing
    if len(recent) >= 2:
        notable_recent = [
            r for r in recent[:2]
            if r.team_projection_delta is not None and is_notable_delta(r.team_projection_delta, r.team_projected_pts)
        ]
        if len(notable_recent) == 2:
            if all(r.team_projection_delta > 0 for r in notable_recent):
                notes.append("has now outscored their team's total projection in back-to-back weeks")
            elif all(r.team_projection_delta < 0 for r in notable_recent):
                notes.append("has now fallen short of their team's total projection in back-to-back weeks")

    # Repeat bench regret
    if len(recent) >= 2 and all(r.bench_beat_starter for r in recent[:2]):
        notes.append("has now had a bench player who would've won them the game in back-to-back weeks")

    # Head-to-head history against this week's opponent
    past_meetings = db.execute(
        text("""
            SELECT user_1_points, user_2_points, user_id_1, user_id_2
            FROM matchups
            WHERE league_id = :league_id
              AND matchup_week < :week
              AND ((user_id_1 = :uid AND user_id_2 = :opp) OR (user_id_1 = :opp AND user_id_2 = :uid))
        """),
        {"league_id": league_id, "week": current_week, "uid": user_id, "opp": opponent_user_id},
    ).mappings().all()

    if past_meetings:
        wins = sum(1 for m in past_meetings if
                    (m["user_id_1"] == user_id and m["user_1_points"] > m["user_2_points"]) or
                    (m["user_id_2"] == user_id and m["user_2_points"] > m["user_1_points"]))
        notes.append(f"is {wins}-{len(past_meetings) - wins} against this opponent this season")

    return notes