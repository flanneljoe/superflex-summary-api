class LeagueNotFoundError(Exception):
    """League ID doesn't exist on Sleeper at all."""
    pass

class LeagueNotEligibleError(Exception):
    """League exists but isn't a usable NFL season (wrong sport, or hasn't started)."""
    pass