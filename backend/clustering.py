# backend/clustering.py
from fastapi import APIRouter, Query, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any
import numpy as np
from sklearn.cluster import DBSCAN
import math
import json

from backend.database import get_async_session
from backend.models import UserWindow  # ensure correct import path

router = APIRouter()

EARTH_RADIUS_M = 6371000.0

def haversine_radians(lat1, lon1, lat2, lon2):
    """
    Haversine distance between arrays of radians. Not used directly here.
    """
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2.0)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2.0)**2
    c = 2 * np.arcsin(np.minimum(1, np.sqrt(a)))
    return EARTH_RADIUS_M * c

@router.get("/clusters")
async def clusters(
    # bbox optional to limit region: min_lon,min_lat,max_lon,max_lat
    bbox: str = Query(None, description="optional bbox: min_lon,min_lat,max_lon,max_lat"),
    eps_meters: int = Query(200, description="cluster radius in meters"),
    min_samples: int = Query(3, description="minimum points to form a cluster"),
    only_anomalous: bool = Query(False, description="only include windows with anomaly_score>threshold"),
    anomaly_threshold: float = Query(0.5, description="threshold for anomaly_score when only_anomalous=True"),
    limit: int = Query(5000, description="max points to fetch from DB (safety)"),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Return GeoJSON FeatureCollection of clusters computed by DBSCAN (haversine metric).
    Each cluster feature properties include: cluster_id, count, avg_anomaly_score, sum_steps, etc.
    Noise points are returned as cluster_id = -1 (optionally excluded by client).
    """

    # Build DB query for user_windows with lat/lon not null
    stmt = select(UserWindow).where(UserWindow.lat_mean.isnot(None), UserWindow.lon_mean.isnot(None)).limit(limit)

    # Apply bbox filter if provided
    if bbox:
        try:
            min_lon, min_lat, max_lon, max_lat = [float(x.strip()) for x in bbox.split(",")]
            stmt = stmt.where(
                (UserWindow.lon_mean >= min_lon) &
                (UserWindow.lon_mean <= max_lon) &
                (UserWindow.lat_mean >= min_lat) &
                (UserWindow.lat_mean <= max_lat)
            )
        except Exception:
            raise HTTPException(status_code=400, detail="bbox must be min_lon,min_lat,max_lon,max_lat")

    rows = (await session.execute(stmt)).scalars().all()
    points = []
    for r in rows:
        points.append({
            "id": r.id,
            "lat": r.lat_mean,
            "lon": r.lon_mean,
            "anomaly_score": r.anomaly_score or 0.0,
            "metrics": r.meta or {},
            "steps": r.steps_sum or 0,
        })

    if not points:
        return {"type": "FeatureCollection", "features": []}

    # Optionally filter by anomaly threshold
    if only_anomalous:
        points = [p for p in points if p["anomaly_score"] >= anomaly_threshold]
        if not points:
            return {"type": "FeatureCollection", "features": []}

    # Convert to numpy array in radians for haversine metric required by sklearn
    coords = np.array([[math.radians(p["lat"]), math.radians(p["lon"])] for p in points]) # type: ignore

    # DBSCAN with haversine metric: eps must be in radians (meters -> radians = meters / EarthRadius)
    eps_rad = eps_meters / EARTH_RADIUS_M
    clustering = DBSCAN(eps=eps_rad, min_samples=max(1, min_samples), metric="haversine")
    labels = clustering.fit_predict(coords)  # labels: -1 for noise

    # Aggregate clusters
    clusters: Dict[int, Dict[str, Any]] = {}
    for idx, label in enumerate(labels):
        label = int(label)
        pt = points[idx]
        if label not in clusters:
            clusters[label] = {
                "count": 0,
                "sum_steps": 0,
                "anomaly_scores": [],
                "ids": [],
                "lat_sum": 0.0,
                "lon_sum": 0.0,
            }
        c = clusters[label]
        c["count"] += 1
        c["sum_steps"] += pt["steps"]
        c["anomaly_scores"].append(pt["anomaly_score"])
        c["ids"].append(pt["id"])
        c["lat_sum"] += pt["lat"]
        c["lon_sum"] += pt["lon"]

    # Build GeoJSON features
    features = []
    for label, c in clusters.items():
        centroid_lat = c["lat_sum"] / c["count"]
        centroid_lon = c["lon_sum"] / c["count"]
        avg_an = sum(c["anomaly_scores"]) / len(c["anomaly_scores"]) if c["anomaly_scores"] else 0.0
        props = {
            "cluster_id": label,
            "count": c["count"],
            "average_anomaly_score": avg_an,
            "sum_steps": c["sum_steps"],
            "member_ids": c["ids"],
        }
        # cluster geometry: use centroid point
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [centroid_lon, centroid_lat]},
            "properties": props
        })

    # Optionally include noise points separately (label == -1) — currently included
    return {"type": "FeatureCollection", "features": features}
