#!/usr/bin/env python3
"""Diagnose why Google Flights searches fail. Writes data/diagnostics.txt."""
# Run 5: round-trip control (CDG) vs others; what does an empty response contain?

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

    def legs_amd(dest, via=None, lo=None, hi=None):
        kw = {}
        if via:
            kw = dict(connecting_airports=via, min_layover_minutes=lo, max_layover_minutes=hi)
        return [FlightQuery(date=d1.isoformat(), from_airport="COO", to_airport=dest, **kw),
                FlightQuery(date=d2.isoformat(), from_airport=dest, to_airport="COO", **kw)]

    def rt(dest, legs=None, **kw):
        return create_query(flights=legs or legs_amd(dest), trip="round-trip", seat="economy",
                            passengers=Passengers(adults=1), language="en", currency="EUR", **kw)

    def ow(o, dst, date, **kw):
        return create_query(flights=[FlightQuery(date=date.isoformat(), from_airport=o, to_airport=dst)],
                            trip="one-way", seat="economy", passengers=Passengers(adults=1),
                            language="en", currency="EUR", **kw)

    variants = [("RT CDG none (control)", rt("CDG")),
                ("RT BRU none", rt("BRU")),
                ("OW BRU->COO on return date", ow("BRU", "COO", d2)),
                ("OW IST->COO on return date", ow("IST", "COO", d2)),
                ("RT BRU none, EUR off", create_query(flights=legs_amd("BRU"), trip="round-trip", seat="economy",
                                                     passengers=Passengers(adults=1), language="en", currency="")),
                ("RT CDG none (control again)", rt("CDG"))]

    for label, query in variants:
        log(f"\n== {label}")
        import time; time.sleep(2)
        try:
            html = fetch_flights_html(query)
            p = payload_of(html)
            if p is None:
                log("  no ds:1 payload; title:", re.search(r"<title>(.*?)</title>", html).group(1) if "<title>" in html else None)
                continue
            log("  insights p[5][:6]:", p[5][:6] if p[5] else None)
            log("  shape:", " | ".join(f"p[{i}]={shape(p[i], maxd=2)[:160]}" for i in range(min(len(p), 12)) if p[i] is not None))
            txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
            txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", txt))
            for kw_ in ("No results", "no flights", "Try changing", "isn't available", "unavailable"):
                i_ = txt.find(kw_)
                if i_ >= 0:
                    log("  text:", txt[max(0, i_ - 150): i_ + 200])
            try:
                from fast_flights.parser import parse_js
                m = re.search(r'<script[^>]*class="ds:1"[^>]*>(.*?)</script>', html, re.S)
                res = parse_js(m.group(1))
                log(f"  parsed: {len(res)} itineraries; cheapest:",
                    sorted(r.price for r in res if r.price)[:4])
                for r in sorted((r for r in res if r.price), key=lambda r: r.price)[:3]:
                    log("    ", r.price, r.airlines, [(s_.from_airport.code, s_.to_airport.code, s_.plane_type,
                        s_.departure.time, s_.arrival.time) for s_ in r.flights])
            except Exception as e:
                log("  parse error:", type(e).__name__, e)
        except Exception:
            log("  FAILED:\n" + traceback.format_exc(limit=4))

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
