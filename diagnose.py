#!/usr/bin/env python3
"""Quick live check of the tracker's search code on a few legs. Writes data/diagnostics.txt.

Pushing a change to this file runs it once on GitHub (see .github/workflows/track.yml);
it can also be started from the Actions tab with mode "diagnose".
"""
# Check 9: Amsterdam on several days / any stops; Brussels on Saturdays; Paris CDG

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
    # Amsterdam: list everything Google returns, with and without the via/layover filters
    from fast_flights import FlightQuery, Passengers, create_query
    from fast_flights.fetcher import fetch_flights_html
    sat = day + dt.timedelta(days=(5 - day.weekday()) % 7)
    cases = []
    for k in range(3):
        dd = day + dt.timedelta(days=k * 3)
        cases += [(f"AMS out {dd} any stops", "COO", "AMS", dd, None),
                  (f"AMS in {dd} any stops", "AMS", "COO", dd, None)]
    cases += [(f"BRU out {sat} (Sat)", "COO", "BRU", sat, 1), (f"BRU in {sat + dt.timedelta(days=21)} (Sat)", "BRU", "COO", sat + dt.timedelta(days=21), 1),
              (f"CDG out {day}", "COO", "CDG", day, 1), (f"CDG->AMS {day + dt.timedelta(days=1)}", "CDG", "AMS", day + dt.timedelta(days=1), 0)]
    for label, a_, b_, dd, ms in cases:
        kw = {}
        q = create_query(flights=[FlightQuery(date=dd.isoformat(), from_airport=a_, to_airport=b_, **kw)],
                         trip="one-way", seat="economy", passengers=Passengers(adults=1),
                         language="en", currency="EUR", max_stops=ms)
        lines.append(f"\n== {label}")
        try:
            its = tracker.parse_itineraries(fetch_flights_html(q))
            lines.append(f"  {None if its is None else len(its)} itineraries")
            for it in sorted(its or [], key=lambda x: x["price"] or 9e9)[:5]:
                kind, via, lay = tracker.classify(it)
                lines.append(f"  {it['price']} {kind} via={via} layover={lay} " + " | ".join(
                    f"{x['carrier']}{x['number']} {x['from']}-{x['to']} {x['dep']:%d %H:%M}-{x['arr']:%H:%M}" for x in it["segs"]))
        except Exception:
            lines.append(traceback.format_exc(limit=4))
        time.sleep(2)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
