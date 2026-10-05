#!/usr/bin/env python3
"""Diagnose why Google Flights searches fail. Writes data/diagnostics.txt."""
# Run 3: why do round-trip searches return 0 itineraries?

from __future__ import annotations

import datetime as dt
import importlib.metadata as md
import json
import re
import traceback
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data" / "diagnostics.txt"
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    lines.append(s)


def shape(x, depth=0, maxd=3):
    if depth >= maxd:
        return type(x).__name__
    if isinstance(x, list):
        return "[" + ", ".join(shape(i, depth + 1, maxd) for i in x[:12]) + (", …" if len(x) > 12 else "") + f"]#{len(x)}"
    if isinstance(x, str):
        return repr(x[:20])
    return repr(x)


def payload_of(html: str):
    m = re.search(r'<script[^>]*class="ds:1"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    js = m.group(1)
    data = js.split("data:", 1)[1].rsplit(",", 1)[0]
    try:
        return json.loads(data)
    except Exception as e:
        log("  json failed:", e, data[-200:])
        return None


def main() -> None:
    log("Diagnostics", dt.datetime.utcnow().isoformat(timespec="seconds"), "UTC")
    for pkg in ("fast-flights", "primp"):
        log(f"{pkg}: {md.version(pkg)}")

    from fast_flights import FlightQuery, Passengers, create_query, get_flights
    from fast_flights.fetcher import fetch_flights_html

    d1 = dt.date.today() + dt.timedelta(days=30)
    d2 = d1 + dt.timedelta(days=14)

    def q(dest, trip="round-trip", **kw):
        legs = [FlightQuery(date=d1.isoformat(), from_airport="COO", to_airport=dest)]
        if trip == "round-trip":
            legs.append(FlightQuery(date=d2.isoformat(), from_airport=dest, to_airport="COO"))
        return create_query(flights=legs, trip=trip, seat="economy",
                            passengers=Passengers(adults=1), language="en", currency="EUR", **kw)

    variants = [
        ("RT CDG plain", q("CDG")),
        ("RT CDG max_stops=1", q("CDG", max_stops=1)),
        ("RT CDG hide_separate", q("CDG", hide_separate_and_self_transfer=True)),
        ("OW CDG plain", q("CDG", trip="one-way")),
        ("OW BRU max_stops=1", q("BRU", trip="one-way", max_stops=1)),
        ("OW IST max_stops=1", q("IST", trip="one-way", max_stops=1)),
    ]
    for label, query in variants:
        log(f"\n== {label}")
        log("  url:", query.url())
        try:
            html = fetch_flights_html(query)
            p = payload_of(html)
            if p is None:
                log("  no ds:1 payload; title:", re.search(r"<title>(.*?)</title>", html).group(1) if "<title>" in html else None)
                continue
            log("  top-level:", shape(p, maxd=1))
            for i in range(min(len(p), 12)):
                if p[i] is not None:
                    log(f"  p[{i}]:", shape(p[i], maxd=3)[:400])
            try:
                from fast_flights.parser import parse_js
                m = re.search(r'<script[^>]*class="ds:1"[^>]*>(.*?)</script>', html, re.S)
                res = parse_js(m.group(1))
                log(f"  parsed: {len(res)} itineraries; cheapest:",
                    sorted(r.price for r in res if r.price)[:4])
            except Exception as e:
                log("  parse error:", type(e).__name__, e)
        except Exception:
            log("  FAILED:\n" + traceback.format_exc(limit=4))

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
