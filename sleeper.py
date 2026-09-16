import httpx

from sqlalchemy.orm import Session
from config import WORKER_URL, SLEEPER_BASE

import queries
from exceptions import LeagueNotEligibleError, LeagueNotFoundError

FLEX_ELIGIBILITY = {
    "FLEX": {"RB", "WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"},
    "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
    "IDP_FLEX": {"DL", "LB", "DB"},
}

def slot_eligible_positions(slot: str) -> set[str]:
    return FLEX_ELIGIBILITY.get(slot, {slot})

# --- Player data (via your Worker ---

async def get_players() -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(WORKER_URL)
        resp.raise_for_status()
        return resp.json()  # keyed by player_id


# --- Sleeper league data ---

async def get_matchups(league_id: str, week: int) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{SLEEPER_BASE}/league/{league_id}/matchups/{week}")
        resp.raise_for_status()
        return resp.json()


async def get_rosters(league_id: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{SLEEPER_BASE}/league/{league_id}/rosters")
        resp.raise_for_status()
        return resp.json()


async def get_users(league_id: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{SLEEPER_BASE}/league/{league_id}/users")
        resp.raise_for_status()
        return resp.json()


INELIGIBLE_STATUSES = {"pre_draft", "drafting"}

async def get_league_settings(league_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{SLEEPER_BASE}/league/{league_id}")
        if resp.status_code == 404:
            raise LeagueNotFoundError(f"League '{league_id}' not found on Sleeper")
        resp.raise_for_status()
        data = resp.json()

    if data.get("sport") != "nfl":
        raise LeagueNotEligibleError(f"League '{league_id}' is not an NFL league")

    if data.get("status") in INELIGIBLE_STATUSES:
        raise LeagueNotEligibleError(
            f"League '{league_id}' has no matchup data yet (status: {data.get('status')})"
        )

    return {
        "season": data["season"],
        "scoring_settings": data["scoring_settings"],
        "roster_positions": data["roster_positions"],
    }

async def get_or_fetch_projections(db: Session, season: str, week: int) -> dict:
    cached = queries.get_cached_projections(db, season, week)
    if cached is not None:
        return cached

    fresh = await get_projections(season, week)
    queries.store_projections(db, season, week, fresh)
    return fresh

async def get_projections(season: str, week: int) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{SLEEPER_BASE}/projections/nfl/regular/{season}/{week}")
        resp.raise_for_status()
        return resp.json()


async def get_nfl_state() -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{SLEEPER_BASE}/state/nfl")
        resp.raise_for_status()
        return resp.json()


# ### BUILD TEAM STATS FOR A MATCHUP ###

def build_roster_lookup(rosters: list[dict], users: list[dict]) -> dict[int, dict]:
    user_by_id = {u["user_id"]: u for u in users}
    lookup = {}

    for roster in rosters:
        user_id = roster["owner_id"]
        user = user_by_id.get(user_id, {})
        team_name = (user.get("metadata") or {}).get("team_name") or user.get("display_name", "Unknown Team")

        settings = roster.get("settings", {})
        wins = settings.get("wins", 0)
        losses = settings.get("losses", 0)
        ties = settings.get("ties", 0)
        record = f"{wins}-{losses}" + (f"-{ties}" if ties else "")

        lookup[roster["roster_id"]] = {
            "user_id": user_id,
            "team_name": team_name,
            "record": record,
            "streak": (user.get("metadata") or {}).get("streak"),  # None if the field isn't present
        }

    return lookup


def summarize_matchup_team(team: dict, players: dict, roster_positions: list[str],
                             projections: dict | None = None, scoring_settings: dict | None = None) -> dict:
    starter_ids = team["starters"]
    points_by_player = team["players_points"]

    starter_scores = [(pid, points_by_player.get(pid, 0)) for pid in starter_ids]
    starter_scores.sort(key=lambda x: x[1], reverse=True)
    top_id, top_pts = starter_scores[0]
    low_id, low_pts = starter_scores[-1]

    def player_label(pid):
        return players.get(pid, {}).get("full_name", pid)

    result = {
        "roster_id": team["roster_id"],
        "points": team["points"],
        "high_performer_id": top_id,
        "high_performer_name": player_label(top_id),
        "high_performer_pts": top_pts,
        "low_performer_id": low_id,
        "low_performer_name": player_label(low_id),
        "low_performer_pts": low_pts,
        "bench_standout": None,
        "record": None,
        "streak": None,
        "over_performer": None,
        "under_performer": None,
        "team_projection": None,
    }

    bench = get_bench_standout(team, players, roster_positions)
    if bench:
        result["bench_standout"] = bench

    if projections is not None and scoring_settings is not None:
        over, under = get_projection_deltas(team, players, projections, scoring_settings)
        result["over_performer"] = over
        result["under_performer"] = under

        result["team_projection"] = compute_team_projection_delta(team, players, projections, scoring_settings)

    return result

def build_week_matchups(matchups: list[dict], players: dict, roster_lookup: dict, roster_positions: list[str],
                          projections: dict | None = None, scoring_settings: dict | None = None) -> list[dict]:
    by_matchup_id: dict[int, list[dict]] = {}

    for team in matchups:
        summary = summarize_matchup_team(team, players, roster_positions, projections, scoring_settings)
        roster_info = roster_lookup[summary["roster_id"]]

        summary["team_name"] = roster_info["team_name"]
        summary["user_id"] = roster_info["user_id"]
        summary["record"] = roster_info["record"]
        summary["streak"] = roster_info["streak"]

        by_matchup_id.setdefault(team["matchup_id"], []).append(summary)

    weekly_matchups = []
    for matchup_id, teams in by_matchup_id.items():
        if len(teams) != 2:
            continue

        team_a, team_b = teams
        winner, loser = (team_a, team_b) if team_a["points"] > team_b["points"] else (team_b, team_a)

        weekly_matchups.append({
            "matchup_id": matchup_id,
            "team_a": team_a,
            "team_b": team_b,
            "winner_team_name": winner["team_name"],
            "loser_team_name": loser["team_name"],
            "margin": round(abs(team_a["points"] - team_b["points"]), 2),
        })

    return weekly_matchups

# ### LEAGUE SPECIFIC STAT PROJECTIONS ###

def compute_projected_points(player_id: str, projections: dict, scoring_settings: dict) -> float | None:
    proj = projections.get(player_id)
    if not proj:
        return None

    matched_keys = [k for k in proj if k in scoring_settings]
    if not matched_keys:
        return None

    return round(sum(proj[k] * scoring_settings[k] for k in matched_keys), 2)


def get_projection_deltas(team: dict, players: dict, projections: dict, scoring_settings: dict) -> tuple[dict | None, dict | None]:
    deltas = []
    for pid in team["starters"]:
        projected = compute_projected_points(pid, projections, scoring_settings)
        if projected is None:
            continue

        actual = team["players_points"].get(pid, 0)
        deltas.append({
            "player_id": pid,
            "name": players.get(pid, {}).get("full_name", pid),
            "actual": actual,
            "projected": projected,
            "delta": round(actual - projected, 2),
        })

    if not deltas:
        return None, None

    over_candidate = max(deltas, key=lambda d: d["delta"])
    under_candidate = min(deltas, key=lambda d: d["delta"])

    over = over_candidate if over_candidate["delta"] > 0 else None
    under = under_candidate if under_candidate["delta"] < 0 else None

    return over, under


def compute_team_projection_delta(team: dict, players: dict, projections: dict, scoring_settings: dict) -> dict | None:
    total_actual = 0
    total_projected = 0
    matched_any = False

    for pid in team["starters"]:
        projected = compute_projected_points(pid, projections, scoring_settings)
        if projected is None:
            continue
        matched_any = True
        total_projected += projected
        total_actual += team["players_points"].get(pid, 0)

    if not matched_any:
        return None  # genuinely no usable projection data

    return {
        "actual": round(total_actual, 2),
        "projected": round(total_projected, 2),
        "delta": round(total_actual - total_projected, 2),
    }


def get_bench_standout(team: dict, players: dict, roster_positions: list[str]) -> dict | None:
    bench_ids = set(team["players"]) - set(team["starters"])
    if not bench_ids:
        return None

    points_by_player = team["players_points"]
    starting_slots = [p for p in roster_positions if p not in ("BN", "IR", "TAXI")]
    starter_slot_pairs = list(zip(team["starters"], starting_slots))

    best = None
    for bench_id in bench_ids:
        bench_pts = points_by_player.get(bench_id, 0)
        bench_positions = set(players.get(bench_id, {}).get("fantasy_positions", []))
        if not bench_positions:
            continue

        for starter_id, slot in starter_slot_pairs:
            if not bench_positions & slot_eligible_positions(slot):
                continue  # bench player couldn't have filled this slot

            starter_pts = points_by_player.get(starter_id, 0)
            if bench_pts > starter_pts and (best is None or bench_pts > best["points"]):
                best = {
                    "player_id": bench_id,
                    "name": players.get(bench_id, {}).get("full_name", bench_id),
                    "points": bench_pts,
                    "outscored_starter_name": players.get(starter_id, {}).get("full_name", starter_id),
                    "outscored_starter_pts": starter_pts,
                    "slot": slot,
                }

    return best