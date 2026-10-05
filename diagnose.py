#!/usr/bin/env python3
"""Quick live check of the tracker's search code on a few legs. Writes data/diagnostics.txt.

Pushing a change to this file runs it once on GitHub (see .github/workflows/track.yml);
it can also be started from the Actions tab with mode "diagnose".
"""
# Check 8: flight-number classification; why does Amsterdam via Paris find nothing?

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
    for label, kw in [("AMS out, via CDG 120-360", dict(connecting_airports=["CDG"], min_layover_minutes=120, max_layover_minutes=360)),
                      ("AMS out, via CDG only", dict(connecting_airports=["CDG"])),
                      ("AMS out, no filters", {}),
                      ("BRU out, no filters", {})]:
        dest = label[:3]
        q = create_query(flights=[FlightQuery(date=day.isoformat(), from_airport="COO", to_airport=dest, **kw)],
                         trip="one-way", seat="economy", passengers=Passengers(adults=1),
                         language="en", currency="EUR", max_stops=1)
        lines.append(f"\n== {label}")
        try:
            its = tracker.parse_itineraries(fetch_flights_html(q))
            lines.append(f"  {None if its is None else len(its)} itineraries")
            for it in sorted(its or [], key=lambda x: x["price"] or 9e9)[:8]:
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
