# models.py
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Index, JSON, UniqueConstraint
)
from sqlalchemy.sql import func
from .database import Base

# ---------- Raw incoming events ----------
class RawEvent(Base):
    __tablename__ = "raw_events"

    # We accept an explicit ID from client (UUID string) for traceability
    id = Column(String, primary_key=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)

    hr = Column(Integer)      # can be null if device missed reading
    spo2 = Column(Integer)    # same
    steps = Column(Integer)

    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    tile_id = Column(String, index=True)   # H3 index computed at ingest (res 8 default)

    # raw environmental sensors (optional in some events)
    ambient_temp = Column(Float, nullable=True)
    humidity = Column(Float, nullable=True)
    noise = Column(Float, nullable=True)
    aqi = Column(Float, nullable=True)

    ingested_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # helpful single-column indexes
    __table_args__ = (
        Index("ix_raw_events_user_ts", "user_id", "timestamp"),
        Index("ix_raw_events_tile_ts", "tile_id", "timestamp"),
    )


# ---------- Aggregated User Windows ----------
class UserWindow(Base):
    __tablename__ = "user_windows"

    # Keep an explicit string id (UUID) if you prefer; we also enforce uniqueness on user+window.
    id = Column(String, primary_key=True)

    # core identifiers
    user_id = Column(String, nullable=False, index=True)
    window_start = Column(DateTime(timezone=True), nullable=False, index=True)
    window_end = Column(DateTime(timezone=True), nullable=False)

    # aggregated user vitals (common)
    hr_mean = Column(Float, nullable=True)
    hr_std = Column(Float, nullable=True)
    spo2_mean = Column(Float, nullable=True)
    spo2_min = Column(Float, nullable=True)
    steps_sum = Column(Integer, nullable=True)

    # centroid / location & h3 tile
    lat_mean = Column(Float, nullable=True)
    lon_mean = Column(Float, nullable=True)
    tile_id = Column(String, index=True)  # H3 index computed at aggregation time

    # aggregated environment metrics (optional)
    ambient_temp_mean = Column(Float, nullable=True)
    humidity_mean = Column(Float, nullable=True)
    noise_mean = Column(Float, nullable=True)
    aqi_mean = Column(Float, nullable=True)
    heat_index_mean = Column(Float, nullable=True)

    # rolling baseline features you mentioned
    baseline_hr_hour = Column(Float, nullable=True)
    baseline_spo2 = Column(Float, nullable=True)

    # fields to store anomaly engine outputs & meta (Mehul's stage will write to these)
    anomaly_score = Column(Float, nullable=True)        # continuous score
    anomaly_flags = Column(JSON, nullable=True)         # e.g. {"hr": true, "aqi": false}
    meta = Column(JSON, nullable=True)                  # general metadata: {"event_count": 12, "device_id": "xxx"}

    # Composite uniqueness: one window per user
    __table_args__ = (
        UniqueConstraint("user_id", "window_start", name="uq_user_window_user_windowstart"),
        Index("ix_user_windows_user_window", "user_id", "window_start"),
        Index("ix_user_windows_tile_window", "tile_id", "window_start"),
    )
