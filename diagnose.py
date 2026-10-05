#!/usr/bin/env python3
"""Quick live check of the tracker's search code on a few legs. Writes data/diagnostics.txt.

Pushing a change to this file runs it once on GitHub (see .github/workflows/track.yml);
it can also be started from the Actions tab with mode "diagnose".
"""
# Check 11: what does Google show for the regional routes on a week of days?

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
    import collections
    for code in ("ACC", "LBV", "DLA", "SSG", "ADD", "IST", "CMN"):
        for direction in ("out", "in"):
            summary = []
            for k in range(7):
                d = day + dt.timedelta(days=k)
                a, b = ("COO", code) if direction == "out" else (code, "COO")
                try:
                    its, _ = tracker.search_itineraries(a, b, d, settings, None)
                    kinds = collections.Counter(
                        tracker.classify(i)[0] + ("" if tracker.classify(i)[0] == "nonstop" else "@" + tracker.classify(i)[1])
                        for i in its)
                    cheapest_direct = min((i["price"] for i in its if tracker.classify(i)[0] in ("nonstop", "same-plane")), default=None)
                    summary.append(f"{d:%a}: {len(its)} [{', '.join(f'{k_}x{v}' for k_, v in kinds.most_common(3))}] direct={cheapest_direct}")
                except Exception as e:
                    summary.append(f"{d:%a}: ERROR {e}")
                time.sleep(1.5)
            lines.append(f"{code} {direction}: " + " | ".join(summary))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
