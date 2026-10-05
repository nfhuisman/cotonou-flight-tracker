#!/usr/bin/env python3
"""Quick live check of the tracker's search code. Writes data/diagnostics.txt.

Pushing a change to this file runs it once on GitHub (see .github/workflows/track.yml);
it can also be started from the Actions tab with mode "diagnose".
"""
# Check 12: can Addis Ababa / Malabo / Libreville / Amsterdam be reached with other request styles?

from __future__ import annotations

import collections
import datetime as dt
import time
import traceback
import urllib.parse
from pathlib import Path

import tracker

OUT = Path(__file__).resolve().parent / "data" / "diagnostics.txt"


def summarise(its):
    if its is None:
        return "error page"
    kinds = collections.Counter(tracker.classify(i)[0] + ("@" + tracker.classify(i)[1] if tracker.classify(i)[1] else "")
                                for i in its if i["price"])
    cheapest = min((i["price"] for i in its if i["price"]), default=None)
    return f"{len(its)} itineraries, cheapest {cheapest}, kinds {dict(kinds.most_common(4))}"


def main() -> None:
    from fast_flights import FlightQuery, Passengers, create_query
    from fast_flights.fetcher import fetch_flights_html
    from primp import Client

    lines = [f"Live check {dt.datetime.utcnow():%Y-%m-%d %H:%M} UTC"]
    d1 = dt.date.today() + dt.timedelta(days=30)
    d2 = d1 + dt.timedelta(days=14)
    client = Client(impersonate="chrome_145", impersonate_os="macos", referer=True, cookie_store=True)

    def get(params):
        r = client.get("https://www.google.com/travel/flights", params=params)
        return tracker.parse_itineraries(r.text)

    for dest in ("ADD", "SSG", "LBV", "AMS", "BRU"):
        lines.append(f"\n== {dest}")
        for label, fn in [
            ("tfs one-way", lambda: tracker.parse_itineraries(fetch_flights_html(create_query(
                flights=[FlightQuery(date=d1.isoformat(), from_airport="COO", to_airport=dest)],
                trip="one-way", passengers=Passengers(adults=1), language="en", currency="EUR")))),
            ("tfs round-trip", lambda: tracker.parse_itineraries(fetch_flights_html(create_query(
                flights=[FlightQuery(date=d1.isoformat(), from_airport="COO", to_airport=dest),
                         FlightQuery(date=d2.isoformat(), from_airport=dest, to_airport="COO")],
                trip="round-trip", passengers=Passengers(adults=1), language="en", currency="EUR")))),
            ("q one-way", lambda: get({"q": f"Flights from COO to {dest} on {d1} one way", "hl": "en", "curr": "EUR"})),
            ("q round-trip", lambda: get({"q": f"Flights from COO to {dest} on {d1} through {d2}", "hl": "en", "curr": "EUR"})),
            ("q one-way gl=BJ", lambda: get({"q": f"Flights from COO to {dest} on {d1} one way", "hl": "en", "curr": "EUR", "gl": "BJ"})),
            ("q round-trip gl=BJ", lambda: get({"q": f"Flights from COO to {dest} on {d1} through {d2}", "hl": "en", "curr": "EUR", "gl": "BJ"})),
            ("tfs one-way gl=BJ", lambda: get({**create_query(
                flights=[FlightQuery(date=d1.isoformat(), from_airport="COO", to_airport=dest)],
                trip="one-way", passengers=Passengers(adults=1), language="en", currency="EUR").params(), "gl": "BJ"})),
        ]:
            try:
                lines.append(f"  {label}: {summarise(fn())}")
            except Exception as e:
                lines.append(f"  {label}: ERROR {type(e).__name__}: {e}")
            time.sleep(2)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
