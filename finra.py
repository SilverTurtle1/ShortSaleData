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
from markupsafe import escape


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
            temp_df = ssdata_temp[(ssdata_temp.TotalVolume > min_volume)]
            if finra_df.empty:
                finra_df = temp_df.copy()
            else:
                finra_df = pd.concat([finra_df, temp_df.copy()], axis=0)

        except requests.HTTPError as e:
            print(f"[!] Exception caught: {e}{file_date}")
            continue

    if finra_df.empty:
        print("Problem!")
        df_empty = pd.DataFrame([['NONE','1','B','1','1','None.None','2023-04-04','1','1','1','1','1','1','1']],
                                columns=['symbol', 'size', 'Market', 'Percentile', 'value', 'name', 'date', 'open', 'high',
                                         'low', 'close', 'volume', 'adjclose','gain'])
        return df_empty
    yfMaxDate = finra_df["Date"].max()
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

            finra_df['Percentile'] = finra_df.TotalVolume.rank(pct = True)
            # finra_df = finra_df[(finra_df.Percentile > 0.5)]
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

                # Start date for Yahoo Finance data should still be the min date in the FINRA df
                start = datetime.strptime(str(finra_df["Date"].min()), '%Y%m%d')

                # end = datetime.strptime(enddate, '%Y%m%d')

                # Set YFinance end date to the min of FINRA end date and current date - 1. Don't want to deal with Yahoo formatting for current date
                print(yfMaxDate)
                end = min([datetime.strptime(str(yfMaxDate), '%Y%m%d') + timedelta(days=1), datetime.today() + timedelta(days=1)])
                if start == end:
                    print("Start = End")
                print("Start Date: ", start)
                print("End Date: ", end)

                pricedf = tickers.history(start=start, end=end)
                # Flatten multi index df to simplify data manipulation
                pricedf = pricedf.reset_index().astype(str)
                # print(pricedf)
                closingprices_df = pd.DataFrame()

                if end.date() > datetime.today().date():
                    end = end - timedelta(days=1)

                if start.date() == datetime.today().date():
                    closingprices_df = pricedf
                    closingprices_df['gain'] = 0
                else:
                    start_df = pricedf[(pricedf.date == start.strftime('%Y-%m-%d'))]
                    # print(start_df)
                    # end_df = pricedf[(pricedf.date == (end - timedelta(days=1)).strftime('%Y-%m-%d'))]
                    end_df = pricedf[(pricedf.date == end.strftime('%Y-%m-%d'))]
                    # print(end_df)
                    closingprices_df = pd.merge(start_df, end_df, on='symbol')
                    closingprices_df[['close_x', 'close_y']] = closingprices_df[['close_x','close_y']].astype(float)
                    closingprices_df['gain'] = ((closingprices_df['close_y']/closingprices_df['close_x'])-1)
                    closingprices_df.drop(columns=["close_x", "close_y"], inplace=True)

                mapped_df.drop(
                    columns=["Date", "ShortVolume", "ShortExemptVolume", "Name", "% Holding", "Fund"], inplace=True)
                decimals = 2
                mapped_df['Short%'] = mapped_df['Short%'].apply(lambda x: round(x, decimals))
                closingprices_df['gain'] = closingprices_df['gain'].apply(lambda x: round(x, decimals))
                mapped_df.rename(columns={'Short%': 'value', 'TotalVolume': 'size', 'Symbol': 'symbol'}, inplace=True)
                mapped_df = mapped_df[mapped_df.name != '']
                final_df = pd.merge(mapped_df, closingprices_df, on='symbol')

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
        # print(final_df)
        return final_df.to_json(orient='records')

