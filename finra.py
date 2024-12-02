import io
import os
import re
import time
from datetime import datetime
from datetime import timedelta

import pandas as pd
import requests
from sqlalchemy import MetaData, Table, Column, String, BIGINT, ForeignKey, text, Float
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy_utils import database_exists, create_database

from local_settings import postgresql as settings

finra_dir = r'https://cdn.finra.org/equity/regsho/daily/CNMSshvol'
data_dir = r'static/data/'
mapping_file = 'etfMapping-backup.csv'
min_volume = 5000000  # 5M shares traded daily min


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
    #if not database_exists(url):
    #    create_database(url)
    #postgresql://pguser:zmfLzC3hqRf43N5abIpIbdkmllswE9Hj@dpg-ct6h009u0jms7396hdkg-a.oregon-postgres.render.com/alpha_flsq
    #postgresql://pguser:zmfLzC3hqRf43N5abIpIbdkmllswE9Hj@dpg-ct6h009u0jms7396hdkg-a/alpha_flsq
    engine = create_engine(
        "postgresql://pguser:zmfLzC3hqRf43N5abIpIbdkmllswE9Hj@dpg-ct6h009u0jms7396hdkg-a/alpha_flsq",
        pool_size=50, echo=False)
    return engine


def get_engine_from_settings():
    keys = ['pguser', 'pgpasswd', 'pghost', 'pgport', 'pgdb']
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


def get_ssdata(startdate, enddate=0, minvol=5000000, etfs=0):
    print("Here")
    print(minvol)
    file_date = re.sub("\/", "", startdate)
    input_date = startdate
    temp_start = startdate
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

    metadata = MetaData()

    finra_files = Table('FINRAFiles', metadata,
                        Column('Date', BIGINT, primary_key=True),
                        Column('FileURL', String(100))
                        )

    finra_file_detail = Table('FINRAFileDetail', metadata,
                              Column('Date', BIGINT, ForeignKey('FINRAFiles.Date'), nullable=False),
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
            print(row.Date)
            # remove entries that already exist
            dates.remove(str(row.Date))

    print("Still need to load files from FINRA for ... ", dates)

    # engine = session.get_bind()

    # Retrieve dates from database to determine if any additional FINRA files are needed

    # pg_conn = psycopg2.connect(conn_string)
    #
    # session = get_session()
    # # result = session.execute('''Select DISTINCT("Date") from to_finra_test''')
    # result = session.execute(sa.text(sql_string))
    # for e in result:
    #     print(e.date)
    # session.close()

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
            engine.execute(sql)

            # start_time = time.time()
            #
            # etf_df = pd.read_csv(os.path.join(src_dir, data_dir, mapping_file))
            # funds = ["SPX", "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XRT"];
            # etf_df = etf_df[etf_df["Fund"].isin(funds)]
            #
            # mapped_df = pd.merge(ssdata_temp, etf_df, on='Symbol')
            # mapped_df.drop(
            #     columns=["Name", "% Holding"], inplace=True)
            # print(mapped_df)
            # tickers = Ticker(mapped_df['Symbol'])
            # # Start date for Yahoo Finance data should still be the min date in the FINRA df
            # # start = datetime.strptime(str(finra_df["Date"].min()), '%Y%m%d')
            # start = datetime.strptime(d, '%Y%m%d')
            # end = datetime.strptime(d, '%Y%m%d') + timedelta(days=1)
            # # Set YFinance end date to the min of FINRA end date and current date - 1. Don't want to deal with Yahoo formatting for current date
            # print("Start Date: ", start)
            # print("End Date: ", end)
            # pricedf = tickers.history(start=start, end=end)
            # print("Made it here5!")
            # # Flatten multi index df to simplify data manipulation
            # pricedf = pricedf.reset_index().astype(str)
            # print(pricedf)
            # print("Time to load Tickers from Yahoo Finance: {} seconds".format(time.time() - start_time))

            ssdata_temp.to_sql('FINRAFileDetail', con=engine, if_exists='append', index=False)
            # sql = '''
            # COPY copy_test
            # FROM 'PATH_TO_FILE.csv' --input full file path here. see line 46
            # DELIMITER ',' CSV;
            # '''
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
            engine.execute(sql)

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
        SELECT * FROM "FINRAFileDetail" WHERE "Date" IN :datelist AND "TotalVolume" > :minvolume
    """)
    print(minvol)
    select = select.bindparams(datelist=tuple(date_list), minvolume=minvol)
    # engine.execute(select)
    finra_df = pd.read_sql(select, engine)
    engine.dispose()  # Close all checked in sessions

    # while True:
    #     for i in values:
    #         cur_day = datetime.strptime(temp_start, '%Y%m%d') + timedelta(days=i)
    #         file_date = cur_day.strftime('%Y%m%d')
    #         finra_file = finra_dir + f'{file_date}.txt'
    #         try:
    #             ssdata_temp = get_csv(finra_file)
    #             # start_time = time.time()
    #             # ssdata_temp.to_sql('to_finra_test', con=conn, if_exists='replace', index=False)
    #             # print("to_sql duration: {} seconds".format(time.time() - start_time))
    #             temp_df = ssdata_temp[(ssdata_temp.TotalVolume > min_volume)]
    #             if finra_df.empty:
    #                 finra_df = temp_df.copy()
    #             else:
    #                 finra_df = pd.concat([finra_df, temp_df.copy()], axis=0)
    #             temp_start = input_date
    #         except requests.HTTPError as e:
    #             print(f"[!] Exception caught: {e}{file_date}")
    #             # Create entry in db to indicate no file ONLY if date is not today
    #             sql = f'''INSERT INTO finra_no_file (date) VALUES ({file_date}) ON CONFLICT (date) DO NOTHING'''
    #             # cur = pg_conn.cursor()
    #             # cur.execute(table_create_sql)
    #             # cur.execute(sql)
    #             # pg_conn.commit()
    #             # cur.close()
    #             if numDays == 0:
    #                 prior_day = datetime.strptime(temp_start, '%Y%m%d') - timedelta(days=1)
    #                 temp_start = prior_day.strftime('%Y%m%d')
    #                 finra_file = finra_dir + f'{temp_start}.txt'
    #             continue
    #
    #     if temp_start == input_date:
    #         break

    if finra_df.empty:
        print("Empty DF - return first recent day with data")
        # return pd.DataFrame()
        return [finra_df.to_json(orient='records'), finra_df.to_json(orient='records')]
    yfMaxDate = finra_df["Date"].max()
    # Master df with daily totals that will be used for detailed breakdown
    detail_df = finra_df.copy()
    detail_df["LongVolume"] = detail_df["TotalVolume"] - detail_df["ShortVolume"]
    detail_df.drop(columns=["ShortExemptVolume", "Market"], inplace=True)
    finra_df = finra_df.groupby('Symbol').sum().reset_index()

    while True:
        try:
            # print("In Try")
            # print(file_date)
            # finra_file = finra_dir + f'{file_date}.txt'
            # print(finra_file)
            # ssdata_temp = get_csv(finra_file)
            # print("FINRA File")
            # finra_df = ssdata_temp[(ssdata_temp.TotalVolume > min_volume)]

            finra_df['Percentile'] = finra_df.TotalVolume.rank(pct=True)

            # finra_df = finra_df[(finra_df.Percentile > 0.5)]
            # src_dir = os.path.dirname(os.path.abspath(__file__))
            final_df = pd.DataFrame()

            if etfOnly:

                print("Made it here!")
                # print(os.path.join(src_dir, mapping_file))
                etf_df = pd.read_csv(os.path.join(src_dir, data_dir, mapping_file))
                # print("Mapping File Pre Filter")
                # print(etfs)
                funds = ["SPX", "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XRT", "Other"];
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
                # print("Mapped File")
                # print(mapped_df)

                mapped_df["Short%"] = mapped_df["ShortVolume"] / mapped_df["TotalVolume"]
                mapped_df["name"] = mapped_df["Fund"] + "." + mapped_df["Symbol"]

                print("Made it here2!")

                # start_time = time.time()
                # tickers = Ticker(mapped_df['Symbol'])
                #
                #
                # print("Made it here3!")
                #
                # # Start date for Yahoo Finance data should still be the min date in the FINRA df
                # start = datetime.strptime(str(finra_df["Date"].min()), '%Y%m%d')
                #
                # # end = datetime.strptime(enddate, '%Y%m%d')
                #
                # # Set YFinance end date to the min of FINRA end date and current date - 1. Don't want to deal with Yahoo formatting for current date
                # # print(yfMaxDate)
                # end = min([datetime.strptime(str(yfMaxDate), '%Y%m%d') + timedelta(days=1), datetime.today() + timedelta(days=1)])
                # if start == end:
                #     print("Start = End")
                # # print("Start Date: ", start)
                # # print("End Date: ", end)
                # print("Made it here4!", start, end)
                # pricedf = tickers.history(start=start, end=end)
                # print("Time to load Tickers from Yahoo Finance: {} seconds".format(time.time() - start_time))
                # # Flatten multi index df to simplify data manipulation
                # pricedf = pricedf.reset_index().astype(str)
                # print(pricedf)
                # print("End of price df")
                # closingprices_df = pd.DataFrame()
                #
                # if end.date() > datetime.today().date():
                #     end = end - timedelta(days=1)
                #
                # if start.date() == datetime.today().date():
                #     closingprices_df = pricedf
                #     closingprices_df['gain'] = 0
                # else:
                #     start_df = pricedf[(pricedf.date == start.strftime('%Y-%m-%d'))]
                #     # print(start_df)
                #     # end_df = pricedf[(pricedf.date == (end - timedelta(days=1)).strftime('%Y-%m-%d'))]
                #     end_df = pricedf[(pricedf.date == (end - timedelta(days=1)).strftime('%Y-%m-%d'))]
                #     # print("End DF")
                #     # print(end_df)
                #     closingprices_df = start_df
                #     if not end_df.empty:
                #         # print("End DF not empty")
                #         closingprices_df = pd.merge(start_df, end_df, on='symbol')
                #         closingprices_df[['close_x', 'close_y']] = closingprices_df[['close_x','close_y']].astype(float)
                #         closingprices_df['gain'] = ((closingprices_df['close_y']/closingprices_df['close_x'])-1)
                #         closingprices_df.drop(columns=["close_x", "close_y"], inplace=True)
                #     else:
                #         closingprices_df['gain'] = 0
                #         closingprices_df.drop(columns=["close"], inplace=True)

                mapped_df.drop(
                    columns=["Date", "ShortVolume", "ShortExemptVolume", "Name", "% Holding"], inplace=True)
                decimals = 2
                mapped_df['Short%'] = mapped_df['Short%'].apply(lambda x: round(x, decimals))
                # closingprices_df['gain'] = closingprices_df['gain'].apply(lambda x: round(x, decimals))
                mapped_df.rename(columns={'Short%': 'value', 'TotalVolume': 'size', 'Symbol': 'symbol'}, inplace=True)
                mapped_df = mapped_df[mapped_df.name != '']
                mapped_df['gain'] = 0
                final_df = mapped_df
                # final_df = pd.merge(mapped_df, closingprices_df, on='symbol')
                # print("Closing Prices DF ...", closingprices_df)

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
