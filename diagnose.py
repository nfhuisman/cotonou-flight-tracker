#!/usr/bin/env python3
"""Quick live check of the tracker's search code on a few legs. Writes data/diagnostics.txt.

Pushing a change to this file runs it once on GitHub (see .github/workflows/track.yml);
it can also be started from the Actions tab with mode "diagnose".
"""
# Check 7: one-way legs through tracker.fetch_google

from __future__ import annotations

import datetime as dt
import time
import traceback
from pathlib import Path

import tracker

OUT = Path(__file__).resolve().parent / "data" / "diagnostics.txt"


def main() -> None:
    lines = [f"Live check {dt.datetime.utcnow():%Y-%m-%d %H:%M} UTC"]
    settings, routes = tracker.load_config(tracker.HERE)
    by_code = {r["code"]: r for r in routes}
    day = dt.date.today() + dt.timedelta(days=30)
    checks = [("BRU", "out", day), ("BRU", "in", day + dt.timedelta(days=21)),
              ("AMS", "out", day), ("AMS", "in", day + dt.timedelta(days=28)),
              ("IST", "out", day), ("ABJ", "out", day), ("DSS", "out", day),
              ("SSG", "in", day + dt.timedelta(days=14))]
    for code, direction, d in checks:
        t = time.time()
        try:
            best = tracker.fetch_google(settings.get("origin", "COO"), by_code[code], direction, d, settings)
            lines.append(f"{code} {direction} {d}: {best and {k: best[k] for k in ('price', 'airline', 'kind', 'via')}}"
                         f"  ({time.time() - t:.1f}s)")
        except Exception:
            lines.append(f"{code} {direction} {d}: ERROR\n{traceback.format_exc(limit=4)}")
        time.sleep(2)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
