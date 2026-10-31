"""How often is the route unknown, and for whom?  Reads the sightings log (data/stats.db).

    python tools/route_gaps.py            # whole history
    python tools/route_gaps.py --days 14  # last two weeks

Useful for deciding whether a paid route source is worth it: the last section counts the distinct
airline-style callsigns per day that still have no route, which is roughly how many lookups a paid
API would need.
"""
import argparse
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import classify  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0, help="only the last N days (default: all)")
    ap.add_argument("--db", default=str(ROOT / "data" / "stats.db"))
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    where, params = "", ()
    if args.days:
        where, params = "WHERE day >= ?", ((datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d"),)
    rows = con.execute(f"SELECT day, hex, callsign, airline, origin, dest, military FROM sightings {where}", params).fetchall()
    if not rows:
        print("No sightings logged yet.")
        return

    days = sorted({r[0] for r in rows})
    total = len(rows)
    known = [r for r in rows if r[4] and r[5]]
    missing = [r for r in rows if not (r[4] and r[5])]
    sched, other = [], []
    for r in missing:
        prefix, _ = classify.split_callsign(r[2])
        (sched if prefix and not r[6] else other).append(r)

    pct = lambda n, d=total: f"{100 * n / d:5.1f}%" if d else "  n/a"
    print(f"{total:,} sightings over {len(days)} day(s): {days[0]} .. {days[-1]}\n")
    print(f"  route known                         {len(known):6,}  {pct(len(known))}")
    print(f"  route unknown                       {len(missing):6,}  {pct(len(missing))}")
    print(f"    airline-style callsign (ABC123)   {len(sched):6,}  {pct(len(sched))}   <- a route source could fill these")
    print(f"    private / military / no callsign  {len(other):6,}  {pct(len(other))}   <- no schedule exists for these\n")

    # services that have no schedule however good the source (police, air ambulance, offshore helicopters, ...)
    service = {"UKP", "HLE", "NHZ", "CHX", "NPA", "PLC", "SPT"}
    scheduled = [r for r in sched if classify.split_callsign(r[2])[0] not in service]
    num = [r for r in scheduled if classify.split_callsign(r[2])[1].isdigit()]
    alnum = [r for r in scheduled if not classify.split_callsign(r[2])[1].isdigit()]
    print(f"  of the {len(sched):,} airline-style unknowns:")
    print(f"    police / air ambulance / helicopter callsigns   {len(sched) - len(scheduled):6,}  (never in a schedule)")
    print(f"    flight-number callsigns (RYR1234)               {len(num):6,}")
    print(f"    operational callsigns with letters (RYR27MC)    {len(alnum):6,}  (assigned per flight, so schedules rarely list them)\n")

    print(f"Airlines with the most unknown routes (of airline-style callsigns):")
    by_air = Counter(classify.split_callsign(r[2])[0] for r in sched)
    tot_air = Counter(classify.split_callsign(r[2])[0] for r in rows if classify.split_callsign(r[2])[0])
    for pre, n in by_air.most_common(args.top):
        name = next((r[3] for r in sched if classify.split_callsign(r[2])[0] == pre and r[3]), "")
        print(f"  {pre:4} {n:5,} of {tot_air[pre]:5,} sightings  {name}")

    print("\nMost frequently seen callsigns with no route:")
    for cs, n in Counter(r[2] for r in sched).most_common(args.top):
        print(f"  {cs:9} x{n}")

    per_day = Counter()
    seen = set()
    for r in sched:
        if (r[0], r[2]) not in seen:
            seen.add((r[0], r[2]))
            per_day[r[0]] += 1
    if per_day:
        vals = sorted(per_day.values())
        avg = sum(vals) / len(days)
        print(f"\nDistinct airline-style callsigns with no route, per day: avg {avg:.0f}, "
              f"busiest {vals[-1]}, ~{avg * 30:.0f} per month")
        print("  (a paid lookup API would need about that many calls; compare it with the plan's allowance)")


if __name__ == "__main__":
    main()
