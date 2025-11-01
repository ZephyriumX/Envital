# backend/aggregator.py
"""
Aggregator daemon / runner for Envital GeoAware.

- Defensive runtime checks and type-casts so static type-checkers (Pylance/mypy)
  don't complain about SQLAlchemy Column descriptors.
- Auto-computes H3 tile_id (string) when missing.
- Produces user_windows ORM rows (merge/add) for persistence.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, List, Sequence, Dict, Tuple, Optional, cast
import statistics
import logging

import h3.api.basic_int as h3

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import AsyncSessionLocal
from backend.models import RawEvent, UserWindow

logger = logging.getLogger("aggregator")

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
WINDOW_SECONDS = 300  # 5-minute tumbling window (change if needed)
H3_RESOLUTION = 8     # default H3 resolution for tiling


# ------------------------------------------------------------------
# Small helpers to keep Pylance happy and avoid Column[...] reaching numeric ops
# ------------------------------------------------------------------
def _to_float_list(values: Sequence[Any]) -> List[float]:
    out: List[float] = []
    for v in values:
        if v is None:
            continue
        # Skip SQLAlchemy descriptors if accidentally passed (seen at static-analysis time)
        if hasattr(v, "__class__") and "InstrumentedAttribute" in v.__class__.__name__:
            continue
        try:
            out.append(float(v))
        except Exception:
            continue
    return out


def _to_int_list(values: Sequence[Any]) -> List[int]:
    out: List[int] = []
    for v in values:
        if v is None:
            continue
        if hasattr(v, "__class__") and "InstrumentedAttribute" in v.__class__.__name__:
            continue
        try:
            out.append(int(v))
        except Exception:
            continue
    return out


def floor_to_window(ts: datetime, window_seconds: int = WINDOW_SECONDS) -> datetime:
    """Return timezone-aware floored datetime to the window start."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    epoch = int(ts.timestamp())
    floored = epoch - (epoch % window_seconds)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


# ------------------------------------------------------------------
# DB fetch + aggregation logic
# ------------------------------------------------------------------
async def fetch_raw_events(session: AsyncSession, since: datetime) -> List[RawEvent]:
    """Fetch RawEvent instances newer than `since`."""
    stmt = select(RawEvent).where(RawEvent.timestamp >= since).order_by(RawEvent.timestamp.asc())
    res = await session.execute(stmt)
    # convert to concrete list for typing and runtime safety
    return list(res.scalars().all())


def aggregate_events_to_row(evs: List[RawEvent]) -> Optional[Dict[str, Any]]:
    """
    Convert a list of RawEvent model instances into a plain dict suitable for
    creating/updating a UserWindow ORM object.
    """
    if not evs:
        return None

    # Defensive extraction
    hr_vals = _to_float_list([getattr(e, "hr", None) for e in evs])
    spo2_vals = _to_float_list([getattr(e, "spo2", None) for e in evs])
    steps_vals = _to_int_list([getattr(e, "steps", None) for e in evs])
    lat_vals = _to_float_list([getattr(e, "lat", None) for e in evs])
    lon_vals = _to_float_list([getattr(e, "lon", None) for e in evs])

    def mean_or_none(lst: List[float]) -> Optional[float]:
        return statistics.mean(lst) if lst else None

    hr_mean = mean_or_none(hr_vals)
    hr_std = statistics.pstdev(hr_vals) if len(hr_vals) > 1 else None
    spo2_mean = mean_or_none(spo2_vals)
    spo2_min = min(spo2_vals) if spo2_vals else None
    steps_sum = int(sum(steps_vals)) if steps_vals else 0
    lat_mean = mean_or_none(lat_vals)
    lon_mean = mean_or_none(lon_vals)

    # Prefer existing tile_id values from events; else compute using centroid
    tile_candidates = [t for t in (getattr(e, "tile_id", None) for e in evs) if t]
    tile_id_val: Optional[str] = None
    if tile_candidates:
        # ensure string
        tile_id_val = str(tile_candidates[0])
    else:
        if lat_mean is not None and lon_mean is not None:
            try:
                raw_tile = h3.geo_to_h3(lat_mean, lon_mean, H3_RESOLUTION)
                tile_id_val = str(raw_tile)
            except Exception:
                tile_id_val = None

    first_ts = evs[0].timestamp
    # make sure timestamp is datetime
    if not isinstance(first_ts, datetime):
        # fallback to now if something weird
        first_ts = datetime.now(timezone.utc)
    user_id = getattr(evs[0], "user_id", None)
    if user_id is None:
        user_id = "unknown"

    window_start = floor_to_window(first_ts)
    window_end = window_start + timedelta(seconds=WINDOW_SECONDS)

    row = {
        "id": f"{user_id}_{window_start.isoformat()}",
        "user_id": user_id,
        "window_start": window_start,
        "window_end": window_end,
        "hr_mean": hr_mean,
        "hr_std": hr_std,
        "spo2_mean": spo2_mean,
        "spo2_min": spo2_min,
        "steps_sum": steps_sum,
        "lat_mean": lat_mean,
        "lon_mean": lon_mean,
        "tile_id": tile_id_val,
        # environmental placeholders (keep None when unknown)
        "ambient_temp_mean": None,
        "humidity_mean": None,
        "noise_mean": None,
        "aqi_mean": None,
        "heat_index_mean": None,
        # baseline placeholders
        "baseline_hr_hour": hr_mean,
        "baseline_spo2": spo2_mean,
        "anomaly_score": None,
    }
    return row


async def upsert_user_window(session: AsyncSession, row: Dict[str, Any]) -> None:
    """
    Persist the aggregated row to user_windows. Use ORM merge/add approach
    which works reliably for our schema; this keeps the code simple and readable.
    """
    # Construct a UserWindow ORM instance and add/merge
    uw = UserWindow(**row)
    # Use merge() to perform upsert-like behavior (it will INSERT or UPDATE object states)
    await session.merge(uw)


# ------------------------------------------------------------------
# Runner / daemon
# ------------------------------------------------------------------
async def run_once(window_seconds: int = WINDOW_SECONDS) -> None:
    """Run one aggregator pass."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(seconds=2 * window_seconds)

    # AsyncSessionLocal is an async_sessionmaker; at runtime this is valid.
    async with AsyncSessionLocal() as session:  # type: ignore[reportGeneralTypeIssues]
        events = await fetch_raw_events(session, since)
        if not events:
            print(f"No raw events found in window: {since.isoformat()}")
            return

        # Group events by (user_id, window_start)
        groups: Dict[Tuple[str, datetime], List[RawEvent]] = {}
        for ev in events:
            ts = getattr(ev, "timestamp", None)
            if not isinstance(ts, datetime):
                continue
            wstart = floor_to_window(ts)
            uid = getattr(ev, "user_id", None)
            if uid is None:
                continue
            if not isinstance(uid, str):
                uid = str(uid)
            key: Tuple[str, datetime] = (uid, wstart)
            groups.setdefault(key, []).append(ev)

        print(f"Found {len(groups)} user-windows to aggregate.")

        for (uid, wstart), evs in groups.items():
            row = aggregate_events_to_row(evs)
            if row:
                await upsert_user_window(session, row)

        # commit all changes
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.exception("Aggregator commit failed: %s", exc)
            raise
        print(f"Aggregated {len(events)} raw events into {len(groups)} user_windows.")


async def run_daemon(interval_sec: int = 60) -> None:
    print("Starting aggregator daemon (Ctrl+C to stop)")
    while True:
        try:
            await run_once()
        except Exception as e:
            logger.exception("Aggregator run failed: %s", e)
        await asyncio.sleep(interval_sec)


# CLI entry
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="GeoAware aggregator")
    parser.add_argument("--once", action="store_true", help="Run one aggregation pass and exit")
    parser.add_argument("--interval", type=int, default=60, help="Daemon interval in seconds")
    args = parser.parse_args()

    if args.once:
        asyncio.run(run_once())
    else:
        try:
            asyncio.run(run_daemon(interval_sec=args.interval))
        except KeyboardInterrupt:
            print("Stopped by user")
