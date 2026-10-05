#!/usr/bin/env python3
"""Diagnose why Google Flights searches fail. Writes data/diagnostics.txt."""
# Run 6: try the `fli` library for round trips and date sweeps

from __future__ import annotations

import datetime as dt
import importlib.metadata as md
import time
import traceback
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data" / "diagnostics.txt"
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


def fmt(fr):
    legs = ", ".join(f"{l.airline.name}{l.flight_number} {l.departure_airport.name}-{l.arrival_airport.name} "
                     f"{l.departure_datetime:%d%b %H:%M}-{l.arrival_datetime:%H:%M} {l.aircraft or ''}"
                     for l in fr.legs)
    return f"{fr.price} {fr.currency} stops={fr.stops} [{legs}]"


def main() -> None:
    log("Diagnostics", dt.datetime.utcnow().isoformat(timespec="seconds"), "UTC")
    log("flights (fli):", md.version("flights"))
    from fli.models import (Airline, Airport, DateSearchFilters, FlightSearchFilters, FlightSegment,
                            LayoverRestrictions, MaxStops, PassengerInfo, SeatType, SortBy, TripType)
    from fli.search import SearchDates, SearchFlights

    d1 = dt.date.today() + dt.timedelta(days=30)

    def rt_filters(dest, stay, stops=MaxStops.NON_STOP, airlines=None, layover=None):
        ret = d1 + dt.timedelta(days=stay)
        return FlightSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(departure_airport=[[Airport["COO"], 0]], arrival_airport=[[Airport[dest], 0]],
                              travel_date=d1.isoformat()),
                FlightSegment(departure_airport=[[Airport[dest], 0]], arrival_airport=[[Airport["COO"], 0]],
                              travel_date=ret.isoformat()),
            ],
            stops=stops, seat_type=SeatType.ECONOMY, sort_by=SortBy.CHEAPEST,
            airlines=airlines, layover_restrictions=layover)

    sf = SearchFlights()
    cases = [
        ("RT BRU 21d nonstop", rt_filters("BRU", 21)),
        ("RT IST 14d nonstop", rt_filters("IST", 14)),
        ("RT DSS 14d nonstop", rt_filters("DSS", 14)),
        ("RT ABJ 14d nonstop", rt_filters("ABJ", 14)),
        ("RT AMS 21d 1 stop AF/KL layover 120-360",
         rt_filters("AMS", 21, MaxStops.ONE_STOP_OR_FEWER, [Airline["AF"], Airline["KL"]],
                    LayoverRestrictions(min_duration=120, max_duration=360))),
        ("RT CDG 21d nonstop (control)", rt_filters("CDG", 21)),
    ]
    for label, f in cases:
        for country in (None, "BE"):
            log(f"\n== {label} country={country}")
            t = time.time()
            try:
                res = sf.search(f, top_n=2, currency="EUR", language="en", country=country)
                log(f"  {len(res or [])} combos in {time.time() - t:.1f}s")
                for combo in (res or [])[:3]:
                    if isinstance(combo, tuple):
                        log("   OUT", fmt(combo[0]))
                        log("   RET", fmt(combo[1]))
                    else:
                        log("   ", fmt(combo))
            except Exception:
                log("  FAILED:\n" + traceback.format_exc(limit=4))

    # Date sweep: cheapest round-trip price per departure date
    log("\n== SearchDates BRU 21d nonstop, 10 departure dates")
    t = time.time()
    try:
        df = DateSearchFilters(
            trip_type=TripType.ROUND_TRIP, passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(departure_airport=[[Airport["COO"], 0]], arrival_airport=[[Airport["BRU"], 0]],
                              travel_date=d1.isoformat()),
                FlightSegment(departure_airport=[[Airport["BRU"], 0]], arrival_airport=[[Airport["COO"], 0]],
                              travel_date=(d1 + dt.timedelta(days=21)).isoformat()),
            ],
            stops=MaxStops.NON_STOP, seat_type=SeatType.ECONOMY,
            from_date=d1.isoformat(), to_date=(d1 + dt.timedelta(days=9)).isoformat(), duration=21)
        res = SearchDates().search(df, currency="EUR", language="en")
        log(f"  {len(res or [])} dates in {time.time() - t:.1f}s")
        for dp in res or []:
            log("   ", dp)
    except Exception:
        log("  FAILED:\n" + traceback.format_exc(limit=5))

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
