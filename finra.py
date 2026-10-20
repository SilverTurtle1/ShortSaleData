import io
import os
import re
import time

import yfinance as yf
from datetime import datetime
from datetime import timedelta

import pytz

import pandas as pd
import requests

from sqlalchemy import MetaData, Table, Column, String, BIGINT, ForeignKey, text, Float
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy_utils import database_exists, create_database

from polygon import RESTClient
from polygon.exceptions import BadResponse, AuthError
from urllib3.exceptions import MaxRetryError

try:
    # local_settings.py is gitignored and only present for local development.
    from local_settings import postgresql_local as settings_local
    from local_settings import postgresql_render as settings_render
    from local_settings import polygonAPIkey as apikey
except ImportError:
    # Deployed environments (e.g. Render) configure these as environment
    # variables instead of shipping a local_settings.py file.
    settings_local = {
        'pguser': os.environ.get('PG_LOCAL_USER', 'pguser'),
        'pgpasswd': os.environ.get('PG_LOCAL_PASSWORD'),
        'pghost': os.environ.get('PG_LOCAL_HOST', 'localhost'),
        'pgport': int(os.environ.get('PG_LOCAL_PORT', 5432)),
        'pgdb': os.environ.get('PG_LOCAL_DB', 'alpha'),
    }
    settings_render = {
        'pguser': os.environ.get('PG_RENDER_USER', 'database_user'),
        'pgpasswd': os.environ.get('PG_RENDER_PASSWORD'),
        'pghost': os.environ.get('PG_RENDER_HOST', 'dpg-ct6h009u0jms7396hdkg-a'),
        'pgport': int(os.environ.get('PG_RENDER_PORT', 5432)),
        'pgdb': os.environ.get('PG_RENDER_DB', 'alpha_flsq'),
    }
    apikey = os.environ.get('POLYGON_API_KEY')

# Polygon's free tier allows 5 calls/min, shared with ESFuturesData on the
# same account -- pace grouped-aggs calls to stay under that ourselves
# rather than relying on the client's own retry (which just gives up and
# raises after enough 429s, see MaxRetryError below). 12.5s comfortably
# clears the 12s/call floor 5-per-minute implies.
POLYGON_MIN_CALL_INTERVAL = 12.5

finra_dir = r'https://cdn.finra.org/equity/regsho/daily/CNMSshvol'
data_dir = r'static/data/'
mapping_file = 'etfMapping-backup.csv'
#min_volume = 1  # 5M shares traded daily min
# Render sets the RENDER env var on every deployed service, so this picks
# the Render-hosted Postgres in production and the local one everywhere else.
local_db = os.environ.get('RENDER') is None

# Guards the one-time CREATE INDEX CONCURRENTLY in fetch_ssdata_raw so it
# only ever runs once per worker process instead of on every request --
# see the comment at that call site for why running it repeatedly is a
# real production risk, not just wasted work.
_finrafiledetail_date_index_ensured = False


def get_company_name(symbol):
    src_dir = os.path.dirname(os.path.abspath(__file__))
    etf_df = pd.read_csv(os.path.join(src_dir, data_dir, mapping_file))
    match = etf_df.loc[etf_df["Symbol"] == symbol, "Name"]
    # A symbol can be in the mapping with a blank name, which pandas reads
    # as NaN -- and NaN serializes to the bare token NaN, which isn't valid
    # JSON and breaks any endpoint that returns it.
    return match.iloc[0] if not match.empty and pd.notna(match.iloc[0]) else None


def get_symbol_detail(symbol, enddate, days=30):
    """A single symbol's daily rows for the trailing `days` window ending
    on (and including) enddate. Queries the DB directly rather than
    relying on any request-scoped cache, since callers like the Daily
    Buys report drill-down have no prior wide-range fetch to reuse --
    it's meant for a quick, targeted lookup, not a bulk range.
    """
    cutoff = (datetime.strptime(enddate, '%Y%m%d') - timedelta(days=days)).strftime('%Y%m%d')
    engine = get_engine_from_settings()
    try:
        select = text("""
            SELECT "Date", "Symbol", "ShortVolume", "TotalVolume", "Close"
            FROM "FINRAFileDetail"
            WHERE "Symbol" = :symbol AND "Date" <= :enddate AND "Date" >= :cutoff
            ORDER BY "Date"
        """).bindparams(symbol=symbol, enddate=int(enddate), cutoff=int(cutoff))
        return pd.read_sql(select, engine)
    finally:
        engine.dispose()


INSIGHTS_LOOKBACK_DAYS = 20
INSIGHTS_SURGE_FLAG_RATIO = 2.0  # volume multiple at which the treemap badges a tile
INSIGHTS_MIN_HISTORY = 10  # fewer prior days than this and a baseline isn't meaningful


# Results for a given (date, volume floor, ETF selection) only change if
# that day's data does, so a short cache makes repeat loads instant and
# spares the DB the window-function query. Per worker process, like the
# treemap's own cache.
_insights_cache = {}
INSIGHTS_CACHE_SECONDS = 600


def get_insights(enddate, min_volume, funds=None, top_n=8):
    key = (str(enddate), int(min_volume), tuple(sorted(funds or [])), top_n)
    hit = _insights_cache.get(key)
    if hit and time.time() - hit[0] < INSIGHTS_CACHE_SECONDS:
        return hit[1]
    result = _compute_insights(enddate, min_volume, funds, top_n)
    _insights_cache[key] = (time.time(), result)
    return result


def _compute_insights(enddate, min_volume, funds, top_n):
    """What looks unusual on the most recent trading day at or before
    `enddate`, each symbol measured against its OWN trailing 20 trading
    days (not against other symbols): volume surges, and the biggest
    jumps/drops in short % (as z-scores against that symbol's own recent
    short % behavior, same style of measure as the rolling-z backtests).

    Queries the DB directly -- the treemap's cached range only holds the
    selected window, which usually has no history before its own start
    to build a baseline from. `funds` (the treemap's ETF checkboxes)
    scopes the universe the same way the treemap does; the short-% bucket
    filter deliberately isn't applied, since it's a filter on the range's
    *level* and this panel is about *change*.
    """
    # Narrow the query to symbols that can actually appear in the result
    # (in the selected ETFs, and over the volume floor on the as-of day):
    # computing rolling windows for all ~12,000 symbols was by far the
    # dominant cost on the hosted DB, for rows that were then discarded.
    in_scope = None
    if funds:
        src_dir = os.path.dirname(os.path.abspath(__file__))
        etf_df = pd.read_csv(os.path.join(src_dir, data_dir, mapping_file))
        in_scope = [str(sym) for sym in etf_df[etf_df["Fund"].isin(funds)]["Symbol"].unique()]

    engine = get_engine_from_settings()
    try:
        with engine.connect() as conn:
            as_of = conn.execute(
                text('SELECT MAX("Date") FROM "FINRAFileDetail" WHERE "Date" <= :d'),
                {"d": int(enddate)}).scalar()
            if as_of is None:
                return {"as_of": None, "volume_surges": [], "short_jumps": [], "short_drops": []}
            # Calendar-day cutoff comfortably wide enough for 20 trading days.
            cutoff = int((datetime.strptime(str(as_of), '%Y%m%d') - timedelta(days=40)).strftime('%Y%m%d'))
            query = text("""
                WITH scope AS (
                    SELECT "Symbol" FROM "FINRAFileDetail"
                    WHERE "Date" = :as_of AND "TotalVolume" >= :min_volume
                      AND (CAST(:symbols AS text[]) IS NULL OR "Symbol" = ANY(CAST(:symbols AS text[])))
                ),
                daily AS (
                    SELECT "Symbol", "Date", "TotalVolume", "Close",
                           "ShortVolume"::float / "TotalVolume" AS short_pct
                    FROM "FINRAFileDetail"
                    WHERE "Date" BETWEEN :cutoff AND :as_of AND "TotalVolume" > 0
                      AND "Symbol" IN (SELECT "Symbol" FROM scope)
                ),
                w AS (
                    SELECT "Symbol", "Date", "TotalVolume", short_pct, "Close",
                        LAG("Close") OVER (PARTITION BY "Symbol" ORDER BY "Date") AS prev_close,
                        AVG("TotalVolume") OVER prior AS avg_volume,
                        AVG(short_pct) OVER prior AS avg_short_pct,
                        STDDEV(short_pct) OVER prior AS std_short_pct,
                        COUNT(*) OVER prior AS prior_days
                    FROM daily
                    WINDOW prior AS (PARTITION BY "Symbol" ORDER BY "Date"
                                     ROWS BETWEEN :lookback PRECEDING AND 1 PRECEDING)
                )
                SELECT "Symbol" AS symbol, "TotalVolume" AS volume, short_pct,
                       ("Close" / NULLIF(prev_close, 0) - 1) * 100 AS price_change_pct,
                       avg_volume, avg_short_pct, std_short_pct
                FROM w
                WHERE "Date" = :as_of AND prior_days >= :min_history AND "TotalVolume" >= :min_volume
            """)
            df = pd.read_sql(query, conn, params={
                "cutoff": cutoff, "as_of": int(as_of), "lookback": INSIGHTS_LOOKBACK_DAYS,
                "min_history": INSIGHTS_MIN_HISTORY, "min_volume": int(min_volume),
                "symbols": in_scope})
    finally:
        engine.dispose()

    if df.empty:
        # Nothing with enough trailing history (e.g. a gap in the cached
        # data just before this date) -- report that explicitly instead of
        # letting the ranking below choke on an empty frame's object dtypes.
        return {"as_of": int(as_of), "lookback_days": INSIGHTS_LOOKBACK_DAYS, "compared": 0,
                "surge_flag_ratio": INSIGHTS_SURGE_FLAG_RATIO, "surge_flags": {},
                "volume_surges": [], "short_jumps": [], "short_drops": []}

    df = df.assign(
        volume_ratio=df["volume"] / df["avg_volume"],
        short_z=(df["short_pct"] - df["avg_short_pct"]) / df["std_short_pct"].where(df["std_short_pct"] > 0),
        short_change_pts=(df["short_pct"] - df["avg_short_pct"]) * 100,
    )

    def price_change(value):
        # Close can be missing (same-day price not available yet), and a
        # |move| this large is far more likely a stale split adjustment in
        # the cached closes than a real one-day move -- show nothing
        # rather than a number that looks like a data error.
        if pd.isna(value) or abs(value) > 50:
            return None
        return round(float(value), 1)

    def rows(frame):
        out = []
        for r in frame.itertuples():
            out.append({
                "symbol": r.symbol,
                "company": get_company_name(r.symbol),
                "volume": int(r.volume),
                "volume_ratio": round(float(r.volume_ratio), 1),
                "short_pct": round(float(r.short_pct) * 100, 1),
                "avg_short_pct": round(float(r.avg_short_pct) * 100, 1),
                "short_change_pts": round(float(r.short_change_pts), 1),
                "short_z": None if pd.isna(r.short_z) else round(float(r.short_z), 1),
                "price_change_pct": price_change(r.price_change_pct),
            })
        return out

    z = df.dropna(subset=["short_z"])
    return {
        "as_of": int(as_of),
        "lookback_days": INSIGHTS_LOOKBACK_DAYS,
        "compared": len(df),
        # Every in-scope symbol at/above the flag ratio (not just the top
        # few listed) -- the treemap badges all of them.
        "surge_flag_ratio": INSIGHTS_SURGE_FLAG_RATIO,
        "surge_flags": {r.symbol: round(float(r.volume_ratio), 1)
                        for r in df[df["volume_ratio"] >= INSIGHTS_SURGE_FLAG_RATIO].itertuples()},
        "volume_surges": rows(df.nlargest(top_n, "volume_ratio")),
        "short_jumps": rows(z[z["short_z"] > 0].nlargest(top_n, "short_z")),
        "short_drops": rows(z[z["short_z"] < 0].nsmallest(top_n, "short_z")),
    }


def is_today_pacific(yyyymmdd):
    # FINRA doesn't publish a trading day's short-volume file until
    # roughly mid-afternoon Pacific time. Comparing in the server's own
    # timezone (often UTC on a host like Render) would misjudge which
    # calendar day is actually "today" for a Pacific-time data source.
    today = datetime.now(pytz.timezone('US/Pacific')).strftime('%Y%m%d')
    return str(yyyymmdd) == today


def get_csv(url):
    try:
        # Without a timeout, a stalled connection (FINRA's CDN hanging
        # instead of cleanly failing) blocks this call forever -- no
        # exception, no crash, just a silently stuck process. Seen for
        # real: a backfill run and a live web request both went
        # unresponsive at the same moment, almost certainly this.
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        if response.status_code == 403:
            # THIS CODE WON"T WORK BECAUSE THE CONTENT RETURNED IS NOT CLEAN XML
            # tree = ET.fromstring(response.content)
            # print(tree)
            # # testId = tree.find('error').find('code')
            raise requests.HTTPError("No file available from FINRA for ")
        data = pd.read_csv(io.StringIO(response.text), sep="|", index_col=False)
        return data
    except requests.exceptions.MissingSchema as err:
        print("Invalid URL passed")


def index_level_dtypes(df):
    return [f"{df.index.names[i]}: {df.index.get_level_values(n).dtype}"
            for i, n in enumerate(df.index.names)]


def get_engine(user, passwd, host, port, db):
    url = f"postgresql://{user}:{passwd}@{host}:{port}/{db}"
    engine = create_engine(
        url,
        pool_size=5, pool_timeout=10, echo=False)
    return engine


def get_engine_from_settings():
    # A fresh engine is created per request (see fetch_ssdata_raw) and
    # this app only ever uses a handful of connections from it at once,
    # so pool_size=50 was pure headroom that made an engine leaked by a
    # missed engine.dispose() (any exception used to skip it entirely --
    # see fetch_ssdata_raw) far more expensive against Render Postgres's
    # own connection limit. pool_timeout=10 also matters independently
    # of leaks: SQLAlchemy's default pool_timeout is 30s, suspiciously
    # identical to gunicorn's default worker timeout -- if the pool ever
    # is exhausted, the next checkout would otherwise block for just
    # long enough to make gunicorn kill the whole worker instead of the
    # checkout failing with a catchable, fast error.
    #
    # Render auto-populates DATABASE_URL when a database is linked to the
    # service, and keeps it in sync if the password is ever rotated from
    # the Render side, so prefer it over the individual PG_RENDER_* vars.
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        return create_engine(database_url, pool_size=5, pool_timeout=10, echo=False)

    keys = ['pguser', 'pgpasswd', 'pghost', 'pgport', 'pgdb']
    if local_db:
        settings = settings_local
    else:
        settings = settings_render
    if not all(key in keys for key in settings.keys()):
        raise Exception('Bad config file')

    return get_engine(settings['pguser'],
                      settings['pgpasswd'],
                      settings['pghost'],
                      settings['pgport'],
                      settings['pgdb'])


def get_session():
    engine = get_engine_from_settings()
    session = sessionmaker(bind=engine)()
    return session


# Matches Polygon's own free-tier historical cap -- data older than this
# never has a real closing price anyway (see the BadResponse fallback in
# fetch_ssdata_raw), so there's little value in keeping it, and letting
# FINRAFileDetail grow forever is what filled the production disk once
# already (see the DiskFull incident this was added for).
DEFAULT_RETENTION_DAYS = 730


def trim_old_data(retention_days=DEFAULT_RETENTION_DAYS):
    """Delete FINRAFiles rows (and their FINRAFileDetail rows, via the
    existing ON DELETE CASCADE) older than the retention window. Safe to
    call on every cron run -- if nothing is old enough, this deletes zero
    rows.
    """
    cutoff = (datetime.now(pytz.timezone('US/Pacific')) - timedelta(days=retention_days)).strftime('%Y%m%d')
    engine = get_engine_from_settings()
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text('DELETE FROM "FINRAFiles" WHERE "Date" < :cutoff'),
                {"cutoff": int(cutoff)},
            )
            print(f"trim_old_data: removed {result.rowcount} FINRAFiles rows older than {cutoff}")
    finally:
        engine.dispose()


def _paced_polygon_call(state):
    """Sleep as needed to stay under the shared Polygon rate limit, then
    record the call. `state` is a one-item list holding the last call time
    (mutable so callers share one pacing clock)."""
    if state[0] is not None:
        wait = POLYGON_MIN_CALL_INTERVAL - (time.time() - state[0])
        if wait > 0:
            time.sleep(wait)
    state[0] = time.time()


def adjust_closes_for_splits(lookback_days=None, symbols=None, dry_run=False,
                             chunk_size=40, max_symbols=None):
    """Re-pull split-adjusted closing prices for every stored symbol that
    has had a stock split since some of its rows were cached.

    Why this exists: Polygon serves closes adjusted to *today's* split
    basis, but we cache each date's close once, at whatever basis was true
    when it was fetched -- and never revisit it. After a split, a symbol's
    older cached rows (old basis) and rows fetched later (new basis) are
    mixed, with no record of which is which, producing fake 10x "returns".
    Adjusting rows by the split ratio isn't safe for that reason (it would
    double-adjust the rows that are already right), so the only reliable
    repair is to re-fetch the symbol's whole stored history in one
    adjusted get_aggs call and overwrite its closes.

    Each (symbol, split execution date) is recorded in "SplitAdjustments"
    once handled, so this is resumable and cheap to run repeatedly -- a
    daily run only does real work for splits it hasn't seen.

    lookback_days: only consider splits executed in the last N days (the
        daily cron's mode). None = everything since the oldest stored row
        (the one-time backlog; ~1 Polygon call per affected symbol at the
        shared 5/min limit, so potentially hours).
    symbols: optionally restrict to these tickers.
    dry_run: report what would be fetched, change nothing, make no
        per-symbol Polygon calls.
    max_symbols: stop after this many symbols (testing / partial runs).
    """
    pacific_today = datetime.now(pytz.timezone('US/Pacific')).date()
    # A split's adjusted data is only reliable once its execution date has
    # passed, and the same-day-data restriction on the free tier applies
    # to prices too -- so only events strictly before today, prices only
    # through yesterday.
    yesterday = pacific_today - timedelta(days=1)
    engine = get_engine_from_settings()
    client = RESTClient(apikey)
    pace = [None]
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS "SplitAdjustments" (
                    "Symbol" VARCHAR(10) NOT NULL,
                    "ExecutionDate" BIGINT NOT NULL,
                    "SplitFrom" DOUBLE PRECISION,
                    "SplitTo" DOUBLE PRECISION,
                    "AdjustedAt" TIMESTAMP DEFAULT now(),
                    PRIMARY KEY ("Symbol", "ExecutionDate")
                )"""))
            oldest = conn.execute(text('SELECT MIN("Date") FROM "FINRAFileDetail"')).scalar()
            already = {(r[0], r[1]) for r in conn.execute(
                text('SELECT "Symbol", "ExecutionDate" FROM "SplitAdjustments"')).fetchall()}
        if oldest is None:
            print("adjust_closes_for_splits: no stored data.")
            return {"symbols": 0, "rows_changed": 0}

        if lookback_days is not None:
            since = pacific_today - timedelta(days=lookback_days)
        else:
            since = datetime.strptime(str(oldest), '%Y%m%d').date()

        print(f"Listing splits executed {since}..{yesterday}")
        events = []
        _paced_polygon_call(pace)
        try:
            for i, sp in enumerate(client.list_splits(
                    execution_date_gte=since.isoformat(), execution_date_lte=yesterday.isoformat(),
                    limit=1000, sort='execution_date', order='asc'), start=1):
                events.append((sp.ticker, int(sp.execution_date.replace('-', '')), sp.split_from, sp.split_to))
                if i % 1000 == 0:
                    time.sleep(POLYGON_MIN_CALL_INTERVAL)  # next page is another call
        except (BadResponse, AuthError, MaxRetryError) as err:
            print(f"adjust_closes_for_splits: couldn't list splits ({err}); try again later.")
            return {"symbols": 0, "rows_changed": 0}
        if symbols:
            wanted = set(symbols)
            events = [e for e in events if e[0] in wanted]

        candidates = sorted({e[0] for e in events})
        with engine.connect() as conn:
            stored = {r[0]: (r[1], r[2]) for r in conn.execute(
                text('SELECT "Symbol", MIN("Date"), MAX("Date") FROM "FINRAFileDetail" '
                     'WHERE "Symbol" = ANY(CAST(:syms AS text[])) GROUP BY "Symbol"'),
                {"syms": candidates}).fetchall()}
            latest = conn.execute(text('SELECT MAX("Date") FROM "FINRAFileDetail"')).scalar()
            volume = {r[0]: r[1] or 0 for r in conn.execute(
                text('SELECT "Symbol", "TotalVolume" FROM "FINRAFileDetail" '
                     'WHERE "Date" = :d AND "Symbol" = ANY(CAST(:syms AS text[]))'),
                {"d": latest, "syms": candidates}).fetchall()}

        # Only symbols we store with rows from *before* a split we haven't
        # handled yet -- rows after the split were fetched on the new basis.
        pending = {}
        for ticker, exec_date, split_from, split_to in events:
            if ticker not in stored or (ticker, exec_date) in already:
                continue
            if stored[ticker][0] < exec_date:
                pending.setdefault(ticker, []).append((exec_date, split_from, split_to))
        # Highest-volume (most visible) symbols first, so an interrupted
        # backlog run has already fixed the names that matter most.
        order = sorted(pending, key=lambda t: volume.get(t, 0), reverse=True)
        if max_symbols is not None:
            order = order[:max_symbols]

        print(f"{len(order)} symbol(s) need their closes re-fetched "
              f"(~{len(order) * POLYGON_MIN_CALL_INTERVAL / 60:.0f} min at the Polygon rate limit).")
        if dry_run:
            print("Dry run -- first few:", order[:15])
            return {"symbols": len(order), "rows_changed": 0}

        total_changed = 0
        buffer = []  # (symbol, [(date_int, close)], events)

        def flush():
            nonlocal total_changed, buffer
            if not buffer:
                return
            by_date = {}
            for sym, bars, _ in buffer:
                for d, close in bars:
                    by_date.setdefault(d, []).append((sym, close))
            changed = 0
            with engine.begin() as conn:
                # One statement per date: the Date index narrows each to
                # that day's ~12k rows, instead of scanning the whole table
                # per symbol (there's no Symbol index).
                for d, pairs in by_date.items():
                    result = conn.execute(text("""
                        UPDATE "FINRAFileDetail" t SET "Close" = v.c
                        FROM unnest(CAST(:syms AS text[]), CAST(:closes AS float8[])) AS v(s, c)
                        WHERE t."Date" = :d AND t."Symbol" = v.s AND t."Close" IS DISTINCT FROM v.c
                    """), {"d": d, "syms": [p[0] for p in pairs], "closes": [p[1] for p in pairs]})
                    changed += result.rowcount
                for sym, _, evs in buffer:
                    for exec_date, split_from, split_to in evs:
                        conn.execute(text("""
                            INSERT INTO "SplitAdjustments" ("Symbol", "ExecutionDate", "SplitFrom", "SplitTo")
                            VALUES (:s, :e, :f, :t) ON CONFLICT DO NOTHING"""),
                            {"s": sym, "e": exec_date, "f": split_from, "t": split_to})
            total_changed += changed
            print(f"  applied {len(buffer)} symbol(s), {changed} rows changed")
            buffer = []

        ny = pytz.timezone('America/New_York')
        for n, sym in enumerate(order, start=1):
            first, last = stored[sym]
            from_ = datetime.strptime(str(first), '%Y%m%d').date()
            to_ = min(datetime.strptime(str(last), '%Y%m%d').date(), yesterday)
            _paced_polygon_call(pace)
            try:
                aggs = client.get_aggs(sym, 1, "day", from_.isoformat(), to_.isoformat(),
                                       adjusted=True, limit=50000)
            except (BadResponse, AuthError, MaxRetryError) as err:
                # Not logged as handled, so a later run retries it.
                print(f"  {sym}: skipped ({err})")
                continue
            bars = [(int(datetime.fromtimestamp(a.timestamp / 1000, tz=pytz.utc)
                         .astimezone(ny).strftime('%Y%m%d')), float(a.close))
                    for a in aggs if a.close is not None]
            print(f"[{n}/{len(order)}] {sym}: {len(bars)} bars")
            buffer.append((sym, bars, pending[sym]))
            if len(buffer) >= chunk_size:
                flush()
        flush()
        print(f"Done: {len(order)} symbol(s), {total_changed} rows changed.")
        return {"symbols": len(order), "rows_changed": total_changed}
    finally:
        engine.dispose()


def ensure_ssdata_cached(startdate, enddate=0):
    """Ensure FINRA/Polygon data for the date range is loaded into Postgres.
    Does not return the data -- see fetch_ssdata_raw() for that.

    This is the expensive part (network + DB) and should only be re-run
    when the requested date range changes, not on every filter tweak.
    Callers that only care about the caching side effect (the daily
    prewarm job, the one-time history backfill) should call this
    directly rather than fetch_ssdata_raw() -- that additionally does
    one bulk read of the *entire* requested range's FINRAFileDetail rows
    into a single DataFrame at the end, which for a wide range (e.g. the
    2-year backfill) can be millions of rows and multiple GB, and is
    pure wasted memory if nothing ever uses the returned DataFrame. This
    is what was actually causing the backfill Cron Job's repeated
    out-of-memory failures -- not a leak in the per-date fetch loop
    (which commits incrementally and is genuinely resumable), but this
    one-shot full-range load running unconditionally at the end every
    single time, regardless of how few dates were newly fetched.
    """
    file_date = re.sub("\/", "", startdate)
    input_date = startdate
    temp_start = startdate
    pd.set_option('display.max_rows', None)

    values = range(0)
    if enddate != 0:
        numDays = (datetime.strptime(enddate, '%Y%m%d') - datetime.strptime(startdate, '%Y%m%d')).days
        values = range(numDays + 1)
    else:
        numDays = 0
    # print(numDays)

    dates = []
    start_time = time.time()
    for i in values:
        cur_day = datetime.strptime(temp_start, '%Y%m%d') + timedelta(days=i)
        file_date = cur_day.strftime('%Y%m%d')
        dates.append(file_date)

    date_list = dates.copy()
    print("to_sql duration: {} seconds".format(time.time() - start_time))
    print(dates)

    sql_string = '''SELECT
    COALESCE("[finra_no_file].[date]", "[to_finra_test].[Date]") as date
    FROM
    finra_no_file
    FULL
    JOIN
    to_finra_test
    ON
    ["finra_no_file"].["date"] = ["to_finra_test"].["Date"]
    '''

    # print(engine.url.database)
    try:
        session = get_session()
        # session.close()
        engine = session.get_bind()
        conn = engine.connect()
        metadata = MetaData()

        finra_files = Table('FINRAFiles', metadata,
                            Column('Date', BIGINT, primary_key=True),
                            Column('FileURL', String(100))
                            )

        finra_file_detail = Table('FINRAFileDetail', metadata,
                                  # index=True: every query in this app filters
                                  # FINRAFileDetail by Date, including the
                                  # self-heal existence check, and this table
                                  # has millions of rows with no index at all --
                                  # a foreign key does NOT implicitly index the
                                  # referencing column in Postgres. Likely the
                                  # actual cause of a worker timeout observed in
                                  # production right after the self-heal fix
                                  # started actually running its EXISTS check
                                  # against this table for real.
                                  Column('Date', BIGINT, ForeignKey('FINRAFiles.Date', ondelete='CASCADE'), nullable=False, index=True),
                                  Column('Symbol', String(10)),
                                  Column('ShortVolume', BIGINT),
                                  Column('ShortExemptVolume', BIGINT),
                                  Column('TotalVolume', BIGINT),
                                  Column('Market', String(10)),
                                  Column('Close', Float)
                                  )
        metadata.create_all(engine)

        # metadata.create_all() only creates tables that don't exist yet -- it
        # does not retroactively alter an existing table's schema, so the
        # index=True above has no effect on the FINRAFileDetail table that's
        # already live in production. CONCURRENTLY avoids taking a lock that
        # would block reads/writes on this table while the index builds, and
        # must run outside of any transaction.
        #
        # This must only run ONCE per process, not on every request: Postgres
        # requires CREATE INDEX CONCURRENTLY to wait for every transaction
        # that was already open when it started to finish before it can
        # complete. If a prior worker was ever SIGKILLed (gunicorn's worker
        # timeout does exactly this) while holding a connection open, that
        # connection can look "not yet finished" to Postgres for a while
        # after the process is already gone -- and re-issuing this same
        # CREATE INDEX on every single request, each potentially getting
        # killed the same way, is a plausible way to keep compounding
        # exactly that problem instead of it ever clearing.
        global _finrafiledetail_date_index_ensured
        if not _finrafiledetail_date_index_ensured:
            index_conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
            try:
                index_conn.execute(text(
                    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_finrafiledetail_date '
                    'ON "FINRAFileDetail" ("Date")'
                ))
            finally:
                index_conn.close()
            _finrafiledetail_date_index_ensured = True

        # A date only counts as done if it actually has detail rows, or
        # it's a confirmed no-file day that's also a weekend. Two distinct
        # broken states get self-healed here:
        #  - FileURL set but zero FINRAFileDetail rows: the FINRA fetch
        #    succeeded but something crashed before writing detail rows
        #    (e.g. the Polygon closing-price step).
        #  - FileURL IS NULL on a WEEKDAY: FINRA genuinely has no file for
        #    weekends, so a null FileURL there is trustworthy forever, but
        #    the same marker on a weekday means some earlier attempt
        #    failed for an unrelated/transient reason (queried before
        #    FINRA published, a network blip, anything before the
        #    is_today_pacific fix existed) and got permanently
        #    blacklisted by the old code even though real data exists for
        #    that trading day. NYSE holidays are the one gap this doesn't
        #    close -- a real weekday holiday will keep getting retried on
        #    every request touching it instead of being cached, which
        #    costs an occasional wasted FINRA/Polygon call but is
        #    otherwise harmless.
        #  - Detail rows exist but almost none have a Close: Polygon's
        #    free tier has no same-day data -- a day's prices aren't
        #    queryable until roughly 8am PT the *next* morning, but the
        #    daily cron fetches each day same-afternoon (FINRA's own file
        #    is ready by then, Polygon's isn't), so the day it just
        #    fetched always gets an all-NULL Close on that first attempt.
        #    Threshold is 50%, not "any missing", because a small
        #    fraction of symbols never having Polygon coverage is normal
        #    and permanent (~2% baseline) -- retrying those forever would
        #    defeat the cache entirely. A genuinely brand-new date (zero
        #    existing rows) correctly falls through to NULL here, not 0,
        #    so it isn't mistaken for "done" either.
        select = text("""
                    SELECT "Date"
                    FROM "FINRAFiles" f
                    WHERE "Date" IN :date_list
                    AND (
                        (
                            "FileURL" IS NULL
                            AND EXTRACT(ISODOW FROM TO_DATE(CAST("Date" AS TEXT), 'YYYYMMDD')) IN (6, 7)
                        )
                        OR (
                            SELECT COUNT(*) FILTER (WHERE d."Close" IS NOT NULL)::float / NULLIF(COUNT(*), 0)
                            FROM "FINRAFileDetail" d WHERE d."Date" = f."Date"
                        ) >= 0.5
                    )
                    """)
        select = select.bindparams(date_list=tuple(date_list))
        with engine.begin() as con:
            for row in con.execute(select):
                # remove entries that already exist
                dates.remove(str(row.Date))

        print("Still need to load files from FINRA for ... ", dates)

        sql_compare = '''
            SELECT  IF NOT EXISTS finra_no_file (date varchar(10) NOT NULL,
            UNIQUE (date)
            )
        '''

        last_polygon_call = None
        for d in dates:
            finra_file = finra_dir + f'{d}.txt'
            try:
                print(finra_file)
                ssdata_temp = get_csv(finra_file)
                ssdata_temp.drop(ssdata_temp.tail(1).index, inplace=True)  # drop last n rows
                start_time = time.time()
                # ON CONFLICT: a date being reprocessed here (e.g. self-healing
                # a previously broken/incomplete date, see the query above)
                # already has a FINRAFiles row from the earlier attempt.
                sql = text("""
                    INSERT INTO "FINRAFiles" ("Date", "FileURL") VALUES (:date, :file)
                    ON CONFLICT ("Date") DO UPDATE SET "FileURL" = EXCLUDED."FileURL"
                """)
                sql = sql.bindparams(date=d, file=finra_file)
                #engine.execute(sql)
                print("Before Insert into FINRA DB")

                conn.execute(sql)
                conn.commit()

                try:
                    if last_polygon_call is not None:
                        wait = POLYGON_MIN_CALL_INTERVAL - (time.time() - last_polygon_call)
                        if wait > 0:
                            time.sleep(wait)
                    last_polygon_call = time.time()
                    client = RESTClient(apikey)
                    aggs = client.get_grouped_daily_aggs(f"{d[:4]}-{d[4:6]}-{d[6:]}")
                    data = []
                    for agg in aggs:
                        data.append({
                            "Symbol": agg.ticker,
                            "Close": agg.close
                        })
                    polygondf = pd.DataFrame(data)
                except (BadResponse, AuthError, MaxRetryError) as e:
                    # BadResponse: Polygon rejects grouped-aggregates requests
                    # for the current date until end of day on this account's
                    # tier ("Attempted to request today's data before end of
                    # day"). AuthError: POLYGON_API_KEY isn't configured in
                    # this environment (e.g. missing on a deploy target).
                    # MaxRetryError: the client's own retries against a 429
                    # were exhausted -- e.g. ESFuturesData burning the same
                    # shared rate-limit budget concurrently, despite our own
                    # pacing above. None of these have anything to do with
                    # whether FINRA's own short-volume file (already fetched
                    # successfully above) is available -- fall back to a
                    # closing price of NULL for this date rather than losing
                    # the whole day's short-volume data, and every other
                    # date in the requested range along with it, over a
                    # price lookup.
                    print(f"[!] Polygon closing prices unavailable for {d}: {e}")
                    polygondf = pd.DataFrame(columns=["Symbol", "Close"])
                mergeddf = pd.merge(polygondf, ssdata_temp, on='Symbol', how='right')
                # print(mergeddf)
                print("Before writing FINRA file to SQL")
                # This date may already have detail rows from an earlier
                # attempt (e.g. the self-heal retry above, for a date that
                # got an all-NULL Close the first time) -- clear them first
                # so re-inserting doesn't duplicate every row for the date.
                # A no-op for a genuinely first-time fetch.
                conn.execute(text('DELETE FROM "FINRAFileDetail" WHERE "Date" = :date'), {"date": int(d)})
                conn.commit()
                mergeddf.to_sql('FINRAFileDetail', con=engine, if_exists='append', index=False)
                print("to_sql duration: {} seconds".format(time.time() - start_time))
                # Also load the closing price of the day for each ticker in the FINRA file and update FINRAFileDetail

                temp_start = input_date
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                # A stalled/unreachable connection to FINRA is a transient
                # network problem, not evidence the file doesn't exist --
                # unlike the 403 case below, don't write a permanent
                # "no file" marker for it. Leaving no FINRAFiles row at
                # all means this date is still "missing" and gets retried
                # on the next run, rather than being wrongly blacklisted.
                print(f"[!] Network error fetching FINRA data for {d}: {e}")
                continue
            except requests.HTTPError as e:
                print(f"[!] Exception caught: {e}{d}")
                # Create entry in db to indicate no file ONLY if date is not today.
                # FINRA's file for the current trading day isn't published until
                # mid-afternoon Pacific time, so a fetch attempted earlier in the
                # day fails the same way a weekend/holiday does. Caching that as
                # a permanent "no file" record would keep skipping today's date
                # even after the real file becomes available later -- leaving
                # today unmarked lets a later request this same day retry it.
                if not is_today_pacific(d):
                    # ON CONFLICT: this date may already have a FINRAFiles row
                    # from an earlier broken/incomplete attempt being retried.
                    sql = text("""
                                    INSERT INTO "FINRAFiles" ("Date") VALUES (:date)
                                    ON CONFLICT ("Date") DO UPDATE SET "FileURL" = NULL
                                """)
                    sql = sql.bindparams(date=d)
                    print("In Exception handling")
                    conn.execute(sql)
                    conn.commit()

                if numDays == 0:
                    prior_day = datetime.strptime(temp_start, '%Y%m%d') - timedelta(days=1)
                    temp_start = prior_day.strftime('%Y%m%d')
                    finra_file = finra_dir + f'{temp_start}.txt'
                continue

        # if temp_start == input_date:
        #     break

        # At this point all FINRA data for selected timeframe is stored in the database
    finally:
        engine.dispose()  # Close all checked in sessions -- always, even on error


def fetch_ssdata_raw(startdate, enddate=0):
    """Ensure FINRA/Polygon data for the date range is loaded into Postgres,
    then return the raw, unfiltered per-symbol daily rows for that range.

    This is what the web app uses -- it needs the actual data back to
    build a response. Callers that only need the caching side effect
    should call ensure_ssdata_cached() directly instead; see its
    docstring for why (this function's final bulk read can be millions
    of rows for a wide range, wasted if nothing uses the return value).
    """
    ensure_ssdata_cached(startdate, enddate)

    # Recomputing date_list here is cheap (pure date arithmetic, no
    # network/DB cost) and keeps this function's only remaining job --
    # reading back the now-cached range -- independent of
    # ensure_ssdata_cached()'s internals.
    values = range(0)
    if enddate != 0:
        numDays = (datetime.strptime(enddate, '%Y%m%d') - datetime.strptime(startdate, '%Y%m%d')).days
        values = range(numDays + 1)
    date_list = [(datetime.strptime(startdate, '%Y%m%d') + timedelta(days=i)).strftime('%Y%m%d') for i in values]

    engine = get_engine_from_settings()
    try:
        print("Load the following dates from db ... ", date_list)
        select = text("""
            SELECT * FROM "FINRAFileDetail" WHERE "Date" IN :datelist ORDER BY "Date"
        """)
        select = select.bindparams(datelist=tuple(date_list))
        raw_df = pd.read_sql(select, engine)
    finally:
        engine.dispose()

    return raw_df


# Mirrors percentBuckets in static/js/treemap.js -- that's what actually
# groups/colors the treemap, this is what decides which rows are even
# eligible to show up there. Keep the two in sync if the ranges ever change.
PERCENT_BUCKETS = {
    "50plus": (0.50, float('inf')),
    "40to50": (0.40, 0.50),
    "30to40": (0.30, 0.40),
    "under30": (float('-inf'), 0.30),
}


def build_ssdata(raw_df, minvol=5000000, percbuckets="50plus,40to50,30to40,under30", etfs=0):
    """Filter/aggregate already-fetched raw FINRA data into the treemap and
    detail views. Pure in-memory pandas work, no network or DB access, so
    it's cheap to re-run on every filter (toggle) change.
    """
    src_dir = os.path.dirname(os.path.abspath(__file__))
    # Flask route params arrive as strings; the old SQL-side filter let
    # Postgres coerce them implicitly, but pandas comparisons need explicit
    # numeric types.
    minvol = int(minvol)
    selected_buckets = [b for b in percbuckets.split(",") if b in PERCENT_BUCKETS]

    if raw_df.empty:
        empty = raw_df.to_json(orient='records')
        return [empty, empty]

    pct = raw_df["ShortVolume"] / raw_df["TotalVolume"]
    # No buckets selected genuinely means "show nothing" -- not a fallback
    # to "show everything", which would be surprising if someone unchecks
    # every toggle on purpose.
    bucket_mask = pd.Series(False, index=raw_df.index)
    for bucket in selected_buckets:
        lo, hi = PERCENT_BUCKETS[bucket]
        bucket_mask |= (pct >= lo) & (pct < hi)

    finra_df = raw_df[
        (raw_df["TotalVolume"] > minvol) & bucket_mask
    ].copy()

    if finra_df.empty:
        print("Empty DF - return first recent day with data")
        empty = finra_df.to_json(orient='records')
        return [empty, empty]
    yfMaxDate = finra_df["Date"].max()
    # Master df with daily totals that will be used for detailed breakdown
    detail_df = finra_df.copy()
    detail_df["LongVolume"] = detail_df["TotalVolume"] - detail_df["ShortVolume"]
    detail_df.drop(columns=["ShortExemptVolume", "Market"], inplace=True)
    decimals = 2
    # Start date for Yahoo Finance data should still be the min date in the FINRA df
    start = datetime.strptime(str(detail_df["Date"].min()), '%Y%m%d')
    end = datetime.strptime(str(detail_df["Date"].max()), '%Y%m%d')
    # end = min([datetime.strptime(str(yfMaxDate), '%Y%m%d') + timedelta(days=1), datetime.today() + timedelta(days=1)])
    # print("Date Range: ", start.strftime('%Y%m%d'), " - ", end.strftime('%Y%m%d') )
    # finra_df[finra_df.Symbol == 'SUNE'])
    close_df = detail_df.copy()
    # print("Here")
    # print(start_df)
    close_df.drop(columns=["ShortVolume","TotalVolume","LongVolume"], inplace=True)
    start_df = close_df[(close_df.Date == int(start.strftime('%Y%m%d')))]
    end_df = close_df[(close_df.Date == int(end.strftime('%Y%m%d')))]
    # print("Start DF")
    closingprices_df = pd.merge(start_df, end_df, on='Symbol')
    closingprices_df[['Close_x', 'Close_y']] = closingprices_df[['Close_x', 'Close_y']].astype(float)
    closingprices_df['gain'] = ((closingprices_df['Close_y']/closingprices_df['Close_x'])-1)
    closingprices_df.drop(columns=["Close_x", "Close_y","Date_x","Date_y"], inplace=True)
    closingprices_df['gain'] = closingprices_df['gain'].apply(lambda x: round(x, decimals+2))
    # print(closingprices_df)
    # print("FINRA DF - DATES SHOULD ALL BE CORRECT STILL: ", finra_df[finra_df.Symbol =='SUNE'])
    # Statement below sums date field since there are multiple entries
    finra_df = finra_df.groupby('Symbol').sum().reset_index()
    finra_df.sort_values(by=["Date"], inplace=True)

    finra_df['Percentile'] = finra_df.TotalVolume.rank(pct=True)

    etf_df = pd.read_csv(os.path.join(src_dir, data_dir, mapping_file))
    funds = ["SPX", "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XRT", "Other"]
    if etfs != 0:
        etf_df = etf_df[etf_df["Fund"].isin(funds)]

    mapped_df = pd.merge(finra_df, etf_df, on='Symbol')
    mapped_df["Short%"] = mapped_df["ShortVolume"] / mapped_df["TotalVolume"]
    mapped_df["name"] = mapped_df["Fund"] + "." + mapped_df["Symbol"]

    mapped_df.drop(
        columns=["Date", "ShortVolume", "ShortExemptVolume", "Name", "% Holding"], inplace=True)

    mapped_df['Short%'] = mapped_df['Short%'].apply(lambda x: round(x, decimals))
    mapped_df.rename(columns={'Short%': 'value', 'TotalVolume': 'size', 'Symbol': 'symbol'}, inplace=True)
    mapped_df = mapped_df[mapped_df.name != '']
    closingprices_df.rename(columns={'Symbol': 'symbol'}, inplace=True)
    final_df = pd.merge(mapped_df, closingprices_df, on='symbol')

    return [final_df.to_json(orient='records'), detail_df.to_json(orient='records')]
