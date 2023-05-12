import pandas as pd
from flask import Flask, render_template, request, redirect, jsonify, make_response, session
from flask_session import Session
import json
import csv
from finra import get_ssdata
from datetime import datetime

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


@app.route('/treemap/<start_date>/<end_date>/<etfs>')
def treemap(start_date=0, end_date=0, etfs=0):
    finraList =[]
    if start_date:
        finra_df = pd.DataFrame()
        finra_detail = pd.DataFrame()
        if not session.get("data"):
            # fetching data for selected date range from FINRA
            session['startdate'] = start_date
            session['enddate'] = end_date
            finraList = get_ssdata(start_date, end_date, etfs)
            finra_df = finraList[0]
            finra_detail = finraList[1]
            session['data'] = finra_df
            session['dataDetail'] = finra_detail
        else:
            if session['startdate'] == start_date and session['enddate'] == end_date:
                finra_df = session['data']
            else:
                session['startdate'] = start_date
                session['enddate'] = end_date
                finraList = get_ssdata(start_date, end_date, etfs)
                finra_df = finraList[0]
                finra_detail = finraList[1]
                session['data'] = finra_df
                session['dataDetail'] = finra_detail
        temp_df = pd.read_json(finra_df)
        temp_df = temp_df[temp_df["Fund"].isin(list(etfs.split(",")))]
        finra_df = temp_df.to_json(orient='records')
        finraList = [finra_df, finra_detail]
        return finra_df

    else:
        return jsonify({"error": "Could not load data for " + start_date})

@app.route('/barchart/<symbol>')
def barchart(symbol):
    finra_detail = session['dataDetail']
    temp_df = pd.read_json(finra_detail)
    temp_df = temp_df.loc[temp_df['Symbol'] == symbol]
    temp_df["Date"] = pd.to_datetime(temp_df["Date"],format='%Y%m%d').dt.strftime('%m-%d-%Y')
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



