"""Pre-warm the FINRA/Polygon cache for recent trading days.

Run on a schedule (Render Cron Job), separate from the web service, so a
live request almost always finds its date range already cached in
Postgres and just reads it back -- instead of the web worker doing the
FINRA+Polygon fetch synchronously and risking a gunicorn WORKER TIMEOUT
on any range with more than a couple of previously-uncached days (see
the "This Month" incident: Polygon's free-tier 5 calls/min cap alone can
force ~12s between calls, which a 30s worker timeout can't absorb for
more than a couple of missing dates).

fetch_ssdata_raw() already skips any date that's already cached (see the
self-heal EXISTS check in finra.py), so it's safe to call with the same
wide window every run -- only the dates actually missing since the last
run do any real work.
"""
from datetime import datetime, timedelta

from finra import fetch_ssdata_raw

# Covers a full "This Month"-sized request plus slack, without making a
# single cron run walk back further than necessary against the shared
# Polygon rate limit.
BACKFILL_DAYS = 40


def main():
    end = datetime.today()
    start = end - timedelta(days=BACKFILL_DAYS)
    startdate = start.strftime('%Y%m%d')
    enddate = end.strftime('%Y%m%d')
    print(f"Pre-warming cache for {startdate}..{enddate}")
    fetch_ssdata_raw(startdate, enddate)
    print("Done.")


if __name__ == '__main__':
    main()
