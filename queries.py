from sqlalchemy import text, func, and_, or_
from sqlalchemy.orm import Session
from models import LeagueSummary, ProjectionCache, TeamHistory, Matchup, KnownLeague, GenerationState, DiscordSubscription



def get_league_summary(db: Session, league_id: str, week: int):
    return (
        db.query(LeagueSummary)
        .filter(LeagueSummary.league_id == league_id, LeagueSummary.week_generated == week)
        .first()
    )


def register_known_league(db: Session, league_id: str, season: str, previous_league_id: str | None):
    db.merge(KnownLeague(league_id=league_id, season=season, previous_league_id=previous_league_id))
    db.commit()


def get_cached_projections(db: Session, season: str, week: int) -> dict | None:
    row = db.query(ProjectionCache).filter_by(season=season, week=week).first()
    return row.data if row else None


def get_highest_recorded_week(db: Session, league_id: str) -> int | None:
    result = db.query(func.max(TeamHistory.matchup_week)).filter(TeamHistory.league_id == league_id).scalar()
    return result


def get_current_season_league_ids(db: Session) -> list[str]:
    max_season = db.query(func.max(KnownLeague.season)).scalar()
    if max_season is None:
        return []
    return [row.league_id for row in db.query(KnownLeague).filter(KnownLeague.season == max_season).all()]


def store_projections(db: Session, season: str, week: int, data: dict):
    row = ProjectionCache(season=season, week=week, data=data)
    db.merge(row)  # insert or update if it somehow already exists
    db.commit()


def store_matchup(db: Session, league_id: str, week: int, user_id_1: str, user_id_2: str,
                    points_1: float, points_2: float):
    existing = db.query(Matchup).filter(
        Matchup.league_id == league_id,
        Matchup.matchup_week == week,
        or_(
            and_(Matchup.user_id_1 == user_id_1, Matchup.user_id_2 == user_id_2),
            and_(Matchup.user_id_1 == user_id_2, Matchup.user_id_2 == user_id_1),
        ),
    ).first()

    if existing:
        if existing.user_id_1 == user_id_1:
            existing.user_1_points = points_1
            existing.user_2_points = points_2
        else:
            existing.user_1_points = points_2
            existing.user_2_points = points_1
    else:
        db.add(Matchup(league_id=league_id, matchup_week=week,
                         user_id_1=user_id_1, user_id_2=user_id_2,
                         user_1_points=points_1, user_2_points=points_2))


def store_team_history(db: Session, league_id: str, user_id: str, week: int, team: dict, facts: dict):
    over = team.get("over_performer")
    under = team.get("under_performer")
    team_projection = team.get("team_projection")

    row = TeamHistory(
        league_id=league_id,
        user_id=user_id,
        matchup_week=week,
        high_performer_id=team["high_performer_id"],
        high_performer_pts=team["high_performer_pts"],
        low_performer_id=team["low_performer_id"],
        low_performer_pts=team["low_performer_pts"],
        over_performer_id=over["player_id"] if over else None,
        over_performer_delta=over["delta"] if over else None,
        over_performer_projected=over["projected"] if over else None,
        under_performer_id=under["player_id"] if under else None,
        under_performer_delta=under["delta"] if under else None,
        under_performer_projected=under["projected"] if under else None,
        margin=facts["margin"],
        bench_beat_starter=facts["bench_beat_starter"],
        all_play_wins=facts["all_play_wins"],
        all_play_losses=facts["all_play_losses"],
        team_projected_pts=team_projection["projected"] if team_projection else None,
        team_projection_delta=team_projection["delta"] if team_projection else None,
    )
    db.merge(row)
    db.commit()


def get_state(db: Session, key: str) -> str | None:
    row = db.query(GenerationState).filter_by(key=key).first()
    return row.value if row else None

def set_state(db: Session, key: str, value: str):
    db.merge(GenerationState(key=key, value=value))
    db.commit()


def upsert_discord_subscription(db: Session, league_id: str, guild_id: str, channel_id: str):
    db.merge(DiscordSubscription(league_id=league_id, guild_id=guild_id, channel_id=channel_id))
    db.commit()


def delete_discord_subscription(db: Session, league_id: str, guild_id: str) -> bool:
    row = db.query(DiscordSubscription).filter_by(league_id=league_id, guild_id=guild_id).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def list_discord_subscriptions_for_guild(db: Session, guild_id: str) -> list[DiscordSubscription]:
    return db.query(DiscordSubscription).filter_by(guild_id=guild_id).all()


def get_subscriptions_for_league(db: Session, league_id: str) -> list[DiscordSubscription]:
    return db.query(DiscordSubscription).filter_by(league_id=league_id).all()