import json
from anthropic import Anthropic
from config import ANTHROPIC_API_KEY, is_notable_delta

client = Anthropic(api_key=ANTHROPIC_API_KEY)

# ### Shapes Anthropic payload and makes api call ###

# SYSTEM_PROMPT = """You are a sports reporter writing a weekly summary article on a fantasy football league. \
# Each week, you're given structured data about that week's matchups and asked to write a cohesive recap covering the entire week.
#
# Structure your response as:
# 1. A markdown header (##) for the weekly article title followed by a short intro paragraph that sets \
# the tone for the week as a whole. You can reference standout results across the league \
# (closest game, biggest blowout,highest score, etc.) to tie it together.
# 2. A markdown header (##) for each matchup, formatted as "## {Team A} vs {Team B}: {Team A's Score}-{Team B's Score}", \
# followed by two paragraphs (~5 sentences) recapping that specific game from each team's perspective.
#
# The article title header should follow the format 'Week #: <Article Title>'.
#
# For each team in a matchup, you're given a pool of available stats and storylines — not all of them will be \
# present for every team, and you should not try to use all of them. For each team, choose the 2-3 most \
# interesting or narratively useful items from what's provided (e.g. high_performer, low_performer, \
# bench_standout, over_performer, under_performer, record, streak) and build the paragraphs around those. If present, \
# team trends found in elements of trends_notes[str] can be used for additional narrative items. Not all trends should or\
# need to be used. Let the specific data available guide the choice — topics such as team trends, a team with a notable \
# bench_standout, or a big over_performer delta is often more interesting to highlight than a routine \
# high/low performer split. Consider expanding on these ideas like a beat reporter. Vary which fields you draw from \
# across different matchups and different teams so the recap doesn't read the same for each team team.
#
# Always state the final score and who won for each matchup, regardless of which supporting details you choose \
# to highlight.
#
# Do not invent stats, players, or context not present in the data provided. Only use what's given. Do not \
# force in every available data point for a team — cherry-pick for the story, not for completeness.
#
# Write in a serious tone of a sports reporter with occasional light humor. Should feel like an ESPN recap \
# article, not a reading of stats. \
# Do not include any preamble, closing remarks, or text outside the requested structure."""

SYSTEM_PROMPT = """You are a sports reporter writing a weekly summary article on a fantasy football league. \
Each week, you're given structured data about that week's matchups and asked to write a cohesive recap covering the entire week.

Structure your response as:
1. A markdown header (##) for the weekly article title followed by a short intro paragraph that sets \
the tone for the week as a whole. You can reference standout results across the league \
(closest game, biggest blowout,highest score, etc.) to tie it together.
2. A markdown header (##) for each matchup, formatted as "## {Team A} vs {Team B}: {Team A's Score}-{Team B's Score}", \
followed by two paragraphs (~5 sentences) recapping that specific game from each team's perspective.

The article title header should follow the format 'Week #: <Article Title>'.

For each team in a matchup, you're given a pool of available stats and storylines to construct narratives. Not all of \
them will be present for every team. If present, team trends found in elements of trends_notes[str] can be used as \
additional narrative options. Not all trends should or need to be used. Identify what datapoints were important \
in determining a team's performance.

Then use up to 4 of the most narratively significant items to write a paragraph summarizing the team's performance.\
Write and expand on these ideas like a beat reporter. When possible vary which fields you draw from across different \
matchups and different teams so the summaries don't become repetitive when reading.

Always state the final score and who won for each matchup, regardless of which supporting details you choose \
to highlight.

Do not invent stats, players, or context not present in the data provided. Only use what's given. Do not \
force in every available data point for a team. Select for the story, not for completeness.

Aim for the feel like a cohesive article, not a listing of stats. Write in the tone of a fan giving their thoughts \
after each game has just ended. Avoid using em dashes (—) when writing. Do not include any preamble, closing remarks, \
or text outside the requested structure."""

def _drop_none(obj):
    """Recursively strip None values from dicts so the LLM only sees fields with real content."""
    if isinstance(obj, dict):
        return {k: _drop_none(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_drop_none(v) for v in obj]
    return obj


def build_llm_payload(weekly_matchups: list[dict]) -> list[dict]:
    payload = []
    for m in weekly_matchups:
        team_payload = {}
        for side in ("team_a", "team_b"):
            team = m[side]
            entry = {
                "team_name": team["team_name"],
                "points": team["points"],
                "record": team.get("record"),
                "streak": team.get("streak"),
                "high_performer": f"{team['high_performer_name']} ({team['high_performer_pts']} pts)",
                "low_performer": f"{team['low_performer_name']} ({team['low_performer_pts']} pts)",
            }

            bench = team.get("bench_standout")
            if bench:
                entry["bench_standout"] = (
                    f"{bench['name']} ({bench['points']} pts on bench, "
                    f"outscored {bench['outscored_starter_name']} ({bench['outscored_starter_pts']} pts) "
                    f"at {bench['slot']})"
                )

            over = team.get("over_performer")
            if over and is_notable_delta(over["delta"], over["projected"]):
                entry[
                    "over_performer"] = f"{over['name']}: {over['actual']} actual vs {over['projected']} projected (+{over['delta']})"

            under = team.get("under_performer")
            if under and is_notable_delta(under["delta"], under["projected"]):
                entry[
                    "under_performer"] = f"{under['name']}: {under['actual']} actual vs {under['projected']} projected ({under['delta']})"

            notes = team.get("trend_notes")
            if notes:
                entry["trend_notes"] = notes

            team_payload[side] = _drop_none(entry)

        payload.append({
            "matchup_id": m["matchup_id"],
            "team_a": team_payload["team_a"],
            "team_b": team_payload["team_b"],
            "winner": m["winner_team_name"],
            "margin": m["margin"],
        })
    return payload

def request_narrative(week: int, weekly_matchups: list[dict]) -> str:
    payload = build_llm_payload(weekly_matchups)
    user_message = f"Here is the matchup data for week {week}:\n\n{json.dumps(payload, indent=2)}"

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    print([block.type for block in response.content])
    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        raise ValueError(f"No text content in response. Got block types: {[b.type for b in response.content]}")

    return "\n".join(text_blocks)