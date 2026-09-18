from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from sqlalchemy.orm import Session

from typing import Optional

from config import ALLOW_WEEK_OVERRIDE
from database import get_db
from generation import build_and_store_weekly_summary
from schemas import LeagueSummaryResponse
from exceptions import LeagueNotFoundError, LeagueNotEligibleError

import queries
import sleeper


app = FastAPI()

def get_client_ip(request):
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host  # local dev fallback, no proxy in front

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://superflex-summary.pages.dev", "http://localhost:5173"],  # dev + prod
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"status": "ok"}

@app.get("/api/summary/{league_id}/{week}", response_model=LeagueSummaryResponse)
async def get_summary(league_id: str, week: int, db: Session = Depends(get_db)):
    summary = queries.get_league_summary(db, league_id, week)
    if summary is None:
        raise HTTPException(status_code=404, detail="Summary not found for this league/week")
    return summary

@app.get("/api/current-week")
async def get_current_week():
    state = await sleeper.get_nfl_state()
    return {"week": max(state["week"] - 1, 0)}

@app.post("/api/generate/{league_id}")
@limiter.limit("5/hour")
async def trigger_summary_generation(request: Request, league_id: str, week: Optional[int] = None, db: Session = Depends(get_db)):
    if week is not None and not ALLOW_WEEK_OVERRIDE:
        raise HTTPException(status_code=400, detail="Week override is not permitted")

    if week is None:
        state = await sleeper.get_nfl_state()
        target_week = state["week"] - 1

        if target_week < 1:
            raise HTTPException(
                status_code=400,
                detail="No completed weeks available yet this season",
            )

        week = target_week

    try:
        summary = await build_and_store_weekly_summary(db, league_id, week)
    except LeagueNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except LeagueNotEligibleError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "generated", "week": week, "summary": summary}