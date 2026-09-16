import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
INTERNAL_API_KEY = os.environ["INTERNAL_API_KEY"]
WORKER_URL = os.environ["SLEEPER_WORKER_URL"]

SLEEPER_BASE = "https://api.sleeper.app/v1"
PROJECTION_DELTA_THRESHOLD_PCT = .15

ALLOW_WEEK_OVERRIDE = os.environ.get("ALLOW_WEEK_OVERRIDE", "false").lower() == "true"

def is_notable_delta(delta: float, projected: float | None) -> bool:
    if not projected or projected <= 0:
        return False
    return abs(delta) / projected >= PROJECTION_DELTA_THRESHOLD_PCT