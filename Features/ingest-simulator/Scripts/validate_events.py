#!/usr/bin/env python3
import json
import sys
from datetime import datetime

REQUIRED = {"timestamp", "user_id", "hr", "spo2", "steps", "lat", "lon"}

def validate_line(obj, i):
    # keys
    missing = REQUIRED - obj.keys()
    assert not missing, f"Line {i}: missing keys: {missing}"
    # types
    assert isinstance(obj["timestamp"], str)
    assert isinstance(obj["user_id"], str)
    for k in ["hr", "spo2", "steps"]:
        assert isinstance(obj[k], int), f"Line {i}: {k} must be int"
    for k in ["lat", "lon"]:
        assert isinstance(obj[k], (int, float)), f"Line {i}: {k} must be number"
    # ranges
    assert 40 <= obj["hr"] <= 200, f"Line {i}: hr out of range"
    assert 80 <= obj["spo2"] <= 100, f"Line {i}: spo2 out of range"
    assert -90 <= obj["lat"] <= 90 and -180 <= obj["lon"] <= 180, f"Line {i}: invalid lat/lon"
    # timestamp
    datetime.fromisoformat(obj["timestamp"].replace("Z", "+00:00"))

def main():
    for i, line in enumerate(sys.stdin, 1):
        if not line.strip():
            continue
        obj = json.loads(line)
        validate_line(obj, i)
    print("OK")

if __name__ == "__main__":
    main()
