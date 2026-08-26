"""One-time backfill of the last 2 years of FINRA/Polygon data.

Not meant to run on a schedule -- unlike prewarm_cache.py's small rolling
window, this walks back far enough to hit Polygon's free-tier limit for
historical closing prices (2 years), so every date in range gets a real
price, not just a NULL fallback.

At ~12.5s per Polygon call (see POLYGON_MIN_CALL_INTERVAL in finra.py),
backfilling however many dates are actually missing can take well over
an hour. Run this by temporarily pointing the existing Cron Job's Start
Command at `python backfill_history.py`, triggering one manual run, and
switching the Command back to `python prewarm_cache.py` once it
completes -- this script is not meant to be the job's permanent command.

fetch_ssdata_raw() already skips any date that's already cached, so
this is safe to re-run if it's ever interrupted partway through.
"""
from datetime import datetime, timedelta

import pytz

from finra import fetch_ssdata_raw

BACKFILL_DAYS = 730


def main():
    # Same Pacific-time anchoring as prewarm_cache.py, for the same reason:
    # is_today_pacific() in finra.py checks Pacific time when deciding
    # whether a fetch failure is permanent, so the end of this range needs
    # to agree with that clock rather than the container's raw UTC one.
    end = datetime.now(pytz.timezone('US/Pacific'))
    start = end - timedelta(days=BACKFILL_DAYS)
    startdate = start.strftime('%Y%m%d')
    enddate = end.strftime('%Y%m%d')
    print(f"Backfilling {startdate}..{enddate} ({BACKFILL_DAYS} days) -- this can take over an hour.")
    fetch_ssdata_raw(startdate, enddate)
    print("Done.")


if __name__ == '__main__':
    main()
