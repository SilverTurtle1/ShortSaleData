import io
import os
import re
import time

import yfinance as yf
from datetime import datetime
from datetime import timedelta

import pandas as pd
import requests

from sqlalchemy import MetaData, Table, Column, String, BIGINT, ForeignKey, text, Float
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy_utils import database_exists, create_database

from polygon import RESTClient

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

finra_dir = r'https://cdn.finra.org/equity/regsho/daily/CNMSshvol'
data_dir = r'static/data/'
mapping_file = 'etfMapping-backup.csv'
#min_volume = 1  # 5M shares traded daily min
# Render sets the RENDER env var on every deployed service, so this picks
# the Render-hosted Postgres in production and the local one everywhere else.
local_db = os.environ.get('RENDER') is None


def get_company_name(symbol):
    src_dir = os.path.dirname(os.path.abspath(__file__))
    etf_df = pd.read_csv(os.path.join(src_dir, data_dir, mapping_file))
    match = etf_df.loc[etf_df["Symbol"] == symbol, "Name"]
    return match.iloc[0] if not match.empty else None


def get_csv(url):
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
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
        pool_size=50, echo=False)
    return engine


def get_engine_from_settings():
    # Render auto-populates DATABASE_URL when a database is linked to the
    # service, and keeps it in sync if the password is ever rotated from
    # the Render side, so prefer it over the individual PG_RENDER_* vars.
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        return create_engine(database_url, pool_size=50, echo=False)

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

def fetch_ssdata_raw(startdate, enddate=0):
    """Ensure FINRA/Polygon data for the date range is loaded into Postgres,
    then return the raw, unfiltered per-symbol daily rows for that range.

    This is the expensive part (network + DB) and should only be re-run
    when the requested date range changes, not on every filter tweak.
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
                              Column('Date', BIGINT, ForeignKey('FINRAFiles.Date', ondelete='CASCADE'), nullable=False),
                              Column('Symbol', String(10)),
                              Column('ShortVolume', BIGINT),
                              Column('ShortExemptVolume', BIGINT),
                              Column('TotalVolume', BIGINT),
                              Column('Market', String(10)),
                              Column('Close', Float)
                              )
    metadata.create_all(engine)

    select = text("""
                SELECT "Date"
                FROM "FINRAFiles"
                WHERE "Date" IN :date_list
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

    for d in dates:
        finra_file = finra_dir + f'{d}.txt'
        try:
            print(finra_file)
            ssdata_temp = get_csv(finra_file)
            ssdata_temp.drop(ssdata_temp.tail(1).index, inplace=True)  # drop last n rows
            start_time = time.time()
            sql = text("""
                INSERT INTO "FINRAFiles" ("Date", "FileURL") VALUES (:date, :file)
            """)
            sql = sql.bindparams(date=d, file=finra_file)
            #engine.execute(sql)
            print("Before Insert into FINRA DB")

            conn.execute(sql)
            conn.commit()

            client = RESTClient(apikey)
            aggs = client.get_grouped_daily_aggs(f"{d[:4]}-{d[4:6]}-{d[6:]}")
            data = []
            for agg in aggs:
                data.append({
                    "Symbol": agg.ticker,
                    "Close": agg.close
                })
            polygondf = pd.DataFrame(data)
            mergeddf = pd.merge(polygondf, ssdata_temp, on='Symbol', how='right')
            # print(mergeddf)
            print("Before writing FINRA file to SQL")
            mergeddf.to_sql('FINRAFileDetail', con=engine, if_exists='append', index=False)
            print("to_sql duration: {} seconds".format(time.time() - start_time))
            # Also load the closing price of the day for each ticker in the FINRA file and update FINRAFileDetail

            temp_start = input_date
        except requests.HTTPError as e:
            print(f"[!] Exception caught: {e}{d}")
            # Create entry in db to indicate no file ONLY if date is not today
            sql = text("""
                            INSERT INTO "FINRAFiles" ("Date") VALUES (:date)
                        """)
            sql = sql.bindparams(date=d)
            print("In Exception handling")
            conn.execute(sql)
            conn.commit()
            #engine.execute(sql)

            if numDays == 0:
                prior_day = datetime.strptime(temp_start, '%Y%m%d') - timedelta(days=1)
                temp_start = prior_day.strftime('%Y%m%d')
                finra_file = finra_dir + f'{temp_start}.txt'
            continue

    # if temp_start == input_date:
    #     break

    # At this point all FINRA data for selected timeframe is stored in the database
    # temp_df = ssdata_temp[(ssdata_temp.TotalVolume > min_volume)]

    print("Load the following dates from db ... ", date_list)
    select = text("""
        SELECT * FROM "FINRAFileDetail" WHERE "Date" IN :datelist ORDER BY "Date"
    """)
    select = select.bindparams(datelist=tuple(date_list))
    print(select)
    raw_df = pd.read_sql(select, engine)

    engine.dispose()  # Close all checked in sessions

    return raw_df


def build_ssdata(raw_df, minvol=5000000, percshort=50.00, etfs=0):
    """Filter/aggregate already-fetched raw FINRA data into the treemap and
    detail views. Pure in-memory pandas work, no network or DB access, so
    it's cheap to re-run on every filter (slider) change.
    """
    src_dir = os.path.dirname(os.path.abspath(__file__))
    # Flask route params arrive as strings; the old SQL-side filter let
    # Postgres coerce them implicitly, but pandas comparisons need explicit
    # numeric types.
    minvol = int(minvol)
    percshort = float(percshort)

    if raw_df.empty:
        empty = raw_df.to_json(orient='records')
        return [empty, empty]

    finra_df = raw_df[
        (raw_df["TotalVolume"] > minvol) &
        ((raw_df["ShortVolume"] / raw_df["TotalVolume"]) >= (percshort / 100))
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
