#!/usr/bin/env python3
"""Deribit hourly snapshot (GitHub Actions).

GitHub's scheduler is often 30-60 min late, so each run does two things:
  1. If the hour that has already begun is not captured yet, fetch it now and flag it
     late (late_seconds = how far past the top of the hour we are).
  2. Wait until the next top-of-hour (UTC) and fetch it on time.
Both are skipped if that hour's meta.json already exists (another run got it).
Files: data/YYYY-MM-DD/HH_<CUR>_<kind>.json.gz + HH_meta.json; late ones also in data/late.log.
"""
import gzip, json, os, time, urllib.request
from datetime import datetime, timezone, timedelta

BASE = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
JOBS = [("BTC", "option"), ("BTC", "future"), ("ETH", "option"), ("ETH", "future")]
LATE_SECONDS = 60
MAX_WAIT = 65 * 60
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def now():
    return datetime.now(timezone.utc)

def fetch(cur, kind, tries=8):
    url = f"{BASE}?currency={cur}&kind={kind}"
    for k in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "deribit-snapshots/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                b = r.read()
            if len(b) < 1000:
                raise ValueError("response too small")
            return b
        except Exception as e:  # noqa: BLE001
            print(f"  {cur} {kind} attempt {k} failed: {e}", flush=True)
            time.sleep(min(60, 5 * k))
    raise RuntimeError(f"{cur} {kind}: all attempts failed")

def capture(tgt, t0):
    day = tgt.strftime("%Y-%m-%d"); hh = tgt.strftime("%H")
    outdir = os.path.join(ROOT, day); os.makedirs(outdir, exist_ok=True)
    meta_path = os.path.join(outdir, f"{hh}_meta.json")
    if os.path.exists(meta_path):
        print(f"{day} {hh}:00 already captured", flush=True); return False
    t_start = now(); files = {}
    for cur, kind in JOBS:
        b = fetch(cur, kind)
        name = f"{hh}_{cur}_{kind}.json.gz"
        with gzip.open(os.path.join(outdir, name), "wb") as f:
            f.write(b)
        files[name] = len(b)
    t_end = now(); late_s = (t_start - tgt).total_seconds()
    meta = {"target_utc": tgt.isoformat(), "trigger_utc": t0.isoformat(),
            "fetch_start_utc": t_start.isoformat(), "fetch_end_utc": t_end.isoformat(),
            "late_seconds": round(late_s, 1), "late": late_s > LATE_SECONDS,
            "files": files, "source": "github-actions"}
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=1)
    if meta["late"]:
        with open(os.path.join(ROOT, "late.log"), "a") as f:
            f.write(f"{tgt.isoformat()} fetched {late_s:.0f}s late (trigger {t0.isoformat()})\n")
    print(f"captured {day} {hh}:00  late_s={late_s:.1f}{'  LATE' if meta['late'] else ''}", flush=True)
    return True

def main():
    t0 = now()
    this_hour = t0.replace(minute=0, second=0, microsecond=0)
    next_hour = this_hour + timedelta(hours=1)
    print(f"triggered {t0.isoformat()}", flush=True)
    # 1. backfill the hour already begun (flagged late) if nobody captured it;
    #    a failure here (e.g. Deribit 503) must not stop the on-time capture below
    try:
        capture(this_hour, t0)
    except Exception as e:  # noqa: BLE001
        print(f"backfill of {this_hour.isoformat()} failed: {e}", flush=True)
    # 2. wait for the next top of hour and capture it on time
    wait = (next_hour - now()).total_seconds()
    if 0 < wait <= MAX_WAIT:
        print(f"waiting {wait:.0f}s for {next_hour.isoformat()}", flush=True)
        time.sleep(wait)
        capture(next_hour, t0)
    print("done", flush=True)

if __name__ == "__main__":
    main()
