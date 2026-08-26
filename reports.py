from decimal import Decimal

from sqlalchemy import text

from finra import get_engine_from_settings


def _jsonable(value):
    # Postgres numeric columns come back as Decimal, which json.dumps
    # doesn't know how to serialize on its own.
    if isinstance(value, Decimal):
        return float(value)
    return value

# Function names here are never taken from user input -- only from this
# hardcoded registry -- so building the SQL call with an f-string is safe.
# Parameter *values* are always passed as bind params, never interpolated.
REPORTS = {
    "daily_buys": {
        "label": "Daily Buys",
        "description": "Symbols on a single day with unusually high volume and buy% relative to their own historical average.",
        "function": "dp_daily_buys",
        "params": [
            # today_aware: FINRA doesn't publish a trading day's file until
            # roughly mid-afternoon Pacific time, so this defaults to today
            # and lets it be picked, but only once it's actually likely to
            # have data -- otherwise it defaults to (and caps at) yesterday.
            {"name": "date", "label": "Date", "input": "date", "cast": "yyyymmdd", "today_aware": True},
            # format: "number" -- displayed comma-grouped (e.g. 5,000,000)
            # and reformatted live as you type, since a plain type=number
            # input can't show digit grouping at all.
            {"name": "vol", "label": "Min Total Volume", "input": "number", "cast": "int", "default": 5000000, "step": 100000, "format": "number"},
            {"name": "shortperc", "label": "Min Buy % (0-1)", "input": "number", "cast": "float", "default": 0.5, "step": 0.01, "min": 0, "max": 1},
            {"name": "volpercent", "label": "Min Volume vs Avg (x)", "input": "number", "cast": "float", "default": 1.5, "step": 0.1, "min": 0},
        ],
        # Controls result-table column order, labels, and value formatting.
        # Raw names/order here must match dp_daily_buys' RETURNS TABLE
        # exactly -- run_report() returns whatever Postgres calls them.
        "columns": [
            # "date" is deliberately omitted -- it's a report parameter,
            # identical on every row, so showing it per-row is just noise.
            {"name": "symbol", "label": "Symbol"},
            {"name": "totvol", "label": "Volume", "format": "number"},
            {"name": "avgvol", "label": "30-Day Avg Volume", "format": "number"},
            {"name": "pctavgvol", "label": "Volume vs Avg", "format": "multiplier"},
            {"name": "buypct", "label": "Buy %", "format": "percent"},
            {"name": "avgbuypct", "label": "30-Day Avg Buy %", "format": "percent"},
            {"name": "pctavgbuy", "label": "Buy % vs Avg", "format": "multiplier"},
        ],
        # Sorted this way by default so the most unusual rows are visible
        # without needing to click a header first.
        "default_sort": {"column": "pctavgvol", "dir": -1},
    },
    "ticker_detail": {
        "label": "Ticker Detail",
        "description": "Daily volume and buy% history for a single ticker over a date range.",
        "function": "dp_ticker_detail",
        "params": [
            {"name": "ticker", "label": "Ticker", "input": "text", "cast": "ticker"},
            {"name": "startdate", "label": "Start Date", "input": "date", "cast": "yyyymmdd"},
            {"name": "enddate", "label": "End Date", "input": "date", "cast": "yyyymmdd"},
        ],
    },
    "ticker_detail_test": {
        "label": "Ticker Detail (with Returns)",
        "description": "Ticker Detail plus 5-day and 22-day price return calculations.",
        "function": "dp_ticker_detail_test",
        "params": [
            {"name": "ticker", "label": "Ticker", "input": "text", "cast": "ticker"},
            {"name": "startdate", "label": "Start Date", "input": "date", "cast": "yyyymmdd"},
            {"name": "enddate", "label": "End Date", "input": "date", "cast": "yyyymmdd"},
        ],
    },
}


def _cast_param(spec, raw_value):
    if raw_value is None or raw_value == "":
        raise ValueError(f'Missing value for "{spec["label"]}"')

    cast = spec.get("cast")
    if cast == "yyyymmdd":
        # raw_value is "YYYY-MM-DD" from an <input type="date">
        return int(raw_value.replace("-", ""))
    if cast == "int":
        return int(raw_value)
    if cast == "float":
        return float(raw_value)
    if cast == "ticker":
        return raw_value.strip().upper()
    return raw_value


def run_report(report_key, raw_params):
    if report_key not in REPORTS:
        raise KeyError(f"Unknown report: {report_key}")

    report = REPORTS[report_key]
    values = [_cast_param(spec, raw_params.get(spec["name"])) for spec in report["params"]]

    placeholders = ", ".join(f":p{i}" for i in range(len(values)))
    bind = {f"p{i}": v for i, v in enumerate(values)}
    sql = text(f'SELECT * FROM public.{report["function"]}({placeholders})').bindparams(**bind)

    engine = get_engine_from_settings()
    try:
        with engine.connect() as conn:
            result = conn.execute(sql)
            columns = list(result.keys())
            rows = [[_jsonable(v) for v in row] for row in result.fetchall()]
    finally:
        engine.dispose()

    return columns, rows
