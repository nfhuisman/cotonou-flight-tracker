#!/usr/bin/env python3
"""Diagnose why Google Flights searches fail. Writes data/diagnostics.txt."""
# Run 2: after adding typing_extensions

from __future__ import annotations

import datetime as dt
import importlib.metadata as md
import re
import traceback
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data" / "diagnostics.txt"
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    lines.append(s)


def describe_html(html: str) -> None:
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    log("  length:", len(html))
    log("  title:", title.group(1).strip()[:200] if title else None)
    log("  has 'ds:1' script:", "ds:1" in html)
    log("  mentions consent:", "consent" in html.lower(), "| unsupported:", "unsupported" in html.lower(),
        "| captcha/unusual traffic:", "unusual traffic" in html.lower() or "captcha" in html.lower())
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    log("  visible text start:", text[:600])


def main() -> None:
    log("Diagnostics", dt.datetime.utcnow().isoformat(timespec="seconds"), "UTC")
    for pkg in ("fast-flights", "primp", "protobuf", "selectolax"):
        try:
            log(f"{pkg}: {md.version(pkg)}")
        except Exception as e:
            log(f"{pkg}: not installed ({e})")

    try:
        from fast_flights import FlightQuery, Passengers, create_query, get_flights
        from fast_flights.fetcher import fetch_flights_html
        from fast_flights.parser import parse
    except Exception:
        log("IMPORT FAILED:\n" + traceback.format_exc())
        OUT.write_text("\n".join(lines) + "\n")
        return

    d1 = dt.date.today() + dt.timedelta(days=30)
    d2 = d1 + dt.timedelta(days=14)

    def q(dest="BRU", trip="round-trip", lang="en", cur="EUR"):
        legs = [FlightQuery(date=d1.isoformat(), from_airport="COO", to_airport=dest)]
        if trip == "round-trip":
            legs.append(FlightQuery(date=d2.isoformat(), from_airport=dest, to_airport="COO"))
        return create_query(flights=legs, trip=trip, seat="economy",
                            passengers=Passengers(adults=1), language=lang, currency=cur,
                            max_stops=1, hide_separate_and_self_transfer=True)

    # 1. The exact path the tracker uses
    for label, query in [("round-trip COO-BRU (tracker settings)", q()),
                         ("one-way COO-CDG", q("CDG", trip="one-way")),
                         ("round-trip COO-IST, no lang/currency", q("IST", lang="", cur=""))]:
        log(f"\n== get_flights: {label}")
        log("  url:", query.url())
        try:
            res = get_flights(query)
            log(f"  OK: {len(res)} itineraries; prices:",
                sorted(r.price for r in res if r.price)[:5])
            if res:
                r = res[0]
                log("  first:", r.airlines, [(s.from_airport.code, s.to_airport.code, s.plane_type) for s in r.flights])
        except Exception:
            log("  FAILED:\n" + traceback.format_exc(limit=6))
            try:
                html = fetch_flights_html(query)
                describe_html(html)
            except Exception:
                log("  fetch also failed:\n" + traceback.format_exc(limit=4))

    # 2. Alternative fetch settings (to find one that works)
    try:
        from primp import Client
    except Exception:
        Client = None
        log("\nprimp import failed:\n" + traceback.format_exc(limit=3))
    if Client:
        query = q()
        cookie_sets = {"none": None, "consent": {"CONSENT": "YES+cb", "SOCS": "CAI"}}
        for imp in ("chrome_145", "chrome_131", "chrome_120", "safari_18", "firefox_133", None):
            for cname, cookies in cookie_sets.items():
                log(f"\n== alt fetch impersonate={imp} cookies={cname}")
                try:
                    kw = dict(referer=True, cookie_store=True)
                    if imp:
                        kw["impersonate"] = imp
                    c = Client(**kw)
                    params = query.params()
                    if cookies:
                        r = c.get("https://www.google.com/travel/flights", params=params, cookies=cookies)
                    else:
                        r = c.get("https://www.google.com/travel/flights", params=params)
                    log("  status:", r.status_code, "final url:", str(getattr(r, "url", ""))[:150])
                    html = r.text
                    try:
                        res = parse(html)
                        log(f"  PARSE OK: {len(res)} itineraries; cheapest:",
                            min((x.price for x in res if x.price), default=None))
                    except Exception as e:
                        log(f"  parse failed: {type(e).__name__}: {e}")
                        describe_html(html)
                except Exception:
                    log("  FAILED:\n" + traceback.format_exc(limit=3))

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
