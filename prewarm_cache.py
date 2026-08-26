"""Pre-warm the FINRA/Polygon cache for recent trading days.

Run on a schedule (Render Cron Job), separate from the web service, so a
live request almost always finds its date range already cached in
Postgres and just reads it back -- instead of the web worker doing the
FINRA+Polygon fetch synchronously and risking a gunicorn WORKER TIMEOUT
on any range with more than a couple of previously-uncached days (see
the "This Month" incident: Polygon's free-tier 5 calls/min cap alone can
force ~12s between calls, which a 30s worker timeout can't absorb for
more than a couple of missing dates).

ensure_ssdata_cached() already skips any date that's already cached (see
the self-heal EXISTS check in finra.py), so it's safe to call with the
same wide window every run -- only the dates actually missing since the
last run do any real work.
"""
from datetime import datetime, timedelta

import pytz

from finra import ensure_ssdata_cached, trim_old_data

# Covers a full "This Month"-sized request plus slack, without making a
# single cron run walk back further than necessary against the shared
# Polygon rate limit.
BACKFILL_DAYS = 40


def main():
    # finra.py's is_today_pacific() decides whether a fetch failure gets
    # permanently cached as "no file" using Pacific time -- anchoring the
    # end of this range to the container's raw clock (Render runs UTC)
    # instead risks requesting a date Pacific hasn't reached yet whenever
    # this runs (or is manually triggered) after 5pm PT/PDT, when UTC has
    # already rolled to the next calendar day. FINRA correctly 403s that
    # not-yet-started date, but is_today_pacific() then says it's *not*
    # today, so the failure gets cached as permanent instead of retried
    # tomorrow -- reintroducing the exact stale-NULL bug this project
    # already fixed once for the live request path.
    end = datetime.now(pytz.timezone('US/Pacific'))
    start = end - timedelta(days=BACKFILL_DAYS)
    startdate = start.strftime('%Y%m%d')
    enddate = end.strftime('%Y%m%d')
    print(f"Pre-warming cache for {startdate}..{enddate}")
    # Not fetch_ssdata_raw() -- this script only cares about the caching
    # side effect, and fetch_ssdata_raw()'s final bulk read of the whole
    # range into one DataFrame would be pure wasted memory here.
    ensure_ssdata_cached(startdate, enddate)

    # Keeps the table bounded to roughly the same window this script
    # warms -- letting it grow forever is what filled the production
    # disk once already.
    trim_old_data()

    print("Done.")


if __name__ == '__main__':
    main()
