#!/usr/bin/env python3
import time
import random
import uuid
import json
import argparse
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
from urllib import request, error
import math


@dataclass
class UserProfile:
    user_id: str
    hr_base: int = 72
    hr_sigma: float = 4.5
    spo2_base: int = 97
    spo2_sigma: float = 0.8
    lat0: float = 28.6139   # Delhi-ish
    lon0: float = 77.2090
    step_rate_per_interval: int = 12  # avg steps per tick during light activity


def _bounded_int(val: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(val))))


def _jitter(val: float, sigma: float) -> float:
    return random.gauss(val, sigma)


def _rand_walk(prev: float, step_sigma: float, min_v: float, max_v: float) -> float:
    nxt = prev + random.gauss(0, step_sigma)
    return max(min_v, min(max_v, nxt))


def _gps_drift(lat: float, lon: float, meters: float = 10.0) -> tuple[float, float]:
    dlat = (meters / 111000.0) * random.uniform(-1, 1)
    dlon = (meters / (111000.0 * math.cos(math.radians(lat) + 1e-6))) * random.uniform(-1, 1)
    return lat + dlat, lon + dlon


def generate_event(ts: datetime, profile: UserProfile, prev_hr: Optional[float]) -> Dict:
    # Random walk around baseline for more realistic continuity
    if prev_hr is None:
        hr_val = _bounded_int(_jitter(profile.hr_base, profile.hr_sigma), 50, 140)
    else:
        hr_val = _bounded_int(_rand_walk(prev_hr, step_sigma=1.5, min_v=48, max_v=150), 48, 150)

    spo2_val = _bounded_int(_jitter(profile.spo2_base, profile.spo2_sigma), 90, 99)
    # steps for this interval: mostly low, sometimes little bursts
    steps = max(0, int(random.gauss(profile.step_rate_per_interval, 8)))
    lat, lon = _gps_drift(profile.lat0, profile.lon0, meters=random.uniform(2, 25))

    return {
        "id": str(uuid.uuid4()),
        "timestamp": ts.replace(microsecond=0).isoformat() + "Z",  # UTC ISO8601
        "user_id": profile.user_id,
        "hr": hr_val,
        "spo2": spo2_val,
        "steps": steps,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
    }


def inject_anomaly(evt: Dict, kind: str) -> Dict:
    """Mutate the event to simulate an anomaly."""
    e = dict(evt)
    if kind == "hr_spike":
        e["hr"] = min(170, evt["hr"] + random.randint(25, 55))
    elif kind == "spo2_drop":
        e["spo2"] = max(85, evt["spo2"] - random.randint(5, 10))
    elif kind == "tachy_low_spo2":
        e["hr"] = min(165, evt["hr"] + random.randint(20, 40))
        e["spo2"] = max(88, evt["spo2"] - random.randint(3, 7))
    return e


def post_event(url: str, event: Dict, timeout: float = 2.5) -> bool:
    payload = json.dumps(event).encode("utf-8")
    req = request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except error.URLError:
        return False


def stream(
    num_users: int,
    interval_sec: int,
    duration_min: float,
    outfile: Optional[str],
    post_url: Optional[str],
    anomaly_every: Optional[int],
    anomaly_kind: str,
    quiet: bool,
):
    # Create user profiles with subtle baseline diversity
    profiles: List[UserProfile] = []
    for i in range(num_users):
        profiles.append(
            UserProfile(
                user_id=f"user_{i+1}",
                hr_base=random.randint(60, 80),
                hr_sigma=random.uniform(3.0, 6.0),
                spo2_base=random.randint(96, 98),
                spo2_sigma=random.uniform(0.5, 1.2),
                lat0=28.55 + random.uniform(0.01, 0.12),
                lon0=77.10 + random.uniform(0.01, 0.12),
                step_rate_per_interval=random.randint(5, 20),
            )
        )

    start = datetime.utcnow()
    end = start + timedelta(minutes=duration_min)

    f = open(outfile, "w") if outfile else None
    prev_hr_map: Dict[str, Optional[float]] = {p.user_id: None for p in profiles}
    count = 0

    try:
        now = start
        while now < end:
            for p in profiles:
                evt = generate_event(now, p, prev_hr_map[p.user_id])

                # anomaly injection cadence
                count += 1
                to_send = evt
                injected = False
                if anomaly_every and count % anomaly_every == 0:
                    to_send = inject_anomaly(evt, anomaly_kind)
                    injected = True

                line = json.dumps(to_send)
                # write to file or stdout
                if f:
                    f.write(line + "\n")
                elif not quiet:
                    print(line, flush=True)

                # optional POST to API
                if post_url:
                    ok = post_event(post_url, to_send)
                    if not ok and not quiet:
                        print(f"[warn] POST failed for event {to_send.get('id')}", flush=True)

                # update prev HR using the actual (possibly anomalous) value
                prev_hr_map[p.user_id] = to_send["hr"]

            now += timedelta(seconds=interval_sec)
            time.sleep(interval_sec)

    finally:
        if f:
            f.close()


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Envital Wearable Data Simulator")
    ap.add_argument("--users", type=int, default=5, help="number of simulated users")
    ap.add_argument("--interval", type=int, default=5, help="seconds between ticks")
    ap.add_argument("--minutes", type=float, default=1, help="duration to run (minutes, can be float)")
    ap.add_argument("--out", type=str, default=None, help="write JSONL to file (else stdout)")
    ap.add_argument("--post-url", type=str, default=None, help="POST each event to an API URL, e.g., http://localhost:8000/api/ingest_event")
    ap.add_argument("--anomaly-every", type=int, default=0, help="inject an anomaly every N events (0 disables)")
    ap.add_argument("--anomaly-kind", type=str, default="hr_spike", choices=["hr_spike", "spo2_drop", "tachy_low_spo2"], help="type of anomaly to inject")
    ap.add_argument("--quiet", action="store_true", help="suppress stdout printing")
    return ap.parse_args()


if __name__ == "__main__":
    args = parse_args()
    stream(
        num_users=args.users,
        interval_sec=args.interval,
        duration_min=args.minutes,
        outfile=args.out,
        post_url=args.post_url,
        anomaly_every=(args.anomaly_every if args.anomaly_every and args.anomaly_every > 0 else None),
        anomaly_kind=args.anomaly_kind,
        quiet=args.quiet,
    )
