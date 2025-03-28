import csv
import json

import pandas as pd
from flask import Flask, render_template, jsonify, session

from finra import get_ssdata
from flask_session import Session

# Initiate Flask Application
app = Flask(__name__)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Import DataFrame
# PATH_IN = r'static\data\miserables.json'
CSV_IN = r'flare-2.csv'
JSON_OUT = r'SSData.json'


def csv_to_json(csvFilePath, jsonFilePath):
    jsonArray = []

    # read csv file
    with open(csvFilePath, encoding='utf-8') as csvf:
        # load csv file data using csv library's dictionary reader
        csvReader = csv.DictReader(csvf)

        # convert each csv row into python dict
        for row in csvReader:
            # add this python dict to json array
            jsonArray.append(row)

    # convert python jsonArray to JSON String and write to file
    with open(jsonFilePath, 'w', encoding='utf-8') as jsonf:
        jsonString = json.dumps(jsonArray, indent=4)
        jsonf.write(jsonString)


# Routing do define url
@app.route('/')
def index():
    # get_ssdata("20230404", "20230404")
    return render_template('index.html')


@app.route('/treemap/<start_date>/<end_date>/<min_vol>/<perc_short>/<etfs>')
def treemap(start_date=0, end_date=0, min_vol=5000000, perc_short=50, etfs=0):
    #print("In treemap path: start_date = " + start_date + " min_vol=" + min_vol + " perc_short = " + perc_short)
    finraList = []
    if start_date:
        finra_df = pd.DataFrame()
        finra_detail = pd.DataFrame()

        try:
            if not session.get("data"):
                # fetching data for selected date range from FINRA
                session['startdate'] = start_date
                session['enddate'] = end_date
                session['minvol'] = min_vol
                session['percshort'] = perc_short
                #print("Are we here?")
                finraList = get_ssdata(start_date, end_date, min_vol, perc_short, etfs)
                finra_df = finraList[0]
                finra_detail = finraList[1]
                session['data'] = finra_df
                session['dataDetail'] = finra_detail
            else:
                if session['startdate'] == start_date and session['enddate'] == end_date and session[
                    'minvol'] == min_vol and session['percshort'] == perc_short:
                    finra_df = session['data']
                else:
                    session['startdate'] = start_date
                    session['enddate'] = end_date
                    session['minvol'] = min_vol
                    session['percshort'] = perc_short
                    #print("Or here?")
                    finraList = get_ssdata(start_date, end_date, min_vol, perc_short, etfs)
                    finra_df = finraList[0]
                    finra_detail = finraList[1]
                    session['data'] = finra_df
                    session['dataDetail'] = finra_detail
            # Check to see if DF is empty and need to reload most recent available period
            if finraList == ['[]', '[]']:
                raise Exception("No data for selected timeframe")
            temp_df = pd.read_json(finra_df)
            temp_df = temp_df[temp_df["Fund"].isin(list(etfs.split(",")))]
            finra_df = temp_df.to_json(orient='records')
            finraList = [finra_df, finra_detail]
            return finra_df

        except Exception as e:
            print(e)
            return finra_df

    else:
        return jsonify({"error": "Could not load data for " + start_date})


@app.route('/barchart/<symbol>')
def barchart(symbol):
    finra_detail = session['dataDetail']
    temp_df = pd.read_json(finra_detail)
    temp_df = temp_df.loc[temp_df['Symbol'] == symbol]
    temp_df["Date"] = pd.to_datetime(temp_df["Date"], format='%Y%m%d').dt.strftime('%m-%d-%Y')
    temp_df['Date'] = temp_df['Date'].astype(str)
    finra_detail = temp_df.to_json(orient='records')
    return finra_detail


@app.route('/get-json', methods=['GET', 'POST'])
def get_json():
    ''' Send JSON data to Javascript '''
    # Import Data
    csv_to_json(CSV_IN, JSON_OUT)
    with open(JSON_OUT) as f:
        json_to = json.load(f)
    return jsonify(json_to)


# @app.route('/update-data', methods=['GET', 'POST'])
# def update_data():
#     get_ssdata("2022/12/08")


if __name__ == '__main__':
    # Threaded option to enable multiple instances for multiple user access support
    app.run(debug=True, port=5000)
