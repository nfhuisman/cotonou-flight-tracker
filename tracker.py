#!/usr/bin/env python3
"""Cotonou flight price tracker.

Once a day (via GitHub Actions) this script:
  1. searches Google Flights for one-way fares, Cotonou -> destination and back,
     on the dates set in routes.yaml (Google's page only carries round-trip
     results for a few very popular routes, but one-way results for all),
  2. appends the cheapest suitable fare per search to data/legs.csv,
  3. pairs outbound and return legs into trips (e.g. 3 and 4 weeks), compares
     today's trip prices with their history and sends a Telegram message when
     something is clearly cheaper than usual,
  4. rebuilds the dashboard in docs/index.html (served by GitHub Pages).

Run locally:
  python tracker.py                 # normal daily run
  python tracker.py --test-telegram # just send a test message
  python tracker.py --simulate 40   # fake 40 days of data into ./_sim (no internet needed)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import random
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
LEG_FIELDS = ["checked", "route", "dir", "date", "price", "currency",
              "airline", "kind", "via", "duration_min", "link"]


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def load_config(root: Path) -> tuple[dict, list[dict]]:
    cfg = yaml.safe_load((root / "routes.yaml").read_text(encoding="utf-8"))
    settings = cfg["settings"]
    routes = []
    for group in cfg["groups"]:
        for r in group["routes"]:
            stays = r.get("stay_days", group["stay_days"])
            stays = stays if isinstance(stays, list) else [stays]
            for stay in stays:
                routes.append({
                    "id": f'{r["code"]}-{int(stay)}',
                    "code": r["code"],
                    "city": r["city"],
                    "note": r.get("note", ""),
                    "group": group["name"],
                    "allow_change": bool(r.get("allow_change", False)),
                    "via": r.get("via") or None,
                    "min_layover": r.get("min_layover_minutes"),
                    "max_layover": r.get("max_layover_minutes"),
                    "stay_days": int(stay),
                    "every_days": int(r.get("every_days", group["every_days"])),
                    "horizon_days": int(r.get("horizon_days", group["horizon_days"])),
                })
    return settings, routes


GRID_EPOCH = dt.date(2026, 1, 1)


def sample_dates(route: dict, today: dt.date) -> list[tuple[dt.date, dt.date]]:
    """Departure dates on a fixed calendar grid, so the same dates are checked every day."""
    step = route["every_days"]
    first = today + dt.timedelta(days=7)
    d = first + dt.timedelta(days=(-(first - GRID_EPOCH).days) % step)
    end = today + dt.timedelta(days=route["horizon_days"])
    out = []
    while d <= end:
        out.append((d, d + dt.timedelta(days=route["stay_days"])))
        d += dt.timedelta(days=step)
    return out


def leg_jobs(routes: list[dict], today: dt.date) -> list[tuple[dict, str, dt.date]]:
    """One-way searches needed today: (route, 'out'|'in', date), each only once."""
    seen, jobs = set(), []
    for route in routes:
        for d, r in sample_dates(route, today):
            for direction, day in (("out", d), ("in", r)):
                key = (route["code"], direction, day)
                if key not in seen:
                    seen.add(key)
                    jobs.append((route, direction, day))
    jobs.sort(key=lambda j: (j[0]["code"], j[1] == "in", j[2]))
    return jobs


# --------------------------------------------------------------------------
# Fetching (Google Flights via the fast-flights library)
# --------------------------------------------------------------------------

def parse_itineraries(html: str) -> list[dict] | None:
    """Itineraries from a Google Flights results page, with flight numbers.

    Returns None when Google answered with an error page (worth a retry).
    """
    import re
    m = re.search(r'<script[^>]*class="ds:1"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    js = m.group(1)
    if "errorHasStatus: true" in js:
        return None
    payload = json.loads(js.split("data:", 1)[1].rsplit(",", 1)[0])
    out = []
    for section in payload[2:4]:
        for row in (section[0] if section and section[0] else []):
            try:
                flight, fare = row[0], row[1]
                price = fare[0][1] if fare and fare[0] and len(fare[0]) > 1 else None
                segs = []
                for sf in flight[2]:
                    dep_t, arr_t = (sf[8] or []) + [0, 0], (sf[10] or []) + [0, 0]
                    num = sf[22] or []
                    segs.append({
                        "from": sf[3], "to": sf[6], "plane": sf[17] or "",
                        "carrier": num[0] if num else "", "number": str(num[1]) if len(num) > 1 else "",
                        "dep": dt.datetime(*sf[20], dep_t[0] or 0, dep_t[1] or 0),
                        "arr": dt.datetime(*sf[21], arr_t[0] or 0, arr_t[1] or 0),
                        "minutes": sf[11] or 0,
                    })
                out.append({"price": price, "airlines": flight[1] or [], "segs": segs})
            except (IndexError, TypeError, ValueError):
                continue
    return out


def classify(itin: dict) -> tuple[str, str, int | None]:
    """Return (kind, via, layover_minutes). kind: nonstop | same-plane | change | other.

    A stop is "same-plane" only when the flight continues under the same flight
    number (e.g. Turkish Airlines Cotonou-Abidjan-Istanbul).
    """
    segs = itin["segs"]
    if len(segs) == 1:
        return "nonstop", "", None
    if len(segs) == 2:
        a, b = segs
        via = a["to"]
        layover = int((b["dep"] - a["arr"]).total_seconds() // 60)
        if a["carrier"] and (a["carrier"], a["number"]) == (b["carrier"], b["number"]):
            return "same-plane", via, layover
        return "change", via, layover
    return "other", "/".join(x["to"] for x in segs[:-1]), None


def suitable(route: dict, kind: str, via: str, layover: int | None) -> bool:
    if kind in ("nonstop", "same-plane"):
        return True
    if kind != "change" or not route["allow_change"]:
        return False
    if route["via"] and via not in route["via"]:
        return False
    if layover is None:
        return False
    if route["min_layover"] is not None and layover < route["min_layover"]:
        return False
    if route["max_layover"] is not None and layover > route["max_layover"]:
        return False
    return True


def fetch_google(origin: str, route: dict, direction: str, day: dt.date,
                 settings: dict) -> dict | None:
    """Cheapest suitable one-way fare for one leg, or None if there is none."""
    from fast_flights import FlightQuery, Passengers, create_query
    from fast_flights.fetcher import fetch_flights_html

    leg_filters = {}
    if route["allow_change"]:
        leg_filters = {"connecting_airports": route["via"],
                       "min_layover_minutes": route["min_layover"],
                       "max_layover_minutes": route["max_layover"]}
    a, b = (origin, route["code"]) if direction == "out" else (route["code"], origin)
    q = create_query(
        flights=[FlightQuery(date=day.isoformat(), from_airport=a, to_airport=b, **leg_filters)],
        trip="one-way",
        seat="economy",
        passengers=Passengers(adults=int(settings.get("adults", 1))),
        language="en",
        currency=settings.get("currency", "EUR"),
        max_stops=1,
    )
    results = None
    for attempt in range(3):  # Google sometimes answers with an error page; retry
        try:
            results = parse_itineraries(fetch_flights_html(q))
        except Exception:
            if attempt == 2:
                raise
        if results is not None:
            break
        time.sleep(3 + 3 * attempt)

    best = None
    for itin in results or []:
        if not itin["price"]:
            continue
        kind, via, layover = classify(itin)
        if not suitable(route, kind, via, layover):
            continue
        if best is None or itin["price"] < best["price"]:
            best = {
                "price": int(itin["price"]),
                "airline": ", ".join(itin["airlines"]),
                "kind": kind,
                "via": via,
                "duration_min": sum(x["minutes"] for x in itin["segs"]),
            }
    if best:
        best["link"] = q.url()
    return best


def trip_link(origin: str, code: str, depart: str, ret: str, cur: str) -> str:
    text = f"Flights from {origin} to {code} on {depart} through {ret}"
    return ("https://www.google.com/travel/flights?q=" + urllib.parse.quote(text)
            + f"&curr={cur}&hl=en")


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

def read_legs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["price"] = int(float(r["price"]))
    return rows


def append_legs(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LEG_FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in LEG_FIELDS})


def append_run(path: Path, checked: str, ok: int, failed: int, empty: int) -> None:
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["checked", "ok", "no_suitable_flight", "failed"])
        w.writerow([checked, ok, empty, failed])


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

def leg_label(kind: str, via: str) -> str:
    return {"nonstop": "nonstop", "same-plane": f"stop in {via}, same plane",
            "change": f"change in {via}"}.get(kind, kind)


def trips_from_legs(legs: list[dict], routes: list[dict], origin: str) -> list[dict]:
    """Pair each day's outbound and return legs into trips for every route/stay."""
    idx = {(r["checked"], r["route"], r["dir"], r["date"]): r for r in legs}
    outs_by: dict[tuple[str, str], list[dict]] = {}
    for r in legs:
        if r["dir"] == "out":
            outs_by.setdefault((r["checked"], r["route"]), []).append(r)
    trips = []
    for route in routes:
        for (checked, code), outs in outs_by.items():
            if code != route["code"]:
                continue
            for o in outs:
                ret = (dt.date.fromisoformat(o["date"]) + dt.timedelta(days=route["stay_days"])).isoformat()
                i = idx.get((checked, route["code"], "in", ret))
                if not i:
                    continue
                lo, li = leg_label(o["kind"], o["via"]), leg_label(i["kind"], i["via"])
                trips.append({
                    "checked": checked, "route": route["id"], "depart": o["date"], "return": ret,
                    "price": o["price"] + i["price"], "out_price": o["price"], "in_price": i["price"],
                    "currency": o["currency"],
                    "airline": o["airline"] if o["airline"] == i["airline"] else f'{o["airline"]} / {i["airline"]}',
                    "kind": lo if lo == li else f"{lo} out, {li} back",
                    "via": "",
                    "link": trip_link(origin, route["code"], o["date"], ret, o["currency"]),
                })
    return trips


def analyse(rows: list[dict], routes: list[dict], settings: dict, today: str) -> dict:
    """Per-route summary + list of deals found in today's data."""
    th = float(settings.get("deal_threshold", 0.15))
    min_days = int(settings.get("min_history_days", 7))
    t = dt.date.fromisoformat(today)
    window_start = (t - dt.timedelta(days=30)).isoformat()

    by_route: dict[str, list[dict]] = {}
    for r in rows:
        by_route.setdefault(r["route"], []).append(r)

    summary, deals = [], []
    for route in routes:
        rid = route["id"]
        rr = by_route.get(rid, [])

        # cheapest fare per check day
        daily: dict[str, dict] = {}
        for r in rr:
            cur = daily.get(r["checked"])
            if cur is None or r["price"] < cur["price"]:
                daily[r["checked"]] = r
        history = sorted(daily.items())
        prior = [r["price"] for d, r in history if window_start <= d < today]
        median = statistics.median(prior) if prior else None
        best_today = daily.get(today)
        enough = len(prior) >= min_days

        route_deal = bool(best_today and enough and median
                          and best_today["price"] <= (1 - th) * median)

        # price for each departure date in today's run, vs. that date's own history
        per_date: dict[str, list[int]] = {}
        for r in rr:
            if r["checked"] < today:
                per_date.setdefault(r["depart"], []).append(r["price"])
        todays = sorted((r for r in rr if r["checked"] == today), key=lambda r: r["depart"])
        departures = []
        date_deals = []
        for r in todays:
            hist = per_date.get(r["depart"], [])
            usual = statistics.mean(hist) if len(hist) >= 5 else None
            is_deal = bool(usual and r["price"] <= (1 - th) * usual)
            departures.append({**r, "usual": round(usual) if usual else None, "deal": is_deal})
            if is_deal:
                date_deals.append((r, usual))

        if route_deal:
            deals.append({"route": route, "row": best_today, "usual": median,
                          "basis": "the usual cheapest fare on this route (30-day median)"})
        for r, usual in sorted(date_deals, key=lambda x: x[0]["price"] / x[1])[:3]:
            if route_deal and r is best_today:
                continue
            deals.append({"route": route, "row": r, "usual": usual,
                          "basis": "the average for this departure date"})

        summary.append({
            "id": rid, "code": route["code"], "city": route["city"], "group": route["group"],
            "note": route["note"], "stay": route["stay_days"],
            "history": [[d, r["price"]] for d, r in history],
            "median30": round(median) if median else None,
            "history_days": len(prior),
            "enough": enough,
            "best": best_today,
            "route_deal": route_deal,
            "departures": departures,
        })
    return {"summary": summary, "deals": deals}


def filter_new_deals(deals: list[dict], state: dict, settings: dict, today: str) -> list[dict]:
    drop = float(settings.get("realert_drop", 0.05))
    t = dt.date.fromisoformat(today)
    fresh = []
    for d in deals:
        key = f'{d["route"]["id"]}|{d["row"]["depart"]}'
        prev = state.get(key)
        stale = prev and (t - dt.date.fromisoformat(prev["date"])).days > 14
        if prev is None or stale or d["row"]["price"] <= prev["price"] * (1 - drop):
            fresh.append(d)
            state[key] = {"price": d["row"]["price"], "date": today}
    # forget alerts for trips that already departed
    for key in [k for k in state if k.split("|")[1] < today]:
        state.pop(key)
    return fresh


# --------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------

def fmt_date(iso: str) -> str:
    return dt.date.fromisoformat(iso).strftime("%a %-d %b")


def send_telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("Telegram not configured; message would have been:\n" + text)
        return False
    chunks, cur = [], ""
    for block in text.split("\n\n"):
        if len(cur) + len(block) > 3800:
            chunks.append(cur)
            cur = ""
        cur += block + "\n\n"
    chunks.append(cur)
    for chunk in chunks:
        data = urllib.parse.urlencode({
            "chat_id": chat, "text": chunk.strip(), "parse_mode": "HTML",
            "disable_web_page_preview": "true"}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                print("Telegram error", resp.status, resp.read()[:300])
                return False
    return True


def weeks(days: int) -> str:
    return f"{days // 7} weeks" if days % 7 == 0 else f"{days} days"


def money(cur: str, v) -> str:
    sym = {"EUR": "€", "USD": "$", "GBP": "£"}.get(cur)
    return f"{sym}{round(v):,}" if sym else f"{cur} {round(v):,}"


def deal_message(deals: list[dict], cur: str, dashboard: str) -> str:
    parts = [f"✈️ <b>{len(deals)} cheaper-than-usual trip{'s' if len(deals) > 1 else ''} from Cotonou</b>"]
    for d in deals:
        r, route = d["row"], d["route"]
        pct = round((1 - r["price"] / d["usual"]) * 100)
        parts.append(
            f'<b>Cotonou ⇄ {route["city"]}</b> ({weeks(route["stay_days"])}): {money(cur, r["price"])}\n'
            f'{fmt_date(r["depart"])} → {fmt_date(r["return"])} · {r["airline"]}, {r["kind"]}\n'
            f'One-way tickets: {money(cur, r["out_price"])} out + {money(cur, r["in_price"])} back\n'
            f'{pct}% below {d["basis"]} ({money(cur, d["usual"])})\n'
            f'<a href="{r["link"]}">Check return fares in Google Flights</a>')
    if dashboard:
        parts.append(f'<a href="{dashboard}">Dashboard</a>')
    return "\n\n".join(parts)


def weekly_message(summary: list[dict], cur: str, dashboard: str) -> str:
    lines = ["📊 <b>Weekly overview: cheapest trips from Cotonou</b> (two one-way tickets)"]
    for s in summary:
        b = s["best"]
        if not b:
            lines.append(f'{s["city"]} ({weeks(s["stay"])}): no suitable flights found today')
            continue
        vs = ""
        if s["enough"] and s["median30"]:
            diff = round((b["price"] / s["median30"] - 1) * 100)
            vs = f' ({diff:+d}% vs usual)'
        lines.append(f'{s["city"]} ({weeks(s["stay"])}): <b>{money(cur, b["price"])}</b>{vs}, '
                     f'{fmt_date(b["depart"])} → {fmt_date(b["return"])}, {b["airline"]}')
    if dashboard:
        lines.append(f'\n<a href="{dashboard}">Open the dashboard</a>')
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------

def build_dashboard(root: Path, analysis: dict, settings: dict, today: str,
                    run_stats: dict) -> None:
    template = (HERE / "dashboard_template.html").read_text(encoding="utf-8")
    payload = {
        "generated": today,
        "currency": settings.get("currency", "EUR"),
        "threshold": settings.get("deal_threshold", 0.15),
        "minHistory": settings.get("min_history_days", 7),
        "run": run_stats,
        "routes": analysis["summary"],
    }
    blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    out = root / "docs" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(template.replace("/*__DATA__*/null", blob), encoding="utf-8")
    (root / "docs" / ".nojekyll").touch()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def dashboard_url() -> str:
    if os.environ.get("DASHBOARD_URL"):
        return os.environ["DASHBOARD_URL"]
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


def run(root: Path, today: dt.date, fetch, pause=(1.5, 4.0), notify=True,
        log=print) -> dict:
    settings, routes = load_config(root)
    origin = settings.get("origin", "COO")
    cur = settings.get("currency", "EUR")
    tday = today.isoformat()

    new_rows, ok, empty, failed = [], 0, 0, 0
    errors: list[str] = []
    jobs = leg_jobs(routes, today)
    for i, (route, direction, day) in enumerate(jobs, 1):
        tag = f"[{i}/{len(jobs)}] {route['code']} {direction} {day}"
        try:
            best = fetch(origin, route, direction, day, settings)
        except Exception as e:  # keep going; one bad search shouldn't stop the run
            failed += 1
            if len(errors) < 5:
                import traceback
                errors.append(f"{tag}:\n{traceback.format_exc(limit=5)}")
            log(f"{tag}: ERROR {type(e).__name__}: {e}")
            best = None
        else:
            if best:
                ok += 1
                new_rows.append({"checked": tday, "route": route["code"], "dir": direction,
                                 "date": day.isoformat(), "currency": cur, **best})
                log(f"{tag}: {cur} {best['price']} {best['airline']} ({best['kind']})")
            else:
                empty += 1
                log(f"{tag}: no suitable flight")
        if pause and i < len(jobs):
            time.sleep(random.uniform(*pause))

    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "last_errors.txt").write_text(
        f"{tday}: {failed} of {len(jobs)} searches failed\n\n" + "\n".join(errors))
    append_legs(data / "legs.csv", new_rows)
    append_run(data / "runs.csv", tday, ok, failed, empty)

    rows = trips_from_legs(read_legs(data / "legs.csv"), routes, origin)
    analysis = analyse(rows, routes, settings, tday)

    state_path = data / "alert_state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    fresh = filter_new_deals(analysis["deals"], state, settings, tday)
    state_path.write_text(json.dumps(state, indent=1, sort_keys=True))

    run_stats = {"searches": len(jobs), "ok": ok, "empty": empty, "failed": failed}
    build_dashboard(root, analysis, settings, tday, run_stats)

    dash = dashboard_url()
    if notify:
        if len(jobs) and failed / len(jobs) > 0.5:
            send_telegram(f"⚠️ Flight tracker: {failed} of {len(jobs)} searches failed today. "
                          "Google may be blocking the requests; the run log on GitHub "
                          "(Actions tab) shows the errors.")
        if fresh:
            send_telegram(deal_message(fresh, cur, dash))
        if today.weekday() == 6:
            send_telegram(weekly_message(analysis["summary"], cur, dash))
    log(f"Done: {ok} fares, {empty} without suitable flights, {failed} errors, "
        f"{len(fresh)} new deal alert(s).")
    return {"analysis": analysis, "fresh": fresh, "stats": run_stats}


# --------------------------------------------------------------------------
# Simulation (for testing without internet)
# --------------------------------------------------------------------------

BASE = {"BRU": 780, "CDG": 720, "ORY": 650, "AMS": 820, "IST": 690, "CMN": 540,
        "ADD": 610, "DSS": 430, "ABJ": 260, "ACC": 240, "LBV": 380, "DLA": 350, "SSG": 410}
AIR = {"BRU": "Brussels Airlines", "CDG": "Air France", "ORY": "Corsair",
       "AMS": "Air France, KLM", "IST": "Turkish Airlines", "CMN": "Royal Air Maroc",
       "ADD": "Ethiopian", "DSS": "Air Côte d'Ivoire", "ABJ": "Air Côte d'Ivoire",
       "ACC": "ASKY", "LBV": "Afrijet", "DLA": "ASKY", "SSG": "Afrijet"}


def make_sim_fetch(day_index: int, seed: int, crash_on: int | None = None):
    def fetch(origin, route, direction, d, settings):
        rnd = random.Random(f"{seed}-{route['code']}-{direction}-{d}-{day_index}")
        base = BASE.get(route["code"], 500) * 0.6
        season = 1.25 if d.month == 12 and d.day > 15 else 1.0
        noise = rnd.uniform(0.92, 1.1)
        promo = 0.7 if (day_index == crash_on and route["code"] in ("BRU", "IST")) else 1.0
        if rnd.random() < 0.05:
            return None
        return {"price": round(base * season * noise * promo), "airline": AIR[route["code"]],
                "kind": "change" if route["code"] == "AMS" else "nonstop",
                "via": "CDG" if route["code"] == "AMS" else "",
                "duration_min": 400,
                "link": f"https://www.google.com/travel/flights?q=COO-{route['code']}-{d}-{direction}"}
    return fetch


def simulate(days: int) -> None:
    import shutil
    sim = HERE / "_sim"
    shutil.rmtree(sim, ignore_errors=True)
    sim.mkdir()
    shutil.copy(HERE / "routes.yaml", sim / "routes.yaml")
    start = dt.date.today() - dt.timedelta(days=days - 1)
    last = None
    for i in range(days):
        day = start + dt.timedelta(days=i)
        quiet = i < days - 1
        last = run(sim, day, make_sim_fetch(i, 7, crash_on=days - 1), pause=None,
                   notify=not quiet, log=(lambda *a: None) if quiet else print)
    print(f"\nSimulated {days} days into {sim}. New alerts on the last day: {len(last['fresh'])}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test-telegram", action="store_true")
    ap.add_argument("--simulate", type=int, metavar="DAYS")
    ap.add_argument("--no-notify", action="store_true")
    a = ap.parse_args()

    if a.test_telegram:
        ok = send_telegram("✅ Flight tracker connected. You'll get a message here when a "
                           "fare from Cotonou is clearly cheaper than usual, plus an "
                           "overview every Sunday.\n\n" + dashboard_url())
        sys.exit(0 if ok else 1)
    if a.simulate:
        simulate(a.simulate)
        return
    run(HERE, dt.date.today(), fetch_google, notify=not a.no_notify)


if __name__ == "__main__":
    main()
