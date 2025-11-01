# backend/routes.py
"""
Routes for EnVital GeoAware backend:
- POST /ingest_event
- GET  /points
- GET  /city_heatmap
"""
from typing import Optional, List, Any, Dict
from uuid import uuid4
from datetime import datetime
import logging

from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, Field

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_async_session
from backend.models import RawEvent, UserWindow

# Use both H3 basic_int and basic_str to be robust (tile_id may be stored as int-like or str)
import h3.api.basic_int as h3_int
import h3.api.basic_str as h3_str

router = APIRouter()
logger = logging.getLogger("uvicorn.error")

# ----------------------
# Small safe-helpers for conversions (silence Pylance & robust at runtime)
# ----------------------
def _safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def _safe_int(x: Any, default: int = 0) -> int:
    if x is None:
        return default
    try:
        return int(x)
    except Exception:
        try:
            return int(float(x))
        except Exception:
            return default


# ----------------------
# H3 helper: accept int or str tile_id and return GeoJSON Polygon
# ----------------------
def h3_to_polygon_geojson(h3_index: Any) -> Dict:
    """
    Convert an H3 index (int or string) to GeoJSON polygon with coordinates [lon, lat].
    Tries:
      1) if integer-like -> use basic_int.h3_to_geo_boundary
      2) if string-like -> use basic_str.h3_to_geo_boundary
    Raises an Exception if conversion fails (caller should handle/log).
    """
    # attempt integer path
    try:
        if isinstance(h3_index, str):
            h3_s = h3_index.strip()
            # decimal digits -> pass to int API
            if h3_s.isdigit():
                raw = int(h3_s)
                boundary = h3_int.h3_to_geo_boundary(raw, geo_json=True)
            else:
                # not pure digits: try string API
                boundary = h3_str.h3_to_geo_boundary(h3_s, geo_json=True)
        elif isinstance(h3_index, (int,)):
            boundary = h3_int.h3_to_geo_boundary(h3_index, geo_json=True)
        else:
            # unknown type: try both liberally
            try:
                boundary = h3_int.h3_to_geo_boundary(int(h3_index), geo_json=True)
            except Exception:
                boundary = h3_str.h3_to_geo_boundary(str(h3_index), geo_json=True)

        # boundary is list of [lat, lon]
        coords = [[lng, lat] for lat, lng in boundary]
        coords.append(coords[0])
        return {"type": "Polygon", "coordinates": [coords]}

    except Exception as e:
        # include type info for easier debugging in logs
        logger.exception("Failed to convert H3 index to polygon: %s (type=%s): %s", h3_index, type(h3_index), e)
        raise


# ----------------------
# Pydantic model for ingest
# ----------------------
class IngestEvent(BaseModel):
    id: Optional[str] = Field(None, description="Client-supplied UUID string (optional)")
    timestamp: str  # ISO8601 expected
    user_id: str
    hr: Optional[int] = None
    spo2: Optional[int] = None
    steps: Optional[int] = None
    lat: float
    lon: float
    tile_id: Optional[str] = None  # accept str; aggregator may accept int too
    ambient_temp: Optional[float] = None
    humidity: Optional[float] = None
    noise: Optional[float] = None
    aqi: Optional[float] = None


# ----------------------
# Ingest endpoint
# ----------------------
@router.post("/ingest_event", status_code=status.HTTP_201_CREATED)
async def ingest_event(event: IngestEvent, session: AsyncSession = Depends(get_async_session)):
    """
    Insert incoming event into raw_events table.
    """
    eid = event.id or str(uuid4())

    # parse ISO timestamp (support 'Z')
    try:
        parsed_ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(status_code=400, detail="timestamp must be ISO8601 (e.g. 2025-11-01T15:49:00Z)")

    row = {
        "id": eid,
        "timestamp": parsed_ts,
        "user_id": event.user_id,
        "hr": event.hr,
        "spo2": event.spo2,
        "steps": event.steps,
        "lat": event.lat,
        "lon": event.lon,
        "tile_id": event.tile_id,
        "ambient_temp": event.ambient_temp,
        "humidity": event.humidity,
        "noise": event.noise,
        "aqi": event.aqi,
    }

    try:
        stmt = RawEvent.__table__.insert().values(**row)
        await session.execute(stmt)
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.exception("Failed to insert raw event: %s", e)
        raise HTTPException(status_code=500, detail="DB insert failed")

    return {"status": "ok", "id": eid}


# ----------------------
# /points endpoint: return recent user_windows as GeoJSON Point features
# ----------------------
@router.get("/points")
async def points(
    bbox: Optional[str] = Query(None, description="optional bbox: min_lon,min_lat,max_lon,max_lat"),
    limit: int = Query(1000, ge=1, le=5000),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Returns user_windows as GeoJSON Points using lat_mean/lon_mean.
    """
    stmt = select(UserWindow).where(UserWindow.lat_mean.isnot(None), UserWindow.lon_mean.isnot(None))

    if bbox:
        try:
            min_lon, min_lat, max_lon, max_lat = [float(x.strip()) for x in bbox.split(",")]
            stmt = stmt.where(
                (UserWindow.lon_mean >= min_lon)
                & (UserWindow.lon_mean <= max_lon)
                & (UserWindow.lat_mean >= min_lat)
                & (UserWindow.lat_mean <= max_lat)
            )
        except Exception:
            raise HTTPException(status_code=400, detail="bbox must be min_lon,min_lat,max_lon,max_lat")

    stmt = stmt.order_by(UserWindow.window_start.desc()).limit(limit)
    res = await session.execute(stmt)
    rows = list(res.scalars().all())  # concrete list for typing

    features = []
    for r in rows:
        lat = _safe_float(getattr(r, "lat_mean", None))
        lon = _safe_float(getattr(r, "lon_mean", None))
        if lat is None or lon is None:
            continue

        props = {
            "id": getattr(r, "id", None),
            "user_id": getattr(r, "user_id", None),
            "hr_mean": _safe_float(getattr(r, "hr_mean", None)),
            "spo2_mean": _safe_float(getattr(r, "spo2_mean", None)),
            "steps_sum": _safe_int(getattr(r, "steps_sum", None), default=0),
            "window_start": getattr(r, "window_start").isoformat() if getattr(r, "window_start", None) is not None else None,
        }

        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                "properties": props,
            }
        )

    return {"type": "FeatureCollection", "features": features}


# ----------------------
# /city_heatmap endpoint: aggregate by tile_id and return H3 polygons (GeoJSON)
# ----------------------
@router.get("/city_heatmap")
async def city_heatmap(
    resolution: int = Query(8, description="H3 resolution (tile_id stored in user_windows should match)"),
    limit: int = Query(1000, ge=1, le=10000),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Aggregate user_windows by tile_id and return GeoJSON polygons.
    Robust to tile_id stored as integer-like or string.
    """
    stmt = (
        select(
            UserWindow.tile_id,
            func.count().label("count"),
            func.avg(UserWindow.hr_mean).label("avg_hr"),
            func.avg(UserWindow.spo2_mean).label("avg_spo2"),
            func.avg(UserWindow.lat_mean).label("centroid_lat"),
            func.avg(UserWindow.lon_mean).label("centroid_lon"),
        )
        .where(UserWindow.tile_id.isnot(None))
        .group_by(UserWindow.tile_id)
        .limit(limit)
    )

    res = await session.execute(stmt)
    rows = res.all()  # list of Row tuples

    features = []
    for rec in rows:
        # defensive unpacking
        try:
            tile_id, count, avg_hr, avg_spo2, centroid_lat, centroid_lon = rec
        except Exception:
            # fallback if rec is mapping-like
            tile_id = rec[0]
            count = rec[1] if len(rec) > 1 else None
            avg_hr = rec[2] if len(rec) > 2 else None
            avg_spo2 = rec[3] if len(rec) > 3 else None
            centroid_lat = rec[4] if len(rec) > 4 else None
            centroid_lon = rec[5] if len(rec) > 5 else None

        if tile_id is None:
            continue

        # attempt to build polygon; if fails we log and skip
        try:
            polygon = h3_to_polygon_geojson(tile_id)
        except Exception:
            # already logged in helper
            continue

        count_i = _safe_int(count, default=0)
        avg_hr_f = _safe_float(avg_hr)
        avg_spo2_f = _safe_float(avg_spo2)
        centroid_lat_f = _safe_float(centroid_lat)
        centroid_lon_f = _safe_float(centroid_lon)

        props: Dict[str, Any] = {
            "h3_index": str(tile_id),
            "resolution": resolution,
            "count": count_i,
            "avg_hr": avg_hr_f,
            "avg_spo2": avg_spo2_f,
            "centroid_lat": centroid_lat_f,
            "centroid_lon": centroid_lon_f,
        }
        features.append({"type": "Feature", "geometry": polygon, "properties": props})

    return {"type": "FeatureCollection", "features": features}
