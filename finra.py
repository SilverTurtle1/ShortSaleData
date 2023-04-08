import pandas as pd
import urllib
import xml.etree.ElementTree as ET
import requests
import io
import os
import re
from datetime import datetime
from datetime import timedelta
import yfinance as yf
from yahooquery import Ticker


finra_dir = r'https://cdn.finra.org/equity/regsho/daily/CNMSshvol'
data_dir = r'static/data/'
mapping_file = 'etfMapping-backup.csv'
min_volume = 5000000


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

def get_ssdata(startdate, enddate=0, etfs=0):




    # data = yf.download('AAPL', start="2023-01-01", end="2023-03-30")
    # print(data)

    file_date = re.sub("\/", "", startdate)
    finra_df = pd.DataFrame()

    values = range(0)
    if enddate != 0:
        numDays = (datetime.strptime(enddate, '%Y%m%d') - datetime.strptime(startdate, '%Y%m%d')).days
        values = range(numDays + 1)
    else:
        numDays = 0

    etfOnly = True

    for i in values:
        cur_day = datetime.strptime(startdate, '%Y%m%d') + timedelta(days=i)
        file_date = cur_day.strftime('%Y%m%d')
        finra_file = finra_dir + f'{file_date}.txt'
        try:
            ssdata_temp = get_csv(finra_file)
            # print("FINRA File")
            # print(i)
            temp_df = ssdata_temp[(ssdata_temp.TotalVolume > min_volume)]
            # print(temp_df)
            if finra_df.empty:
                finra_df = temp_df.copy()
                # print("finra_df was empty")
            else:
                # print("append to finra_df")
                # finra_df = finra_df.append(temp_df.copy())
                finra_df = pd.concat([finra_df, temp_df.copy()], axis=0)

        except requests.HTTPError as e:
            print(f"[!] Exception caught: {e}{file_date}")
            continue
            # if finra_df.empty:
            #     prior_day = datetime.strptime(file_date, '%Y%m%d') - timedelta(days=1)

    # print("Post Loop")
    # print(finra_df)
    finra_df = finra_df.groupby('Symbol').sum().reset_index()
    # print(finra_df)

    while True:
        try:
            # print("In Try")
            # print(file_date)
            # finra_file = finra_dir + f'{file_date}.txt'
            # print(finra_file)
            # ssdata_temp = get_csv(finra_file)
            # print("FINRA File")
            # finra_df = ssdata_temp[(ssdata_temp.TotalVolume > min_volume)]

            finra_df['Percentile'] = finra_df.TotalVolume.rank(pct = True)
            finra_df = finra_df[(finra_df.Percentile > 0.5)]
            # print(finra_df)
            src_dir = os.path.dirname(os.path.abspath(__file__))
            final_df = pd.DataFrame()

            if etfOnly:

                # print(os.path.join(src_dir, mapping_file))
                etf_df = pd.read_csv(os.path.join(src_dir, data_dir, mapping_file))
                # print("Mapping File Pre Filter")
                # print(etfs)
                if etfs != 0:
                    etf_df = etf_df[etf_df["Fund"].isin(list(etfs.split(",")))]
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

                tickers = Ticker(mapped_df['Symbol'])
                # tickers = Ticker("MSFT, AAPL")
                # print(faang.summary_detail['meta'])

                start = datetime.strptime(startdate, '%Y%m%d')
                end = datetime.strptime(enddate, '%Y%m%d')
                # print(start)
                # print(end)
                pricedf = tickers.history(start=start.strftime('%Y-%m-%d'), end=(end + timedelta(days=1)).strftime('%Y-%m-%d'))
                # print('price df row count ', len(pricedf.index))
                # print("Yahoo Finance df")


                # Flatten multi index df to simplify data manipulation
                pricedf = pricedf.reset_index().astype(str)
                # Need to ensure start and end dates are actual trading days - better to use min and max from df and not input date range
                # start_df = pricedf[(pricedf.date == start.strftime('%Y-%m-%d'))][['symbol', 'close']].copy()
                start_df = pricedf[(pricedf.date == min(pricedf.date))]
                end_df = pricedf[(pricedf.date == max(pricedf.date))]
                # end_df = pricedf[(pricedf.date == end.strftime('%Y-%m-%d'))][['symbol', 'close']].copy()
                # print(start_df)
                # print(end_df)
                # print('start df row count ', len(start_df.index))
                # print('end df row count ', len(end_df.index))
                closingprices_df = pd.merge(start_df, end_df, on='symbol')
                # print(closingprices_df)
                closingprices_df[['close_x', 'close_y']] = closingprices_df[['close_x','close_y']].astype(float)
                closingprices_df['gain'] = ((closingprices_df['close_y']/closingprices_df['close_x'])-1)
                closingprices_df['rectColor'] = ""
                # print(closingprices_df)
                # print('mapped df row count ', len(mapped_df.index))
                # print('closing prices row count ', len(closingprices_df.index))
                # print('Now Here')



                # print(pricedf[['symbol', 'close']].values)

                # mapped_df.drop(
                #     columns=['Market', "Date", "ShortVolume", "ShortExemptVolume", "Name", "Symbol", "% Holding", "Fund"],
                #     inplace=True)

                mapped_df.drop(
                    columns=["Date", "ShortVolume", "ShortExemptVolume", "Name", "% Holding", "Fund"], inplace=True)
                decimals = 2
                mapped_df['Short%'] = mapped_df['Short%'].apply(lambda x: round(x, decimals))
                closingprices_df['gain'] = closingprices_df['gain'].apply(lambda x: round(x, decimals))

                # ssdata_temp.loc[0] = ["", "", "origin"]  # adding a row
                # ssdata_temp = ssdata_temp.drop(ssdata_temp.index[-1]) # delete last row

                mapped_df.rename(columns={'Short%': 'value', 'TotalVolume': 'size', 'Symbol': 'symbol'}, inplace=True)
                mapped_df = mapped_df[mapped_df.name != '']


                # print(mapped_df)
                # print(closingprices_df)
                final_df = pd.merge(mapped_df, closingprices_df, on='symbol')
                final_df.drop(columns=["close_x", "close_y", "symbol"], inplace=True)
                # final_df = mapped_df
                # print(final_df)
                # print('treemap row count ', len(final_df.index))
            else:
                finra_df["Short%"] = finra_df["ShortVolume"] / finra_df["TotalVolume"]
                finra_df["name"] = "None." + finra_df["Symbol"]
                # print("HERE0")



                finra_df.drop(
                    # columns=['Market', "Date", "ShortVolume", "ShortExemptVolume", "Symbol"],
                    # inplace=True)
                    columns=["Date", "ShortVolume", "ShortExemptVolume", "Symbol"], inplace=True)
                decimals = 2
                finra_df['Short%'] = finra_df['Short%'].apply(lambda x: round(x, decimals))
                finra_df = finra_df[finra_df["Short%"] != 0]
                # print("HERE1)")
                # ssdata_temp.loc[0] = ["", "", "origin"]  # adding a row
                # finra_df = finra_df.drop(finra_df.index[-1]) # delete last row
                finra_df.rename(columns={'Short%': 'value', 'TotalVolume': 'size'}, inplace=True)
                # print("HERE2)")
                finra_df = finra_df[finra_df.name != '']
                # print("HERE3)")
                final_df = finra_df


                # writer = pd.ExcelWriter("SSData.xlsx", engine='xlsxwriter')
                # ssdata_temp.to_excel(writer,sheet_name=file_date, index=False)
                # print(os.path.join(src_dir, data_dir, "SSData.csv"))
                # final_df.to_csv(os.path.join(src_dir, data_dir, "SSData.csv"), sep=',', encoding='utf-8', index=False)
                # print(mapped_df)
                # writer.save()

            # symbols = ['meta', 'aapl', 'amzn', 'nflx', 'googl']


        except requests.HTTPError as e:
            print(f"[!] Exception caught: {e}{file_date}")
            prior_day = datetime.strptime(file_date, '%Y%m%d') - timedelta(days=1)
            # prior_day = startdate - timedelta(days=1)

            # print(prior_day)
            file_date = prior_day.strftime("%Y%m%d")  # YYmmdd
            # Ideally we iterate backwards for start date providing most recent ... would then need to update dropdown

            continue
        # print("dataframe")
        # print(final_df)
        # print("Display JSON")
        # print(final_df.to_json(orient='records'))
        return final_df.to_json(orient='records')






