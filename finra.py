import io
import os
import re
import time
from multiprocessing.pool import CLOSE

import yfinance as yf
from datetime import datetime
from datetime import timedelta

from importlib.metadata import version
import pandas as pd
import requests

from sqlalchemy import MetaData, Table, Column, String, BIGINT, ForeignKey, text, Float
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Relationship, relationship
from sqlalchemy_utils import database_exists, create_database

from polygon import RESTClient

from local_settings import postgresql_local as settings_local
from local_settings import postgresql_render as settings_render
from local_settings import polygonAPIkey as apikey

finra_dir = r'https://cdn.finra.org/equity/regsho/daily/CNMSshvol'
data_dir = r'static/data/'
mapping_file = 'etfMapping-backup.csv'
#min_volume = 1  # 5M shares traded daily min
local_db = False


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
    #url = f"postgresql://pguser:zmfLzC3hqRf43N5abIpIbdkmllswE9Hj@dpg-ct6h009u0jms7396hdkg-a.oregon-postgres.render.com/alpha_flsq"
    #if not database_exists(url):
    #    create_database(url)
    #postgresql://pguser:zmfLzC3hqRf43N5abIpIbdkmllswE9Hj@dpg-ct6h009u0jms7396hdkg-a.oregon-postgres.render.com/alpha_flsq
    #postgresql://pguser:zmfLzC3hqRf43N5abIpIbdkmllswE9Hj@dpg-ct6h009u0jms7396hdkg-a/alpha_flsq
    engine = create_engine(
        url,
        pool_size=50, echo=False)
    return engine


def get_engine_from_settings():
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

def myengine_execute(engine, sql):
  #If sqlalchemy version starts with 1.4 then do it the old way
  #print("In Here")
  sqlalchemy_version = version("sqlalchemy")
  if sqlalchemy_version.startswith('1.4.'):
    with engine.connect() as conn:
        #print("In Here 5")
        return conn.execute(text(sql))
  else:
    #otherwise do it the new way with transactions:
    with engine.connect() as conn:
        #print("In Here 6")
        #print(type(sql))
        result = conn.execute(sql)
        #print(result.inserted_primary_key())
        conn.commit()
    result = myengine_execute(upd_sql)

def get_ssdata(startdate, enddate=0, minvol=5000000, percshort=50.00, etfs=0):
    #print("Here")
    #print(percshort)
    file_date = re.sub("\/", "", startdate)
    input_date = startdate
    temp_start = startdate
    pd.set_option('display.max_rows', None)
    finra_df = pd.DataFrame()
    detail_df = pd.DataFrame()

    values = range(0)
    if enddate != 0:
        numDays = (datetime.strptime(enddate, '%Y%m%d') - datetime.strptime(startdate, '%Y%m%d')).days
        values = range(numDays + 1)
    else:
        numDays = 0
    etfOnly = True
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

    src_dir = os.path.dirname(os.path.abspath(__file__))

    for d in dates:
        finra_file = finra_dir + f'{d}.txt'
        try:
            ssdata_temp = get_csv(finra_file)
            ssdata_temp.drop(ssdata_temp.tail(1).index, inplace=True)  # drop last n rows
            start_time = time.time()
            sql = text("""
                INSERT INTO "FINRAFiles" ("Date", "FileURL") VALUES (:date, :file)
            """)
            sql = sql.bindparams(date=d, file=finra_file)
            #engine.execute(sql)
            #myengine_execute(engine, sql)
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
        SELECT * FROM "FINRAFileDetail" WHERE "Date" IN :datelist AND "TotalVolume" > :minvolume AND CAST("ShortVolume" AS Float)/CAST("TotalVolume" AS Float) >= :shortpercent ORDER BY "Date"
    """)
    #AND "ShortVolume/TotalVolume" >= :shortpercent
    #print("Here 12")
    select = select.bindparams(datelist=tuple(date_list), minvolume=minvol, shortpercent=(float(percshort)/100))
    finra_df = pd.read_sql(select, engine)

    engine.dispose()  # Close all checked in sessions

    if finra_df.empty:
        print("Empty DF - return first recent day with data")
        # return pd.DataFrame()
        return [finra_df.to_json(orient='records'), finra_df.to_json(orient='records')]
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

    while True:
        try:

            finra_df['Percentile'] = finra_df.TotalVolume.rank(pct=True)
            final_df = pd.DataFrame()

            if etfOnly:

                #print("Made it here!")
                # print(os.path.join(src_dir, mapping_file))
                etf_df = pd.read_csv(os.path.join(src_dir, data_dir, mapping_file))
                # print("Mapping File Pre Filter")
                # print(etfs)
                funds = ["SPX", "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XRT", "Other"]
                if etfs != 0:
                    # etf_df = etf_df[etf_df["Fund"].isin(list(funds.split(",")))]
                    etf_df = etf_df[etf_df["Fund"].isin(funds)]
                    # print("Mapping File Post Filter")
                    # print(etf_df)

                etf_symbols = etf_df["Fund"].to_frame()
                etf_symbols = etf_symbols.drop_duplicates()
                # print("ETFs")
                # print(etf_symbols)

                mapped_df = pd.merge(finra_df, etf_df, on='Symbol')
                mapped_df["Short%"] = mapped_df["ShortVolume"] / mapped_df["TotalVolume"]
                mapped_df["name"] = mapped_df["Fund"] + "." + mapped_df["Symbol"]

                mapped_df.drop(
                    columns=["Date", "ShortVolume", "ShortExemptVolume", "Name", "% Holding"], inplace=True)

                mapped_df['Short%'] = mapped_df['Short%'].apply(lambda x: round(x, decimals))
                #
                mapped_df.rename(columns={'Short%': 'value', 'TotalVolume': 'size','Symbol': 'symbol'}, inplace=True)
                mapped_df = mapped_df[mapped_df.name != '']
                final_df = mapped_df
                closingprices_df.rename(columns={'Symbol': 'symbol'}, inplace=True)
                final_df = pd.merge(mapped_df, closingprices_df, on='symbol')
                # print("Final DF ...", final_df)

            else:
                finra_df["Short%"] = finra_df["ShortVolume"] / finra_df["TotalVolume"]
                finra_df["name"] = "None." + finra_df["Symbol"]

                finra_df.drop(
                    # columns=['Market', "Date", "ShortVolume", "ShortExemptVolume", "Symbol"],
                    # inplace=True)
                    columns=["Date", "ShortVolume", "ShortExemptVolume", "Symbol"], inplace=True)
                decimals = 2
                finra_df['Short%'] = finra_df['Short%'].apply(lambda x: round(x, decimals))
                finra_df = finra_df[finra_df["Short%"] != 0]
                finra_df.rename(columns={'Short%': 'value', 'TotalVolume': 'size'}, inplace=True)
                finra_df = finra_df[finra_df.name != '']
                final_df = finra_df

                # writer = pd.ExcelWriter("SSData.xlsx", engine='xlsxwriter')
                # ssdata_temp.to_excel(writer,sheet_name=file_date, index=False)
                # print(os.path.join(src_dir, data_dir, "SSData.csv"))
                # final_df.to_csv(os.path.join(src_dir, data_dir, "SSData.csv"), sep=',', encoding='utf-8', index=False)
                # print(mapped_df)
                # writer.save()










        except requests.HTTPError as e:
            print(f"[!] Exception caught: {e}{file_date}")
            prior_day = datetime.strptime(file_date, '%Y%m%d') - timedelta(days=1)
            file_date = prior_day.strftime("%Y%m%d")  # YYmmdd
            # Ideally we iterate backwards for start date providing most recent ... would then need to update dropdown
            continue
        pd.set_option('display.max_columns', 500)

        return [final_df.to_json(orient='records'), detail_df.to_json(orient='records')]
