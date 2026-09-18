from sqlalchemy import Column, String, Integer, Float, Text, DateTime, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.sql import func
from database import Base

class LeagueSummary(Base):
    __tablename__ = "league_summaries"

    league_id = Column(String(64), primary_key=True)
    week_generated = Column(Integer, primary_key=True)
    summary = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class Matchup(Base):
    __tablename__ = "matchups"

    matchup_id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(String(64), nullable=False)
    matchup_week = Column(Integer, nullable=False)
    user_id_1 = Column(String(64), nullable=False)
    user_id_2 = Column(String(64), nullable=False)
    user_1_points = Column(Float, nullable=False)
    user_2_points = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("league_id", "matchup_week", "user_id_1", "user_id_2"),
    )


class TeamHistory(Base):
    __tablename__ = "team_histories"

    league_id = Column(String(64), primary_key=True)
    user_id = Column(String(64), primary_key=True)
    matchup_week = Column(Integer, primary_key=True)

    high_performer_id = Column(String(32))
    high_performer_pts = Column(Float)
    low_performer_id = Column(String(32))
    low_performer_pts = Column(Float)

    over_performer_id = Column(String(32))
    over_performer_delta = Column(Float)
    over_performer_projected = Column(Float)
    under_performer_id = Column(String(32))
    under_performer_delta = Column(Float)
    under_performer_projected = Column(Float)

    margin = Column(Float)
    bench_beat_starter = Column(Integer, nullable=True)
    all_play_wins = Column(Integer)
    all_play_losses = Column(Integer)

    team_projected_pts = Column(Float)
    team_projection_delta = Column(Float)


class ProjectionCache(Base):
    __tablename__ = "projection_cache"

    season = Column(String(8), primary_key=True)
    week = Column(Integer, primary_key=True)
    fetched_at = Column(DateTime, server_default=func.now())
    data = Column(JSON, nullable=False)


class KnownLeague(Base):
    __tablename__ = "known_leagues"

    league_id = Column(String(64), primary_key=True)
    season = Column(String(8), nullable=False)
    previous_league_id = Column(String(64), nullable=True)
    first_seen_at = Column(DateTime, server_default=func.now())


class GenerationState(Base):
    __tablename__ = "generation_state"

    key = Column(String(64), primary_key=True)  # "last_processed_week"
    value = Column(String(64), nullable=False)  # extra column incase batch tracking becomes needed