from __future__ import annotations

LIVE_EVENT_RETENTION_MIN = 20_000


def clamp_live_event_retention(value: int) -> int:
    return max(1, min(int(value), LIVE_EVENT_RETENTION_MIN))
