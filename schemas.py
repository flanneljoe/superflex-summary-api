from pydantic import BaseModel
from datetime import datetime


class LeagueSummaryResponse(BaseModel):
    league_id: str
    week_generated: int
    summary: str
    created_at: datetime

    class Config:
        from_attributes = True