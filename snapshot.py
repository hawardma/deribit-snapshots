#!/usr/bin/env python3
"""Deribit hourly snapshot (GitHub Actions).

Triggered at :35 each hour; waits until the next top-of-hour (UTC), then fetches
BTC/ETH option and future book summaries from Deribit's public API and stores them
as data/YYYY-MM-DD/HH_<CUR>_<kind>.json.gz (same naming as the local collector)
plus data/YYYY-MM-DD/HH_meta.json with timing. If the first request starts more than
60 s after the target hour, the snapshot is flagged late=true in meta.json and in
data/late.log. If the trigger itself arrives after the target hour (runner delay),
the fetch runs immediately and is flagged.
"""
import gzip, json, os, sys, time, urllib.request
from datetime import datetime, timezone, timedelta

BASE = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
JOBS = [("BTC", "option"), ("BTC", "future"), ("ETH", "option"), ("ETH", "future")]
LATE_SECONDS = 60
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def now():
    return datetime.now(timezone.utc)

def target_hour(t):
    # Triggered at :35 -> target is the next hour. Triggered after :00 but before :35
    # (delayed runner) -> target is the hour already begun; we are late.
    h = t.replace(minute=0, second=0, microsecond=0)
    return h + timedelta(hours=1) if t.minute >= 35 else h

def fetch(cur, kind):
    url = f"{BASE}?currency={cur}&kind={kind}"
    for k in range(1, 6):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                b = r.read()
            if len(b) < 1000:
                raise ValueError("response too small")
            return b
        except Exception as e:  # noqa: BLE001
            print(f"  {cur} {kind} attempt {k} failed: {e}", flush=True)
            time.sleep(5 * k)
    raise RuntimeError(f"{cur} {kind}: all attempts failed")

def main():
    t0 = now()
    tgt = target_hour(t0)
    day = tgt.strftime("%Y-%m-%d"); hh = tgt.strftime("%H")
    outdir = os.path.join(ROOT, day); os.makedirs(outdir, exist_ok=True)
    meta_path = os.path.join(outdir, f"{hh}_meta.json")
    if os.path.exists(meta_path):
        print(f"{day} {hh}:00 already captured; nothing to do"); return
    wait = (tgt - t0).total_seconds()
    print(f"triggered {t0.isoformat()}  target {tgt.isoformat()}  wait {wait:.0f}s", flush=True)
    if wait > 0:
        time.sleep(wait)
    t_start = now()
    files = {}
    for cur, kind in JOBS:
        b = fetch(cur, kind)
        name = f"{hh}_{cur}_{kind}.json.gz"
        with gzip.open(os.path.join(outdir, name), "wb") as f:
            f.write(b)
        files[name] = len(b)
        print(f"  saved {name} ({len(b):,} bytes raw)", flush=True)
    t_end = now()
    late_s = (t_start - tgt).total_seconds()
    meta = {
        "target_utc": tgt.isoformat(), "trigger_utc": t0.isoformat(),
        "fetch_start_utc": t_start.isoformat(), "fetch_end_utc": t_end.isoformat(),
        "late_seconds": round(late_s, 1), "late": late_s > LATE_SECONDS,
        "files": files, "source": "github-actions",
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=1)
    if meta["late"]:
        with open(os.path.join(ROOT, "late.log"), "a") as f:
            f.write(f"{tgt.isoformat()} fetched {late_s:.0f}s late (trigger {t0.isoformat()})\n")
        print(f"LATE by {late_s:.0f}s", flush=True)
    print("done", flush=True)

if __name__ == "__main__":
    main()
