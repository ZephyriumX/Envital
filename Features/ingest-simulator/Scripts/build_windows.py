#!/usr/bin/env python3
import os, uuid
from datetime import datetime, timedelta, timezone
import pandas as pd
from sqlalchemy import text, create_engine

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./envital.db")
engine = create_engine(DB_URL)

WINDOW_MINUTES = 10

def build_windows():
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=WINDOW_MINUTES)
    print(f"Building windows for {start:%Y-%m-%d %H:%M} → {now:%H:%M}")

    q = f"""
    SELECT user_id,
           MIN(timestamp) AS window_start,
           MAX(timestamp) AS window_end,
           AVG(hr) AS hr_mean,
           STDDEV(hr) AS hr_std,
           AVG(spo2) AS spo2_mean,
           MIN(spo2) AS spo2_min,
           SUM(steps) AS steps_sum,
           AVG(lat) AS lat_mean,
           AVG(lon) AS lon_mean,
           MAX(tile_id) AS tile_id,
           AVG(ambient_temp) AS ambient_temp_mean,
           AVG(humidity) AS humidity_mean,
           AVG(aqi) AS aqi_mean,
           AVG(noise_db) AS noise_mean
    FROM raw_events
    WHERE timestamp >= :start AND timestamp < :end
    GROUP BY user_id
    """
    df = pd.read_sql(text(q), engine, params={"start": start, "end": now})
    if df.empty:
        print("No new data in this window.")
        return

    df["id"] = [str(uuid.uuid4()) for _ in range(len(df))]
    df.to_sql("user_windows", engine, if_exists="append", index=False)
    print(f"Inserted {len(df)} aggregated windows.")

if __name__ == "__main__":
    build_windows()
